// 実際の GPU で動かしたときの、1 コマごとの時間を測る（カクつきの確認）。
//
//   node partsgen/tools/perfcheck.mjs <モデル名> [モデル名...] [--sec 6] [--query "URL に足す指定"] [--size 1300x1000] [--uncap]
//
// ヘッドレス Chrome を GPU つきで起動し、ふつうの画面（マウス追従・自動まばたき）を数秒動かして、
// コマの間隔の平均・95% 点・最大と、間隔が 25ms を超えたコマの数（60fps で 1 コマ落ち）を出す。
// 「JS」は、1 コマの計算と描画の指示にかかった時間（頂点の変形・WebGL の呼び出し。GPU が絵を描き終える時間は入らない）。
// --uncap: 画面の更新の上限（60Hz）を外して、描けるだけ描かせる。このときのコマの間隔が、1 コマに実際かかる時間（計算 + GPU）。
//          16.7ms より十分小さければ、60fps に余裕がある。--size で、画面の大きさを変えて測る（大きい画面ほど、GPU の仕事が増える）。
// 撮影（regress.py）は、姿勢を止めて 1 枚ずつ撮るので、速さの確認には使えない。
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { closeChrome, CHROME, profDir, CHROME_FLAGS } from './chromeclose.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const argv = process.argv.slice(2);
const optS = (k, d) => { const i = argv.indexOf('--' + k); if (i < 0) return d; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const SEC = +optS('sec', 6), QUERY = optS('query', ''), SIZE = String(optS('size', '1300x1000')).replace('x', ',');
const ui = argv.indexOf('--uncap'); const UNCAP = ui >= 0; if (UNCAP) argv.splice(ui, 1);
const models = argv;
if (!CHROME || !models.length) { console.log('使い方: node perfcheck.mjs <モデル名>...（Chrome / Edge が要る。環境変数 AVATAR_CHROME で指定できる）'); process.exit(1); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png' };
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
const prof = profDir('perf');   // 使い回すプロファイル（chromeclose.mjs に経緯）
const chrome = spawn(CHROME, ['--headless=new', ...CHROME_FLAGS, '--hide-scrollbars', '--window-size=' + SIZE, '--enable-gpu', '--ignore-gpu-blocklist',
  ...(UNCAP ? ['--disable-gpu-vsync', '--disable-frame-rate-limit'] : []),
  '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--remote-debugging-port=0', '--user-data-dir=' + prof, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
const wsUrl = await new Promise((resolve, reject) => {
  let buf = ''; const t = setTimeout(() => reject(new Error('Chrome が起動しません')), 30000);
  chrome.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]); } });
});
const tabs = await (await fetch(wsUrl.replace('ws://', 'http://').replace(/\/devtools\/.*/, '') + '/json')).json();
const ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
let seq = 0; const wait = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && wait.has(m.id)) { wait.get(m.id)(m); wait.delete(m.id); } };
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq; const t = setTimeout(() => { wait.delete(id); reject(new Error('応答なし: ' + method)); }, 60000);
  wait.set(id, (m) => { clearTimeout(t); m.error ? reject(new Error(m.error.message)) : resolve(m.result); });
  ws.send(JSON.stringify({ id, method, params }));
});
const ev = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
await cdp('Runtime.enable'); await cdp('Page.enable');
// エンジンの 1 コマ（requestAnimationFrame で呼ばれる関数）にかかった時間を記録する。計測用のループは、もとの関数（__raf0）を使う
await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `(() => { const raf = window.requestAnimationFrame.bind(window); window.__raf0 = raf; window.__js = [];
  window.requestAnimationFrame = (cb) => raf((t) => { const a = performance.now(); cb(t); window.__js.push(performance.now() - a); }); })();` });
const [SW, SH] = SIZE.split(',').map(Number);
await cdp('Emulation.setDeviceMetricsOverride', { width: SW, height: SH, deviceScaleFactor: 1, mobile: false });
for (const model of models) {
  await cdp('Page.navigate', { url: `http://127.0.0.1:${port}/index.html?model=${model}&hair=1${QUERY ? '&' + QUERY : ''}` });
  let ready = false;
  for (let i = 0; i < 120 && !ready; i++) { await sleep(250); ready = await ev('window.__ready === true').catch(() => false); }
  if (!ready) { console.log(model + ': 読み込みが終わりません'); continue; }
  await sleep(1500);
  const r = await ev(`new Promise((res) => {
    const d = []; let last = performance.now(); const t0 = last;
    const gl = document.querySelector('canvas').getContext('webgl2');
    const dbg = gl && gl.getExtension('WEBGL_debug_renderer_info');
    const cv = document.querySelector('canvas'); window.__js.length = 0;
    const f = (t) => { d.push(t - last); last = t; if (t - t0 < ${SEC * 1000}) window.__raf0(f); else {
      d.sort((a, b) => a - b); const n = d.length;
      const js = window.__js.slice().sort((a, b) => a - b), m = js.length;
      res({ n, avg: d.reduce((a, b) => a + b, 0) / n, p50: d[n >> 1], p95: d[Math.floor(n * 0.95)], max: d[n - 1], slow: d.filter((x) => x > 25).length,
            js50: m ? js[m >> 1] : 0, js95: m ? js[Math.floor(m * 0.95)] : 0, jsMax: m ? js[m - 1] : 0, w: cv.width, h: cv.height,
            gpu: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : '?' }); } };
    window.__raf0(f); })`);
  console.log(`${model.padEnd(16)} ${r.w}x${r.h}${UNCAP ? ' 上限なし' : ''}  ${SEC} 秒で ${r.n} コマ  間隔 平均 ${r.avg.toFixed(1)}ms  中央 ${r.p50.toFixed(1)}ms  95% ${r.p95.toFixed(1)}ms  最大 ${r.max.toFixed(1)}ms  25ms 超 ${r.slow} コマ  JS 中央 ${r.js50.toFixed(1)}ms  95% ${r.js95.toFixed(1)}ms  最大 ${r.jsMax.toFixed(1)}ms  [${r.gpu}]`);
}
try { ws.close(); } catch (e) { /* 閉じられなくてもよい */ }
server.close();
// Chrome に自分で終了させ、残っていれば子プロセスごと落とす（プロファイルは使い回すので、消さない。chromeclose.mjs に経緯）
await closeChrome(chrome, wsUrl);
process.exit(0);
