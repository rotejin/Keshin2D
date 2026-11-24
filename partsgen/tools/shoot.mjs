// 決まった姿勢をまとめて撮る（regress.py shoot から呼ばれる）。
//
//   node partsgen/tools/shoot.mjs <姿勢の一覧.json> <出力フォルダ> [--size 1100] [--jobs 2] [--timeout 60]
//
// PC を重くしない撮り方: 描画は GPU、優先度は「通常以下」、Chrome は 2 つ。同じ 9 枚が、前（ソフトウェア描画・4 つ）の
// 37.6 秒・PC 全体の CPU 96% から、6 秒・38% になった。最後の行に、その間の CPU の使用率が出る。前の描画に戻すのは、環境変数 AVATAR_SHOOT_SW=1（chromeclose.mjs）。
//
// 姿勢の一覧は [{"name": "h1_front", "url": "index.html?model=...&..."}, ...]。
// 以前は 1 枚ごとに Chrome を起動し直していた（1 枚 12〜14 秒）。ここでは Chrome を --jobs 個だけ起動したままにし、
// それぞれが自分の分の姿勢を順に開いて撮る（1 枚 1〜2 秒）。ページの読み込み完了は window.__ready で待つ。
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { closeChrome, CHROME, profDir, CHROME_FLAGS, RENDER_FLAGS, SOFT, lowPriority, cpuMeter } from './chromeclose.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const argv = process.argv.slice(2);
const opt = (k, d) => { const i = argv.indexOf('--' + k); return i >= 0 ? +argv[i + 1] : d; };
const [listFile, outDir] = argv;
const SIZE = opt('size', 1100), JOBS = Math.max(1, opt('jobs', 2)), TIMEOUT = opt('timeout', 60) * 1000;
if (!CHROME) { console.log('Chrome / Edge が見つかりません（環境変数 AVATAR_CHROME で、実行ファイルを指定できます）'); process.exit(1); }
const poses = JSON.parse(await readFile(listFile, 'utf8'));
await mkdir(outDir, { recursive: true });
const NICE = lowPriority();   // PC を重くしない: 優先度を下げてから Chrome を起動する（子へ引き継がれる）。描画は GPU（chromeclose.mjs に経緯）
const cpuUsed = cpuMeter();
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

// ---- Chrome を 1 つ起動して、操作用の接続（CDP）をつなぐ
async function launch(slot) {
  const prof = profDir('shoot' + slot);   // 使い回すプロファイル（作っては消さない。シークレットモードなので、前の実行の状態は残らない。chromeclose.mjs に経緯）
  const chrome = spawn(CHROME, ['--headless=new', ...CHROME_FLAGS, ...RENDER_FLAGS, '--hide-scrollbars', `--window-size=${SIZE},${SIZE}`,
    '--disk-cache-size=1', '--remote-debugging-port=0', '--user-data-dir=' + prof, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = ''; const t = setTimeout(() => reject(new Error('Chrome が起動しません')), 30000);
    chrome.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]); } });
  });
  const base = wsUrl.replace('ws://', 'http://').replace(/\/devtools\/.*/, '');
  const tabs = await (await fetch(base + '/json')).json();
  const ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => { ws.onopen = r; });
  let seq = 0; const wait = new Map(); const b = { errors: [] };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && wait.has(m.id)) { wait.get(m.id)(m); wait.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') b.errors.push('Uncaught ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).split('\n')[0]);
    if (m.method === 'Network.responseReceived' && m.params.response.status >= 400 && !m.params.response.url.endsWith('/favicon.ico')) b.errors.push(m.params.response.status + ' ' + m.params.response.url);
  };
  b.cdp = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq; const t = setTimeout(() => { wait.delete(id); reject(new Error('応答なし: ' + method)); }, TIMEOUT);
    wait.set(id, (m) => { clearTimeout(t); m.error ? reject(new Error(m.error.message)) : resolve(m.result); });
    ws.send(JSON.stringify({ id, method, params }));
  });
  b.ev = async (expr) => (await b.cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
  b.close = async () => {
    try { ws.close(); } catch (e) { /* 閉じられなくてもよい */ }
    // Chrome に自分で終了させ、残っていれば子プロセスごと落とす（プロファイルは使い回すので、消さない。chromeclose.mjs に経緯）
    await closeChrome(chrome, wsUrl);
  };
  await b.cdp('Runtime.enable'); await b.cdp('Page.enable'); await b.cdp('Network.enable');
  await b.cdp('Emulation.setDeviceMetricsOverride', { width: SIZE, height: SIZE, deviceScaleFactor: 1, mobile: false });
  return b;
}

async function shootOne(b, p) {
  b.errors.length = 0;
  await b.cdp('Page.navigate', { url: `http://127.0.0.1:${port}/${p.url}` });
  const t0 = Date.now(); let ready = false;
  while (!ready && Date.now() - t0 < TIMEOUT) { await sleep(60); ready = await b.ev('window.__ready === true').catch(() => false); }
  if (!ready) throw new Error(b.errors[0] || 'timeout');
  // sim= の早送りは最初のフレームで行われ、その次のフレームから止めた絵を描き続ける。3 フレーム待ってから撮る
  await b.ev('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(() => r(1)))))');
  if (b.errors.length) throw new Error(b.errors[0]);
  const r = await b.cdp('Page.captureScreenshot', { format: 'png' });
  await writeFile(path.join(outDir, p.name + '.png'), Buffer.from(r.data, 'base64'));
}

const queue = poses.slice(); const bad = []; const tAll = Date.now();
async function worker(_, slot) {
  let b = await launch(slot);
  for (let p; (p = queue.shift());) {
    let ok = false, msg = '';
    for (let k = 0; k < 3 && !ok; k++) {
      try { await shootOne(b, p); ok = true; } catch (e) {
        msg = e.message.slice(0, 160);
        await b.close().catch(() => {}); b = await launch(slot);   // 固まったら、その Chrome を捨てて起動し直す
      }
    }
    console.log((ok ? 'ok   ' : 'FAIL ') + p.name + (ok ? '' : '  ' + msg));
    if (!ok) bad.push(p.name);
  }
  await b.close();
}
await Promise.all(Array.from({ length: Math.min(JOBS, poses.length) }, worker));
server.close();
console.log(`done: ${outDir}  ${poses.length} 枚 ${((Date.now() - tAll) / 1000).toFixed(1)} 秒  failed=${bad.length} ${bad.join(',')}  [${SOFT ? 'ソフトウェア描画' : 'GPU'}・Chrome ${Math.min(JOBS, poses.length)} つ・優先度 ${NICE ? '低' : '通常'}・その間の PC 全体の CPU ${cpuUsed()}%]`);
process.exit(bad.length ? 1 : 0);
