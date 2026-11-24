// エンジンの計測（?probe=1）を、姿勢ごとに読む。今の姿勢で、頭の輪郭・あご先・瞳・鼻・口が、モデルの座標のどこへ行くか。
//
//   node partsgen/tools/ref/probe.mjs <モデル名> "<指定>" ["<指定>" …]      例: node …/probe.mjs kurage02 "yaw=0" "yaw=30" "yaw=30&mouthFit=0"
//
// 1 行に 1 姿勢ぶんの JSON を出す: { q, top, chin, e: {R, L}, nose, mouth, mouthL, mouthR, pts, R0, HX }
// 顔のパーツの位置関係（正面からのずれ ÷ 両目の間隔）を、姿勢ごとに数字で比べるためのもの（WORKFLOW.md の「横を向いたときの鼻と口」）。
// 奥の目と輪郭の関係は、この出力を partsgen/tools/ref/eyeedge.py に渡す。
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { closeChrome, CHROME, profDir, CHROME_FLAGS, RENDER_FLAGS, lowPriority } from '../chromeclose.mjs';
lowPriority();   // PC を重くしない: 優先度を下げてから Chrome を起動する（chromeclose.mjs に経緯）

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const [model, ...qs] = process.argv.slice(2);
if (!model || !qs.length) { console.error('使い方: probe.mjs <モデル名> "<指定>" …'); process.exit(1); }
if (!CHROME) { console.error('Chrome / Edge が見つかりません（環境変数 AVATAR_CHROME で、実行ファイルを指定できます）'); process.exit(1); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png' };
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
const prof = profDir('probe');   // 使い回すプロファイル（chromeclose.mjs に経緯）
const chrome = spawn(CHROME, ['--headless=new', ...CHROME_FLAGS, ...RENDER_FLAGS, '--hide-scrollbars', '--window-size=700,700',
  '--disk-cache-size=1', '--remote-debugging-port=0', '--user-data-dir=' + prof, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
let ws = null, code = 0, browserWs = '';
try {
  const wsUrl = browserWs = await new Promise((resolve, reject) => {
    let buf = ''; const t = setTimeout(() => reject(new Error('Chrome が起動しません')), 30000);
    chrome.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]); } });
  });
  const base = wsUrl.replace('ws://', 'http://').replace(/\/devtools\/.*/, '');
  const tabs = await (await fetch(base + '/json')).json();
  ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
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
  for (const q of qs) {
    await cdp('Page.navigate', { url: `http://127.0.0.1:${port}/index.html?model=${model}&ui=0&hair=0&sim=3&probe=1&${q}` });
    let title = ''; const t0 = Date.now();
    while (!title.startsWith('PROBE') && Date.now() - t0 < 60000) { await sleep(120); title = await ev('document.title').catch(() => ''); }
    if (!title.startsWith('PROBE')) { console.log(JSON.stringify({ q, error: 'timeout' })); code = 1; continue; }
    console.log(JSON.stringify({ q, ...JSON.parse(title.slice(5)) }));
  }
} catch (e) { console.error(String(e)); code = 1; }
try { if (ws) ws.close(); } catch (e) { /* 閉じられなくてもよい */ }
server.close();
// Chrome に自分で終了させ、残っていれば子プロセスごと落とす（プロファイルは使い回すので、消さない。chromeclose.mjs に経緯）
await closeChrome(chrome, browserWs);
process.exit(code);
