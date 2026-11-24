// 実際の時間で動かしながら、画面を録る（動きの確認用）。
//   node partsgen/tools/ref/livecap.mjs <モデル名> <出力フォルダ> <台本の名前 か 台本.json> [--q "URL に足す指定"] [--size 900] [--fps 30]
//
// regress.py・seqshoot.py は、?sim=秒 で「その時刻まで一気に進めた 1 枚」を撮る。向きや髪のばねは、それで正しく写るが、
// 最後の 1 枚を描くときの経過時間が 0 なので、**口のキーの重みなど「描くときに追いかける値」は、行き先へ一気に飛んだ絵になる**
// （表情を切り替えた直後のコマで、口だけが、もう開ききっている）。切り替わりの途中・マウスへの追従・口パクの「本当の動き」は、
// ここで、ページをふつうに動かしたまま、決まった間隔で画面を撮って確かめる。
//
// 台本: [[秒, 種類, 値…], …]  秒は、録りはじめからの時刻。
//   ["move", x, y]            マウスを、そこへ一気に動かす（x・y は −1〜1。画面のまん中が 0。右と下が +）
//   ["glide", x, y, 秒]       今の位置から、そこへ、その秒数でなめらかに動かす
//   ["key", "3"]              キーを押す（数字キー = 上に並んだ表情）
//   ["eval", "式"]            ページの中で式を実行する
//   ["end"]                   録り終わり
// 名前で選べる台本: mouse（左右・斜め・円）、expr（表情の切り替え）、talk（口パクデモ。--q "talkdemo=1" を付ける）、idle（待機）
//
// 出力: <出力フォルダ>/f00000.jpg …（撮った絵）と frames.json（コマごとの、録りはじめからの秒）
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { closeChrome, CHROME, profDir, CHROME_FLAGS, RENDER_FLAGS, lowPriority } from '../chromeclose.mjs';
lowPriority();

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); if (i < 0) return d; const v = args[i + 1]; args.splice(i, 2); return v; };
const extraQ = opt('--q', ''), SIZE = +opt('--size', 900), FPS = +opt('--fps', 30);
const [model = 'kurage02', outDir, scriptArg = 'mouse'] = args;
if (!outDir) { console.log('使い方: livecap.mjs <モデル名> <出力フォルダ> <台本>'); process.exit(1); }
if (!CHROME) { console.log('NG Chrome / Edge が見つかりません'); process.exit(1); }

const SCRIPTS = {
  // 止まった所から一気に（ばねの戻り）→ なめらかに左右 → 斜め → 円
  mouse: [[0.5, 'move', 0, 0], [1.2, 'move', -1, 0], [2.4, 'glide', 1, 0, 0.5], [3.6, 'move', 0, 0], [4.6, 'glide', 1, -1, 0.4], [5.6, 'glide', -1, 1, 0.6],
    [6.8, 'glide', 0, -1, 0.4], [7.6, 'glide', 0, 1, 0.5], [8.6, 'glide', 0, 0, 0.3], [9.4, 'circle', 1.6], [11.2, 'glide', 0, 0, 0.3], [12.2, 'end']],
  expr: [[0.5, 'move', 0, 0], [1.0, 'key', '3'], [2.0, 'key', '1'], [2.8, 'key', '6'], [3.6, 'key', '8'], [4.4, 'key', '5'], [5.2, 'key', '7'], [6.0, 'key', '4'], [6.8, 'key', '2'], [7.6, 'key', '1'], [8.6, 'end']],
  talk: [[0.2, 'move', 0, 0], [4.5, 'end']],
  idle: [[0.2, 'move', 0, 0], [6.0, 'end']],
};
const script = SCRIPTS[scriptArg] || JSON.parse(await readFile(scriptArg, 'utf8'));
await rm(outDir, { recursive: true, force: true }); await mkdir(outDir, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.wasm': 'application/wasm' };
const server = createServer(async (req, res) => {
  try {
    const p = path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
    if (!p.startsWith(ROOT)) throw new Error('outside');
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream', 'Cache-Control': 'no-store' }); res.end(await readFile(p));
  } catch (e) { res.writeHead(404); res.end(); }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

const chrome = spawn(CHROME, ['--headless=new', ...CHROME_FLAGS, ...RENDER_FLAGS, '--hide-scrollbars', `--window-size=${SIZE},${SIZE}`,
  '--remote-debugging-port=0', '--user-data-dir=' + profDir('livecap'), 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
let ws = null, browserWs = '';
const finish = async (code) => { try { if (ws) ws.close(); } catch (e) { /* 閉じられなくてもよい */ } server.close(); await closeChrome(chrome, browserWs); process.exit(code); };
const wsUrl = browserWs = await new Promise((resolve, reject) => {
  let buf = ''; const t = setTimeout(() => reject(new Error('Chrome が起動しません')), 20000);
  chrome.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]); } });
}).catch((e) => { console.log('NG ' + e.message); return null; });
if (!wsUrl) await finish(1);
const base = wsUrl.replace('ws://', 'http://').replace(/\/devtools\/.*/, '');
const tabs = await (await fetch(base + '/json')).json();
ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
let seq = 0; const wait = new Map();
let onFrame = null;
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && wait.has(m.id)) { wait.get(m.id)(m); wait.delete(m.id); }
  if (m.method === 'Page.screencastFrame' && onFrame) onFrame(m.params);
};
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq; const t = setTimeout(() => { wait.delete(id); reject(new Error('応答なし: ' + method)); }, 20000);
  wait.set(id, (m) => { clearTimeout(t); m.error ? reject(new Error(m.error.message)) : resolve(m.result); });
  ws.send(JSON.stringify({ id, method, params }));
});
const ev = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.value;

try {
  await cdp('Page.enable'); await cdp('Runtime.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: SIZE, height: SIZE, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.navigate', { url: `http://127.0.0.1:${port}/index.html?model=${encodeURIComponent(model)}&ui=0${extraQ ? '&' + extraQ : ''}` });
  for (let i = 0; i < 300 && !(await ev('!!window.__ready')); i++) await sleep(100);
  await sleep(1200);   // 絵の読み込みと、最初のばねが落ち着くのを待つ
  const px = (v) => Math.round((v + 1) / 2 * (SIZE - 1));
  const mm = (x, y) => cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: px(x), y: px(y), buttons: 0 });
  let cur = [0, 0];
  await mm(0, 0);
  const times = [], writes = []; let n = 0, done = false;
  const t0 = performance.now(), w0 = Date.now() / 1000;
  // 画面の録り方: Chrome の画面配信（screencast）。ページが絵を描くたびに、その絵と、描いた時刻が届く（ページは、実際の時間で動いたまま）。
  // 1 枚ずつ撮る方法（captureScreenshot）は、1 秒に 8 コマほどしか撮れなかった
  let last = -1;
  onFrame = (p) => {
    ws.send(JSON.stringify({ id: ++seq, method: 'Page.screencastFrameAck', params: { sessionId: p.sessionId } }));
    if (done) return;
    const t = (p.metadata && p.metadata.timestamp ? p.metadata.timestamp : Date.now() / 1000) - w0;
    if (t - last < 1 / FPS - 0.004) return;                       // 決めたコマ数より細かくは、残さない
    last = t;
    writes.push(writeFile(path.join(outDir, 'f' + String(n).padStart(5, '0') + '.jpg'), Buffer.from(p.data, 'base64')));
    times.push(+t.toFixed(4)); n++;
  };
  await cdp('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: SIZE, maxHeight: SIZE, everyNthFrame: 1 });
  const key = async (k) => { const o = { key: k, text: k, code: /\d/.test(k) ? 'Digit' + k : 'Key' + k.toUpperCase(), windowsVirtualKeyCode: k.toUpperCase().charCodeAt(0) }; await cdp('Input.dispatchKeyEvent', Object.assign({ type: 'keyDown' }, o)); await cdp('Input.dispatchKeyEvent', Object.assign({ type: 'keyUp' }, o)); };
  const log = [];
  for (const [at, kind, ...v] of script) {
    const w = t0 + at * 1000 - performance.now();
    if (w > 0) await sleep(w);
    log.push([+((performance.now() - t0) / 1000).toFixed(3), kind, ...v]);
    if (kind === 'end') break;
    if (kind === 'move') { cur = [v[0], v[1]]; await mm(...cur); }
    if (kind === 'key') await key(String(v[0]));
    if (kind === 'eval') await ev(v[0]);
    if (kind === 'glide' || kind === 'circle') {
      const dur = kind === 'glide' ? v[2] : v[0], a = cur.slice(), ts = performance.now();
      for (;;) {
        const u = Math.min(1, (performance.now() - ts) / (dur * 1000));
        if (kind === 'glide') { const e = u * u * (3 - 2 * u); cur = [a[0] + (v[0] - a[0]) * e, a[1] + (v[1] - a[1]) * e]; }
        else { const r = 0.9 * Math.min(1, u * 5, (1 - u) * 5 + 0.0001), ph = Math.PI * 2 * u * 1.5; cur = [r * Math.sin(ph), -r * Math.cos(ph) * 0.9]; }
        await mm(...cur);
        if (u >= 1) break;
        await sleep(12);
      }
    }
  }
  done = true; await cdp('Page.stopScreencast'); await Promise.all(writes);
  await writeFile(path.join(outDir, 'frames.json'), JSON.stringify({ model, script: scriptArg, size: SIZE, times, log }));
  const span = times[times.length - 1] - times[0];
  console.log(`done: ${outDir}  ${n} コマ  ${span.toFixed(1)} 秒（1 秒あたり ${(n / Math.max(span, 0.01)).toFixed(1)} コマ）`);
  await finish(0);
} catch (e) { console.log('NG ' + e.message); await finish(1); }
