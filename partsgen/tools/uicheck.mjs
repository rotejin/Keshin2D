// 画面の操作を、ヘッドレス Chrome を実際に動かして確かめる（実時間で動かす。撮影用の早送りは使わない）。
//
//   node partsgen/tools/uicheck.mjs <モデル名> <出力フォルダ> [URL に足す指定]
//
// 操作パネルは 3 層: ふだんの画面（動かし方・マイク・口パクデモ・表情・背景）／好みに合わせる／キャラを作る人向け。
// やること: ページを開く → 読み込みを待つ → フレームが進んでいるか → 折りたたみが全部閉じているか →
//           ふだんの画面: 口パクデモ、ドラッグで位置・ホイールで大きさ・ダブルクリックで戻す、表情（数字キーと、全部のボタン）、
//                         動かし方、背景、パネルを隠す・出す →
//           好みに合わせる: 動きの好み（まとめボタン・飾りごと）、向きの上限（9 方向のボタンと上限）、母音の口の大きさ、全部もとに戻す →
//           キャラを作る人向け: 髪の表示、中の項目を全部開いてスライダーを動かす →
//           OBS 用の URL を作る → スクリプトのエラー・コンソールの警告とエラー・読み込みの失敗が無いか →
//           Web カメラ（Chrome のテスト用の偽のカメラ。実際のカメラは使わない）を、ボタンと URL（mode=camera）の両方で開く →
//           OBS 用の URL を開いて、パネルが出ず、値が渡っているか → 外への通信が無いか。終わりに保存値（localStorage）を消す。マイクは押さない。
// 途中の画面を <出力フォルダ>/ui_*.png に書く。結果は標準出力に 1 行ずつ出す（ok / NG）。
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { closeChrome, CHROME, profDir, CHROME_FLAGS, RENDER_FLAGS, lowPriority } from './chromeclose.mjs';
lowPriority();   // PC を重くしない: 優先度を下げてから Chrome を起動する（chromeclose.mjs に経緯）

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const [model = 'kurage02', outDir = path.join(tmpdir(), 'uicheck'), extra = ''] = process.argv.slice(2);
if (!CHROME) { console.log('NG Chrome / Edge が見つかりません（環境変数 AVATAR_CHROME で、実行ファイルを指定できます）'); process.exit(1); }
await mkdir(outDir, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- Keshin2D を配る
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.wasm': 'application/wasm' };
const server = createServer(async (req, res) => {
  try {
    const p = path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
    if (!p.startsWith(ROOT)) throw new Error('outside');
    const buf = await readFile(p);
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream', 'Cache-Control': 'no-store' }); res.end(buf);
  } catch (e) { res.writeHead(404); res.end(); }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

// ---- Chrome を起動して、操作用の接続（CDP）をつなぐ
const prof = profDir('uicheck');   // 使い回すプロファイル（chromeclose.mjs に経緯）
// Web カメラの確認は、Chrome のテスト用の偽のカメラで行う（許可の画面を出さない。実際のカメラの映像は使わない）
const chrome = spawn(CHROME, ['--headless=new', ...CHROME_FLAGS, ...RENDER_FLAGS, '--hide-scrollbars', '--window-size=1300,1000',
  '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
  '--remote-debugging-port=0', '--user-data-dir=' + prof, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
let ws = null, bad = 0, browserWs = '';
const finish = async (code) => {
  try { if (ws) ws.close(); } catch (e) { /* 閉じられなくてもよい */ }
  server.close();
  // Chrome に自分で終了させ、残っていれば子プロセスごと落とす（プロファイルは使い回すので、消さない。chromeclose.mjs に経緯）
  await closeChrome(chrome, browserWs);
  process.exit(code);
};
const wsUrl = browserWs = await new Promise((resolve, reject) => {
  let buf = ''; const t = setTimeout(() => reject(new Error('Chrome が起動しません')), 20000);
  chrome.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]); } });
}).catch((e) => { console.log('NG ' + e.message); return null; });
if (!wsUrl) await finish(1);
const base = wsUrl.replace('ws://', 'http://').replace(/\/devtools\/.*/, '');
const tabs = await (await fetch(base + '/json')).json();
ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
let seq = 0; const wait = new Map(); const errors = [], logs = [], reqs = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && wait.has(m.id)) { wait.get(m.id)(m); wait.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  // console.error・console.warn と、読み込みに失敗したファイル（404 など）も集める
  if (m.method === 'Runtime.consoleAPICalled' && (m.params.type === 'error' || m.params.type === 'warning')) logs.push(m.params.type + ': ' + m.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
  if (m.method === 'Network.responseReceived' && m.params.response.status >= 400) logs.push('HTTP ' + m.params.response.status + ': ' + m.params.response.url);
  if (m.method === 'Network.loadingFailed' && !m.params.canceled) logs.push('読み込みの失敗: ' + m.params.errorText);
  if (m.method === 'Network.requestWillBeSent') reqs.push(m.params.request.url);
};
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq; const t = setTimeout(() => { wait.delete(id); reject(new Error('応答なし: ' + method)); }, 15000);
  wait.set(id, (m) => { clearTimeout(t); m.error ? reject(new Error(m.error.message)) : resolve(m.result); });
  ws.send(JSON.stringify({ id, method, params }));
});
const ev = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
const shot = async (name) => { const r = await cdp('Page.captureScreenshot', { format: 'png' }); await writeFile(path.join(outDir, 'ui_' + name + '.png'), Buffer.from(r.data, 'base64')); };
const say = (ok, text) => { if (!ok) bad++; console.log((ok ? 'ok ' : 'NG ') + text); };
const mouse = (type, x, y, o = {}) => cdp('Input.dispatchMouseEvent', Object.assign({ type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1 }, o));
const click = async (x, y) => { await mouse('mousePressed', x, y); await mouse('mouseReleased', x, y); };
// 画面に見えている部品のまん中（見えていなければ null。隠れた部品を「押したつもり」にしない）
const center = (sel) => ev(`(() => { const e = ${sel}; if (!e || !e.getClientRects().length) return null; e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect(); return r.width && r.height ? [r.x + r.width / 2, r.y + r.height / 2] : null; })()`);
const q1 = (sel) => `document.querySelector(${JSON.stringify(sel)})`;
const byText = (sel, t) => `[...document.querySelectorAll(${JSON.stringify(sel)})].find((b) => b.textContent === ${JSON.stringify(t)})`;
const press = async (sel, pause = 250) => { const p = await center(sel); if (p) { await click(p[0], p[1]); await sleep(pause); } return !!p; };
const isOpen = (id) => ev(`${q1(`.sec[data-sec="${id}"]`)}?.classList.contains('open') === true`);
const openSec = async (id) => { if (!await isOpen(id)) await press(q1(`.sec[data-sec="${id}"] > .sechead`)); return isOpen(id); };
const key = async (k) => { const o = { key: k, text: k, code: /\d/.test(k) ? 'Digit' + k : 'Key' + k.toUpperCase(), windowsVirtualKeyCode: k.toUpperCase().charCodeAt(0) }; await cdp('Input.dispatchKeyEvent', Object.assign({ type: 'keyDown' }, o)); await cdp('Input.dispatchKeyEvent', Object.assign({ type: 'keyUp' }, o)); await sleep(150); };
const frames = (ms) => ev(`new Promise((r) => { let n = 0; const f = () => { n++; requestAnimationFrame(f); }; requestAnimationFrame(f); setTimeout(() => r(n), ${ms}); })`);
// つまみを、マウスで右の端（to = 1）か左の端（to = 0）までドラッグする。動かしたあとの「値（表示）」を返す
const dragSlider = async (labelExpr, to) => {
  const t = await ev(`(() => { const g = ${labelExpr}; if (!g || !g.getClientRects().length) return null; const i = g.querySelector('input'); i.scrollIntoView({ block: 'center' }); const r = i.getBoundingClientRect(); const k = (i.value - i.min) / (i.max - i.min);
    return [r.x + 6 + k * (r.width - 12), r.y + r.height / 2, ${to} ? r.x + r.width + 20 : r.x - 20]; })()`);
  if (!t) return null;
  await mouse('mousePressed', t[0], t[1]);
  for (let k = 1; k <= 8; k++) { await mouse('mouseMoved', t[0] + (t[2] - t[0]) * k / 8, t[1]); await sleep(40); }
  await mouse('mouseReleased', t[2], t[1]);
  return ev(`(() => { const g = ${labelExpr}; return g.querySelector('input').value + '（' + g.lastElementChild.textContent + '）'; })()`);
};
const labelOf = (rootSel, re) => `[...document.querySelectorAll(${JSON.stringify(rootSel + ' label.sl')})].find((l) => l.getClientRects().length && ${re}.test(l.textContent))`;
const pageUrl = (more) => `http://127.0.0.1:${port}/index.html?model=${model}&hair=1${more ? '&' + more : ''}${extra ? '&' + extra : ''}`;
const waitReady = async () => { let ready = false; for (let i = 0; i < 80 && !ready; i++) { await sleep(500); ready = await ev('window.__ready === true').catch(() => false); } return ready; };

try {
  await cdp('Runtime.enable'); await cdp('Page.enable'); await cdp('Network.enable');
  await cdp('Page.navigate', { url: pageUrl('') });
  const ready = await waitReady();
  say(ready, '読み込みが終わる');
  if (!ready) throw new Error('読み込みが終わりません: ' + errors.join(' / '));
  const fr1 = await frames(1500);
  say(fr1 > 10, `画面が動き続ける（1.5 秒で ${fr1} フレーム）`);
  await shot('1_closed');
  const secs = await ev('[...document.querySelectorAll(".sec")].map((d) => d.dataset.sec + ":" + d.classList.contains("open") + ":" + d.querySelector(".sechead").firstChild.textContent)');
  say(secs.length >= 6 && secs.every((s) => s.split(':')[1] === 'false'), `折りたたみの項目が ${secs.length} 個あり、最初は全部閉じている（${secs.map((s) => s.split(':')[2]).join('、')}）`);

  // ================= ふだんの画面 =================
  const modes = await ev(`[...document.querySelectorAll('#modes button')].map((b) => b.textContent)`);
  say(modes.length === 3 && await ev(`${q1('#modes button[data-mode="mouse"]')}.classList.contains('on')`), `動かし方は 3 つで、最初はマウス（${modes.join('・')}）`);
  // 口パクデモ（ふだんの画面にある）
  say(await press(q1('#demos #talkdemo'), 900), '「口パクデモ」のボタンが、ふだんの画面にある');
  await shot('3_talk_a'); await sleep(350); await shot('3_talk_b');
  say(await ev(`${q1('#talkdemo')}.classList.contains('on')`), '押すと、デモが動いている表示になる');
  await press(q1('#talkdemo'), 200);
  // 配置: ドラッグ・ホイール・ダブルクリック。保存された配置（モデル名.view.v1）を読んで確かめる
  const view = () => ev(`JSON.parse(localStorage.getItem(${JSON.stringify(model + '.view.v1')}) || "null")`);
  await mouse('mousePressed', 800, 500); await mouse('mouseMoved', 900, 560); await mouse('mouseMoved', 1000, 620); await mouse('mouseReleased', 1000, 620);
  await sleep(300); const v1 = await view();
  say(!!v1, 'ドラッグすると、配置が変わって保存される' + (v1 ? `（cx ${Math.round(v1.cx)}・cy ${Math.round(v1.cy)}）` : ''));
  await shot('4_dragged');
  await cdp('Input.dispatchMouseEvent', { type: 'mouseWheel', x: 800, y: 500, deltaX: 0, deltaY: -400 }); await sleep(300);
  const v2 = await view();
  say(!!v1 && !!v2 && v2.half < v1.half, 'ホイールを上へ回すと、大きくなる' + (v2 ? `（表示の半分の高さ ${Math.round(v1?.half)} → ${Math.round(v2.half)}）` : ''));
  await shot('5_zoomed');
  await mouse('mousePressed', 800, 500, { clickCount: 1 }); await mouse('mouseReleased', 800, 500, { clickCount: 1 });
  await mouse('mousePressed', 800, 500, { clickCount: 2 }); await mouse('mouseReleased', 800, 500, { clickCount: 2 });
  await sleep(300); const v3 = await view();
  say(!!v3 && !!v2 && v3.half > v2.half, 'ダブルクリックで、初期の配置に戻る');
  await shot('6_reset');
  // 表情: 数字キーで、上に並んだ表情に替わる → 「ほかの表情」を開いて、全部のボタンを押す
  const exprOn = () => ev(`document.querySelector('#exprs button.on')?.dataset.name || ''`);
  const favs = await ev(`[...document.querySelectorAll('#exprs .favs button')].map((b) => b.dataset.name)`);
  await key('3');
  const e3 = await exprOn();
  await key('1');
  say(favs.length >= 5 && e3 === favs[2] && await exprOn() === favs[0], `数字キーで表情が替わる（3 → ${e3}、1 → ${favs[0]}。上に並んだ表情 ${favs.length} 個: ${favs.join('・')}）`);
  await press(q1('#exprtoggle'));
  const exprs = await ev(`[...document.querySelectorAll('#exprs button')].map((b) => b.dataset.name)`);
  let pressed = 0, selected = 0;
  for (let i = 0; i < exprs.length; i++) if (await press(`document.querySelectorAll('#exprs button')[${i}]`, 220)) { pressed++; if (await exprOn() === exprs[i]) selected++; }
  await sleep(500); await shot('7_last_expr');
  say(pressed === exprs.length && selected === exprs.length && exprs.length > 0, `表情のボタンを全部押せて、押した表情が選ばれる（${selected} / ${exprs.length} 個: ${exprs.join('・')}）`);
  await press(`document.querySelectorAll('#exprs button')[0]`);
  await press(q1('#exprtoggle'));
  // 動かし方（カメラは、あとで別に確かめる）
  await press(q1('#modes button[data-mode="demo"]'), 1400);
  const demoOn = await ev(`${q1('#modes button[data-mode="demo"]')}.classList.contains('on')`), demoExpr = await exprOn();
  await press(q1('#modes button[data-mode="mouse"]'), 600);
  await shot('8_modes');
  say(demoOn && await ev(`${q1('#modes button[data-mode="mouse"]')}.classList.contains('on')`), '動かし方を切り替えられる（おまかせ → マウス。カメラは、あとで確かめる）');
  say(demoExpr !== '通常' && await exprOn() === '通常', `おまかせからマウスへ戻すと、表情が通常に戻る（おまかせの途中は「${demoExpr}」）`);
  await key('3'); await press(q1('#modes button[data-mode="mouse"]'), 300);
  say(await exprOn() === '通常', '表情を選んだあと「マウス」を押すと、表情が通常に戻る');
  // 背景: 色の丸を全部押す
  const bgs = await ev(`[...document.querySelectorAll('#bgs button')].map((b) => b.dataset.bg)`);
  let bgok = 0;
  for (const v of bgs) { await press(q1(`#bgs button[data-bg="${v}"]`), 120); if (await ev(`document.body.classList.contains('bg-${v}') && ${q1(`#bgs button[data-bg="${v}"]`)}.classList.contains('on')`)) bgok++; }
  await press(q1('#bgs button[data-bg="room"]'), 120);
  say(bgok === bgs.length && bgs.length === 5 && await ev(`document.body.classList.contains('bg-room')`), `背景を全部選べる（${bgs.join('・')}）`);
  // パネルを隠す → マウスを動かすと、隅に「出す」ボタンが出る → 押すと戻る
  await press(q1('#hide'));
  const hidden = await ev(`document.body.classList.contains('noui') && !${q1('#ui')}.getClientRects().length`);
  await mouse('mouseMoved', 700, 400, { buttons: 0 }); await mouse('mouseMoved', 720, 420, { buttons: 0 }); await sleep(200);
  await shot('9_hidden');
  const peek = await press(q1('#showui'));
  say(hidden && peek && await ev(`!document.body.classList.contains('noui')`), 'パネルを隠せて、マウスを動かすと出る「出す」ボタンで戻せる');
  await key('h'); const hk = await ev(`document.body.classList.contains('noui')`); await key('h');
  say(hk && await ev(`!document.body.classList.contains('noui')`), 'H キーでも、隠す・出すを切り替えられる');

  // ================= 好みに合わせる =================
  say(await openSec('prefs'), '「好みに合わせる」を押すと開く');
  await shot('10_prefs');
  // 動きの好み: まとめボタンで、3 本が一緒に変わる
  const userVals = () => ev(`[...document.querySelectorAll('#p_feel > label.sl')].map((l) => l.lastElementChild.textContent).join(' ')`);
  await press(byText('#presets button', '元気'));
  const uv1 = await userVals();
  await press(byText('#presets button', 'ふつう'));
  const uv2 = await userVals();
  say(uv1 !== uv2 && /^100% 100% 100%$/.test(uv2), `「動きの好み」のまとめボタンで、揺れ・体・瞳が一緒に変わる（元気 ${uv1} → ふつう ${uv2}）`);
  // まとめボタンを押すと、ためしの動き（顔を左右に振る）が入る（止まったままだと、揺れ方の違いが見えないため）
  await sleep(2600);   // 前のためしの動きが終わるのを待つ
  const yaw0 = Math.abs((await ev('window.__state()')).yaw);
  await press(byText('#presets button', '元気'), 0);
  let yawMax = 0; for (let i = 0; i < 12; i++) { await sleep(120); yawMax = Math.max(yawMax, Math.abs((await ev('window.__state()')).yaw)); }
  await shot('10b_preview');
  say(yaw0 < 6 && yawMax > 12, `まとめボタンを押すと、ためしに顔を振って見せる（顔の左右 ${yaw0.toFixed(1)} → 最大 ${yawMax.toFixed(1)}）`);
  await sleep(1500); await press(byText('#presets button', 'ふつう')); await sleep(2600);
  const swayV = await dragSlider(labelOf('#p_feel', '/髪と飾りの揺れ/'), 0);
  say(!!swayV && /^0（0%）/.test(swayV), `「髪と飾りの揺れ」を、いちばん左まで動かせる（${swayV}）`);
  await press(byText('#presets button', 'ふつう'));
  // 飾りごとの揺れ: そのモデルにある揺れ物が、名前つきで 1 本ずつ出る（無いモデルには、欄が無い）
  const nphys = await ev(`fetch('models/${model}/model.json').then((r) => r.json()).then((m) => (m.physics || []).length)`);
  if (await press(q1('#physuser'))) {
    const items = await ev(`[...document.querySelectorAll('#physuserbox label.sl')].filter((l) => l.getClientRects().length).map((l) => l.firstElementChild.textContent)`);
    say(items.length === nphys && nphys > 0, `「飾りごとに決める」に、このモデルの揺れ物 ${nphys} 個が、名前つきで出る（${items.join('・')}）`);
    await press(q1('#physuser'));
  } else say(nphys === 0, '飾りごとの揺れ（このモデルには、揺れ物が無いので、欄も無い）');
  // 向きの上限: 9 方向のボタンで顔を止めて、上限を動かす
  const ndir = await ev(`document.querySelectorAll('#p_limits #dirs button').length`);
  await press(byText('#dirs button', '右下'), 900);
  await shot('11_dir_limit');
  const manual = await ev(`document.body.classList.contains('mode-manual') && [...document.querySelectorAll('#dirs button')].some((b) => b.classList.contains('on'))`);
  const lim = await dragSlider(labelOf('#p_limits', '/左右の上限/'), 0);
  await sleep(700); await shot('11b_dir_limit_min');
  say(ndir === 9 && manual && !!lim, `9 方向のボタンで顔が止まり、止めたまま上限を動かせる（右下で止めて、左右の上限 → ${lim}。前後の画面: ui_11・ui_11b）`);
  const backOk = await press(q1('#dirback'), 400);
  say(backOk && await ev(`${q1('#modes button[data-mode="mouse"]')}.classList.contains('on') && !document.body.classList.contains('mode-manual')`), '「止めるのをやめる」で、前の動かし方（マウス）へ戻る');
  // 母音の口の大きさ: 母音を選んで、開きを最大にすると、口の形が変わる（前後の画面を ui_12b・ui_12c に書く）
  if (await press(byText('#vowelrow button', 'あ'), 2000)) {
    await shot('12b_vowel_a');
    const set = await dragSlider(labelOf('#vowels', '/開き/'), 1);
    await sleep(1500); await shot('12c_vowel_a_open_max');
    say(!!set, `「母音の口の大きさ」で「あ」を押すと、その形のスライダーが出て、開きを動かせる（${set}。前後の画面: ui_12b・ui_12c）`);
    await press(byText('#vowels button', '「あ」を初期値に戻す'), 200);
    await press(byText('#vowelrow button', 'あ'), 200);
  } else say(await ev(`!${q1('#vowels')}.getClientRects().length`), '母音の口の大きさ（このモデルには、無い）');
  say(await ev(`!!${q1('#lipwiz')} && document.querySelectorAll('#p_lip label.sl').length === 3`), '「マイクの口パク」に、スライダー 3 本と「声を覚えさせる」がある');
  // 全部もとに戻す
  const limBefore = await ev(`${labelOf('#p_limits', '/左右の上限/')}.querySelector('input').value`);
  await press(q1('#prefreset'), 300);
  const limAfter = await ev(`${labelOf('#p_limits', '/左右の上限/')}.querySelector('input').value`);
  say(limBefore !== limAfter, `「好みを全部もとに戻す」で、動かした上限が初期値に戻る（左右の上限 ${limBefore} → ${limAfter}）`);
  const nprefs = await ev(`[...document.querySelectorAll('#prefs input[type=range]')].filter((i) => i.getClientRects().length).length`);

  // ================= キャラを作る人向け =================
  say(await openSec('author'), '「キャラを作る人向け」を押すと開く');
  const hairOk = await press(q1('#hair'), 500);
  await shot('13_hair_toggled');
  if (hairOk) await press(q1('#hair'), 300);
  say(hairOk, '「髪を表示」を切り替えられる');
  // 中の項目を全部開いて、スライダーを動かす（値は、あとで保存を消して戻す）
  const inner = await ev(`[...document.querySelectorAll('#author .sec')].map((d) => d.dataset.sec)`);
  let sliders = 0, opened = 0;
  for (const id of inner) {
    if (await openSec(id)) opened++;
    sliders += await ev(`(() => { let n = 0; for (const inp of ${q1(`.sec[data-sec="${id}"]`)}.querySelectorAll('input[type=range]')) { if (!inp.getClientRects().length) continue;
      const v0 = inp.value; inp.value = (+inp.min + +inp.max) / 2; inp.dispatchEvent(new Event('input', { bubbles: true })); inp.value = v0; inp.dispatchEvent(new Event('input', { bubbles: true })); n++; } return n; })()`);
  }
  await sleep(500); await shot('14_author_open');
  const fr2 = await frames(1000);
  say(opened === inner.length && fr2 > 10, `中の項目 ${inner.length} 個（${inner.join('・')}）を全部開き、スライダー ${sliders} 本を動かしても、画面が動き続ける（1 秒で ${fr2} フレーム。「好みに合わせる」に見えているスライダーは ${nprefs} 本）`);
  await press(q1('#modes button[data-mode="mouse"]'), 300);   // 手で動かすスライダーを触ったので、マウスへ戻す

  // ================= OBS 用の URL =================
  await press(byText('#presets button', 'おちついた'));   // 値を変えてから作る（URL に入るか）
  await press(q1('#obsurl'), 400);
  const obs = await ev(`${q1('#obsbox')}?.value || ''`);
  let obsSet = null; try { obsSet = JSON.parse(new URL(obs).searchParams.get('set') || 'null'); } catch (e) { /* 下で NG になる */ }
  say(/[?&]ui=0(&|$)/.test(obs) && /bg=transparent/.test(obs) && obsSet?.user?.sway === 0.5, `「OBS 用の URL をコピー」で、パネルなし・透過・好みの値の入った URL ができる（${decodeURIComponent(obs.replace(/^http:\/\/127\.0\.0\.1:\d+/, '')).slice(0, 170)}）`);
  await shot('15_obs_url');

  say(errors.length === 0, 'スクリプトのエラーが出ていない' + (errors.length ? ': ' + errors.slice(0, 3).join(' / ') : ''));
  say(logs.length === 0, 'コンソールの警告・エラー、読み込みの失敗が無い' + (logs.length ? ': ' + logs.slice(0, 5).join(' / ') : ''));

  // ================= Web カメラ（偽のカメラ）。同梱の MediaPipe が、起動の記録をコンソールへ出すので、コンソールの確認のあとで行う
  const camWait = async () => { let st = ''; for (let i = 0; i < 80; i++) { await sleep(500); st = await ev('document.querySelector("#status")?.textContent || ""').catch(() => ''); if (/追従中|できませんでした/.test(st)) break; } return st; };
  const camMode = () => ev(`document.querySelector('#modes button.on')?.dataset.mode || ''`);
  const nErr = errors.length;
  await ev('document.querySelector("#ui").scrollTop = 0');
  await press(q1('#modes button[data-mode="camera"]'));
  let st = await camWait();
  say(/追従中/.test(st) && await camMode() === 'camera' && await ev(`!!${q1('#mirror')}.getClientRects().length`), `「カメラ」を押すと、追従が始まり、鏡写しの切り替えが出る（テスト用の偽のカメラ。表示「${st}」・選ばれている動かし方 ${await camMode()}）`);
  await sleep(1200); await shot('16_camera');
  // URL の mode=camera でも同じか（前は、表示だけ「追従中」になり、動かし方はマウスへ戻っていた）
  await cdp('Page.navigate', { url: pageUrl('mode=camera') });
  st = await camWait();
  say(/追従中/.test(st) && await camMode() === 'camera', `URL の mode=camera でも、追従が始まる（表示「${st}」・選ばれている動かし方 ${await camMode()}）`);
  say(errors.length === nErr, 'Web カメラで、スクリプトのエラーが出ていない' + (errors.length > nErr ? ': ' + errors.slice(nErr, nErr + 3).join(' / ') : ''));
  // ================= OBS 用の URL を開く: パネルも「出す」ボタンも出ず、好みの値が渡っている
  if (obs) {
    await ev('localStorage.clear()');   // OBS は別の保存場所なので、保存した値が無い状態で開く
    await cdp('Page.navigate', { url: obs });
    const r2 = await waitReady();
    await mouse('mouseMoved', 600, 400, { buttons: 0 }); await mouse('mouseMoved', 640, 420, { buttons: 0 }); await sleep(300);
    const pure = await ev(`document.body.classList.contains('noui') && !${q1('#ui')}.getClientRects().length && !${q1('#showui')}.getClientRects().length && document.body.classList.contains('bg-transparent')`);
    const got = await ev(`+document.querySelector('#p_feel > label.sl input').value`);
    await shot('17_obs_view');
    say(r2 && pure && Math.abs(got - 0.5) < 1e-6, `OBS 用の URL を開くと、パネルも「出す」ボタンも出ず、背景は透過で、好みの値が渡っている（髪と飾りの揺れ = ${got}）`);
  }
  const ext = reqs.filter((u) => !/^http:\/\/127\.0\.0\.1:/.test(u) && !/^(data|blob|about):/.test(u));
  say(ext.length === 0, `外への通信が無い（読み込み ${reqs.length} 件。Web カメラの部品は、同梱の vendor/mediapipe だけ）` + (ext.length ? ': ' + ext.slice(0, 3).join(' ') : ''));
  await ev('localStorage.clear()');   // 確かめるために変えた保存値を残さない
} catch (e) { say(false, e.message); }
console.log(bad ? `NG ${bad} 件。画面: ${outDir}` : `全部 ok。画面: ${outDir}`);
await finish(bad ? 1 : 0);
