// 画面の操作を、ヘッドレス Chrome を実際に動かして確かめる（実時間で動かす。撮影用の早送りは使わない）。
//
//   node partsgen/tools/uicheck.mjs <モデル名> <出力フォルダ> [URL に足す指定]
//
// やること: ページを開く → 読み込みを待つ → フレームが進んでいるか → 調整パネルの項目を開閉 →
//           話しているデモを押す → ドラッグで位置、ホイールで大きさ → ダブルクリックで戻す →
//           表情・口のデモ・動かし方・背景・髪の表示を全部押す → 折りたたみの項目を全部開いてスライダーを動かす →
//           スクリプトのエラー・コンソールの警告とエラー・読み込みの失敗が無いか →
//           Web カメラ（Chrome のテスト用の偽のカメラ。実際のカメラは使わない）を、ボタンと URL（mode=camera）の両方で開く →
//           外への通信が無いか。終わりに保存値（localStorage）を消す。マイクは押さない。
// 途中の画面を <出力フォルダ>/ui_*.png に書く。結果は標準出力に 1 行ずつ出す（ok / NG）。
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
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
let seq = 0; const wait = new Map(); const errors = [];
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
const logs = [], reqs = [];
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
const center = (sel) => ev(`(() => { const e = ${sel}; if (!e) return null; e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);

try {
  await cdp('Runtime.enable'); await cdp('Page.enable'); await cdp('Network.enable');
  await cdp('Page.navigate', { url: `http://127.0.0.1:${port}/index.html?model=${model}&hair=1${extra ? '&' + extra : ''}` });
  let ready = false;
  for (let i = 0; i < 80 && !ready; i++) { await sleep(500); ready = await ev('window.__ready === true').catch(() => false); }
  say(ready, '読み込みが終わる');
  if (!ready) throw new Error('読み込みが終わりません: ' + errors.join(' / '));
  // フレームが進んでいるか（固まっていないか）
  const frames = await ev('new Promise((r) => { let n = 0; const f = () => { n++; requestAnimationFrame(f); }; requestAnimationFrame(f); setTimeout(() => r(n), 1500); })');
  say(frames > 10, `全部閉じた状態で、画面が動き続ける（1.5 秒で ${frames} フレーム）`);
  await shot('1_closed');
  const secs = await ev('[...document.querySelectorAll(".sec")].map((d) => d.dataset.sec + ":" + d.classList.contains("open") + ":" + d.querySelector(".sechead").textContent)');
  say(secs.length >= 5 && secs.every((s) => s.split(':')[1] === 'false'), `折りたたみの項目が ${secs.length} 個あり、最初は全部閉じている（${secs.map((s) => s.split(':')[2]).join('、')}）`);
  // 項目を開く・閉じる
  let c = await center('document.querySelector(\'.sec[data-sec="vowels"] .sechead\')');
  if (c) { await click(c[0], c[1]); await sleep(300); }
  say(await ev('document.querySelector(\'.sec[data-sec="vowels"]\')?.classList.contains("open") === true'), '「母音の口の形」を押すと開く');
  await shot('2_vowels_open');
  // 母音を選んで、開きのスライダーを最大にすると、口の形が変わる（キーの形の口のモデルでは、前はスライダーが口に効いていなかった）。
  // 前後の画面を ui_2b・ui_2c に書く。最後に「初期値に戻す」を押し、母音の選択も外す（保存した値を残さない）
  const vbtn = (t) => `[...document.querySelectorAll('.sec[data-sec="vowels"] button')].find((b) => b.textContent === ${JSON.stringify(t)})`;
  c = await center(vbtn('あ'));
  if (c) {
    // 人の操作のとおりに: 押してから少し待ち（口の重みが落ち着いてから）、つまみをマウスで右の端までドラッグする
    await click(c[0], c[1]); await sleep(2000); await shot('2b_vowel_a');
    const thumb = await ev(`(() => { const g = [...document.querySelectorAll('.sec[data-sec="vowels"] label.sl')].find((l) => l.offsetParent && /開き/.test(l.textContent)); if (!g) return null;
      const i = g.querySelector('input'); i.scrollIntoView({ block: 'center' }); const r = i.getBoundingClientRect(); const t = (i.value - i.min) / (i.max - i.min);
      return [r.x + 6 + t * (r.width - 12), r.y + r.height / 2, r.x + r.width + 20]; })()`);
    let set = null;
    if (thumb) {
      await mouse('mousePressed', thumb[0], thumb[1]);
      for (let k = 1; k <= 8; k++) { await mouse('mouseMoved', thumb[0] + (thumb[2] - thumb[0]) * k / 8, thumb[1]); await sleep(40); }
      await mouse('mouseReleased', thumb[2], thumb[1]);
      set = await ev(`[...document.querySelectorAll('.sec[data-sec="vowels"] label.sl')].find((l) => l.offsetParent && /開き/.test(l.textContent)).querySelector('input').value`);
      set = '開き（倍率） = ' + set;
    }
    await sleep(1500); await shot('2c_vowel_a_open_max');
    say(!!set, `「あ」を押すと、その形のスライダーが出て、開きを動かせる（${set}。前後の画面: ui_2b・ui_2c）`);
    c = await center(vbtn('「あ」を初期値に戻す')); if (c) { await click(c[0], c[1]); await sleep(200); }
    c = await center(vbtn('あ')); if (c) { await click(c[0], c[1]); await sleep(200); }
  }
  c = await center('document.querySelector(\'.sec[data-sec="vowels"] .sechead\')');
  if (c) { await click(c[0], c[1]); await sleep(300); }
  say(await ev('document.querySelector(\'.sec[data-sec="vowels"]\')?.classList.contains("open") === false'), 'もう一度押すと閉じる');
  // 話しているデモ
  await ev('document.querySelector("#ui").scrollTop = 0');
  c = await center('[...document.querySelectorAll("#demos button")].find((b) => b.textContent.includes("話している"))');
  say(!!c, '「話しているデモ」のボタンが、上の「口のデモ」にある');
  if (c) {
    await click(c[0], c[1]); await sleep(900); await shot('3_talk_a'); await sleep(350); await shot('3_talk_b');
    say(await ev('[...document.querySelectorAll("#demos button")].find((b) => b.textContent.includes("話している")).classList.contains("on")'), '押すと、デモが動いている表示になる');
    c = await center('[...document.querySelectorAll("#demos button")].find((b) => b.textContent.includes("話している"))');
    await click(c[0], c[1]); await sleep(200);
  }
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
  // ---- 画面のボタン・選択肢を、順に全部押す（Web カメラは、あとで別に確かめる。マイクは押さない）
  const btns = async (sel) => ev(`[...document.querySelectorAll(${JSON.stringify(sel)})].map((b) => b.textContent)`);
  const press = async (sel, i) => { const p = await center(`document.querySelectorAll(${JSON.stringify(sel)})[${i}]`); if (p) { await click(p[0], p[1]); await sleep(250); } return !!p; };
  const exprs = await btns('#exprs button');
  let pressed = 0;
  for (let i = 0; i < exprs.length; i++) if (await press('#exprs button', i)) pressed++;
  await sleep(600); await shot('7_last_expr');
  say(pressed === exprs.length && exprs.length > 0, `表情のボタンを全部押せる（${pressed} / ${exprs.length} 個: ${exprs.join('・')}）`);
  await press('#exprs button', 0);
  const demos = await btns('#demos button');
  pressed = 0;
  for (let i = 0; i < demos.length; i++) { if (await press('#demos button', i)) pressed++; await sleep(500); if (await press('#demos button', i)) await sleep(150); }
  say(pressed === demos.length, `口のデモのボタンを全部押せる（${demos.join('・') || 'なし'}）`);
  const modes = await btns('#modes button');
  const order = ['demo', 'manual', 'mouse'];
  for (const m of order) {
    const i = await ev(`[...document.querySelectorAll('#modes button')].findIndex((b) => b.dataset.mode === ${JSON.stringify(m)})`);
    if (i >= 0) { await press('#modes button', i); await sleep(1200); }
  }
  await shot('8_modes');
  say(await ev(`document.querySelector('#modes button[data-mode="mouse"]').classList.contains('on')`), `動かし方を切り替えられる（${modes.join('・')}。Web カメラは、あとで確かめる）`);
  // 背景を全部選ぶ・髪の表示を切り替える
  const bgs = await ev(`[...document.querySelectorAll('#bg option')].map((o) => o.value)`);
  for (const v of bgs) await ev(`(() => { const s = document.querySelector('#bg'); s.value = ${JSON.stringify(v)}; s.dispatchEvent(new Event('change')); })()`);
  await ev(`(() => { const s = document.querySelector('#bg'); s.value = 'room'; s.dispatchEvent(new Event('change')); })()`);
  say(await ev(`document.body.classList.contains('bg-room')`), `背景を全部選べる（${bgs.join('・')}）`);
  c = await center('document.querySelector("#hair")');
  if (c) { await click(c[0], c[1]); await sleep(500); await shot('9_hair_toggled'); await click(c[0], c[1]); await sleep(300); }
  say(!!c, '「髪を表示」を切り替えられる');
  // 折りたたみの項目を全部開いて、中のスライダーを動かす（値は、あとで「初期値に戻す」の代わりに、保存を消して戻す）
  const nsec = await ev('document.querySelectorAll(".sec").length');
  let sliders = 0;
  for (let i = 0; i < nsec; i++) {
    const p = await center(`document.querySelectorAll('.sec .sechead')[${i}]`); if (!p) continue;
    await click(p[0], p[1]); await sleep(200);
    sliders += await ev(`(() => { let n = 0; for (const inp of document.querySelectorAll('.sec')[${i}].querySelectorAll('input[type=range]')) { if (!inp.offsetParent) continue;
      const v0 = inp.value; inp.value = (+inp.min + +inp.max) / 2; inp.dispatchEvent(new Event('input', { bubbles: true })); inp.value = v0; inp.dispatchEvent(new Event('input', { bubbles: true })); n++; } return n; })()`);
  }
  await sleep(500); await shot('10_all_open');
  const fr2 = await ev('new Promise((r) => { let n = 0; const f = () => { n++; requestAnimationFrame(f); }; requestAnimationFrame(f); setTimeout(() => r(n), 1000); })');
  say(fr2 > 10, `折りたたみの項目を全部開き、スライダー ${sliders} 本を動かしても、画面が動き続ける（1 秒で ${fr2} フレーム）`);
  await ev('localStorage.clear()');   // 確かめるために変えた保存値を残さない
  say(errors.length === 0, 'スクリプトのエラーが出ていない' + (errors.length ? ': ' + errors.slice(0, 3).join(' / ') : ''));
  say(logs.length === 0, 'コンソールの警告・エラー、読み込みの失敗が無い' + (logs.length ? ': ' + logs.slice(0, 5).join(' / ') : ''));
  // ---- Web カメラ（偽のカメラ）。同梱の MediaPipe が、起動の記録をコンソールへ出すので、コンソールの確認のあとで行う
  const camWait = async () => { let st = ''; for (let i = 0; i < 80; i++) { await sleep(500); st = await ev('document.querySelector("#status")?.textContent || ""').catch(() => ''); if (/追従中|できませんでした/.test(st)) break; } return st; };
  const camMode = () => ev(`document.querySelector('#modes button.on')?.dataset.mode || ''`);
  const nErr = errors.length;
  await ev('document.querySelector("#ui").scrollTop = 0');
  c = await center(`document.querySelector('#modes button[data-mode="camera"]')`);
  if (c) await click(c[0], c[1]);
  let st = await camWait();
  say(/追従中/.test(st) && await camMode() === 'camera', `「Webカメラ」を押すと、追従が始まる（テスト用の偽のカメラ。表示「${st}」・選ばれている動かし方 ${await camMode()}）`);
  await sleep(1200); await shot('11_camera');
  // URL の mode=camera でも同じか（前は、表示だけ「追従中」になり、動かし方はマウスへ戻っていた）
  await cdp('Page.navigate', { url: `http://127.0.0.1:${port}/index.html?model=${model}&hair=1&mode=camera${extra ? '&' + extra : ''}` });
  st = await camWait();
  say(/追従中/.test(st) && await camMode() === 'camera', `URL の mode=camera でも、追従が始まる（表示「${st}」・選ばれている動かし方 ${await camMode()}）`);
  say(errors.length === nErr, 'Web カメラで、スクリプトのエラーが出ていない' + (errors.length > nErr ? ': ' + errors.slice(nErr, nErr + 3).join(' / ') : ''));
  const ext = reqs.filter((u) => !/^http:\/\/127\.0\.0\.1:/.test(u) && !/^(data|blob|about):/.test(u));
  say(ext.length === 0, `外への通信が無い（読み込み ${reqs.length} 件。Web カメラの部品は、同梱の vendor/mediapipe だけ）` + (ext.length ? ': ' + ext.slice(0, 3).join(' ') : ''));
  await ev('localStorage.clear()');
} catch (e) { say(false, e.message); }
console.log(bad ? `NG ${bad} 件。画面: ${outDir}` : `全部 ok。画面: ${outDir}`);
await finish(bad ? 1 : 0);
