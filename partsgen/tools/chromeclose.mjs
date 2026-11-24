// 撮影用に起動するヘッドレスの Chrome の、プロファイルの場所と、終了のさせ方（shoot.mjs・uicheck.mjs・perfcheck.mjs・ref/probe.mjs が使う）。
//
//   const prof = profDir('shoot0')                 使い回すプロファイルのフォルダ（%LOCALAPPDATA%\keshin2d_work\_chrome_prof\shoot0。
//                                                  環境変数 KESHIN2D_WORK があれば、その中の _chrome_prof\shoot0）
//   spawn(CHROME, [...CHROME_FLAGS, '--user-data-dir=' + prof, …])
//   await closeChrome(chrome, wsUrl)               chrome: spawn した子プロセス、wsUrl: 起動時に出る「DevTools listening on ws://…」
//
// **プロファイルは、作っては消さない。決まった場所を使い回す。** シークレットモード（--incognito）で起動するので、前の実行のキャッシュや
// 保存値（localStorage）は、次の実行に持ち越されない（前は「古いエンジンを覚えさせない」ために、毎回新しいフォルダを %TEMP% に作って、終わりに消していた）。
// 経緯:
//   - %TEMP% に、撮影用のプロファイル（shoot_*・shotprof_*）が、消されずにたまっていた（3 日で約 25GB）。
//   - 原因は、作った PC のセキュリティソフト。ブラウザーの保存データ（Login Data・Web Data・History など）を、ブラウザー以外のアプリが
//     読む・消すのを拒否する。Chrome を 1〜2 分動かすと、そのプロファイルが保護の対象になり、道具（node）からもシェルからも「アクセスが拒否されました」で消せない
//     （短い実行のプロファイルは消せるので、気づきにくい）。どの処理も、ファイルを開いてはいない。権限（ACL）も、ふつうの継承のまま。
//   - 途中で「消えるまで繰り返す」作りにしたら、fs.rm の再試行（maxRetries）がファイル 1 個ごとに効いて、道具が終わらずに CPU を使い続けた（10 分以上）。
//   - 保護を回避するのではなく、消す必要のない作りにした。**一時プロファイルを作って消す方式に戻さない。**
// Chrome は、まず自分で終了させる（Browser.close）。残っていれば、子プロセスごと強制終了する（残ると CPU を使い続ける）。どの待ちにも上限時間がある。
import { spawn } from 'node:child_process';
import { mkdirSync, existsSync } from 'node:fs';
import os, { tmpdir } from 'node:os';
import path from 'node:path';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 撮影に使うブラウザ（Chrome 系）の実行ファイル。環境変数 AVATAR_CHROME で指定できる（Edge・Chromium なども可）。
// 指定が無ければ、Chrome → Edge → Chromium の順に、よくある場所を探す。見つからなければ null
export function findChrome() {
  if (process.env.AVATAR_CHROME) return existsSync(process.env.AVATAR_CHROME) ? process.env.AVATAR_CHROME : null;
  const pf = [process.env.ProgramFiles, process.env['ProgramFiles(x86)'], process.env.LOCALAPPDATA].filter(Boolean);
  const cands = process.platform === 'win32'
    ? [...pf.map((b) => path.join(b, 'Google', 'Chrome', 'Application', 'chrome.exe')), ...pf.map((b) => path.join(b, 'Microsoft', 'Edge', 'Application', 'msedge.exe'))]
    : process.platform === 'darwin'
      ? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge', '/Applications/Chromium.app/Contents/MacOS/Chromium']
      : ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge', '/snap/bin/chromium'];
  return cands.find((p) => existsSync(p)) || null;
}
export const CHROME = findChrome();

// ---- PC を重くしない撮り方（撮る絵の質は落とさずに、撮影の間も PC を普通に使えるように）
// 1. 描画は GPU で（既定）。前は、ソフトウェア描画（SwiftShader）で、Chrome 1 つが CPU を何スレッドも使い切っていた（4 つ並べると、全部の CPU が埋まる）。
//    環境変数 AVATAR_SHOOT_SW=1 で、前のソフトウェア描画に戻る（GPU の無い PC、または、前にソフトウェア描画で撮った絵と画素で比べるとき）。
//    **GPU とソフトウェア描画の絵は、ふちの画素がわずかに違う。画素で比べる 2 組は、同じ方式で撮る。**
// 2. 道具（node）と Chrome の優先度を「通常以下」に下げる（lowPriority）。PC を使っている人の操作が、いつも先に処理される。
//    Windows では、この優先度は、あとから起動する子プロセス（Chrome と、その子）へ引き継がれる。AVATAR_SHOOT_NICE=0 で、下げない。
// 3. 撮影の終わりに、その間の PC 全体の CPU の使用率を出す（cpuMeter）。重さを、数字で見張る。
export const SOFT = process.env.AVATAR_SHOOT_SW === '1';
export const RENDER_FLAGS = SOFT ? ['--disable-gpu', '--enable-unsafe-swiftshader'] : ['--enable-gpu', '--ignore-gpu-blocklist'];
export function lowPriority() {
  if (process.env.AVATAR_SHOOT_NICE === '0') return false;
  try { os.setPriority(os.constants.priority.PRIORITY_BELOW_NORMAL); return true; } catch (e) { return false; }
}
// 引き継がれた優先度のうち、Chrome は、2 つだけ自分で付け直す（表のタブの処理 = 通常、GPU の処理 = 通常以上）。ほかの子プロセスは、低いまま。
// この 2 つを、あとから道具（node）で下げることは、この PC では出来なかった（os.setPriority が ERR_SYSTEM_ERROR で拒否される。原因は調べていない。深追いしない）。
// だから、同時に動かす Chrome を 2 つまでにして、「通常」の優先度で動く処理を 2 つに抑える（shoot.mjs の --jobs の既定）。
export function cpuMeter() {
  const snap = () => { let idle = 0, tot = 0; for (const c of os.cpus()) { for (const k in c.times) tot += c.times[k]; idle += c.times.idle; } return [idle, tot]; };
  const a = snap();
  return () => { const b = snap(); const dt = b[1] - a[1]; return dt > 0 ? Math.round(100 * (1 - (b[0] - a[0]) / dt)) : 0; };
}

// 起動時に足す指定。シークレットモード + 裏での通信・更新・同期をしない（プロファイルに余計な物を書かせない。CPU も使わせない）
export const CHROME_FLAGS = ['--incognito', '--no-first-run', '--no-default-browser-check', '--disable-component-update', '--disable-background-networking', '--disable-sync', '--disable-extensions'];

// 使い回すプロファイルのフォルダ。同じ名前を、同時に 2 つの Chrome で使わない（撮影は同時に走らせない）
export function profDir(name) {
  const d = path.join(process.env.KESHIN2D_WORK || path.join(process.env.LOCALAPPDATA || tmpdir(), 'keshin2d_work'), '_chrome_prof', name);
  mkdirSync(d, { recursive: true });
  return d;
}

export async function closeChrome(chrome, wsUrl) {
  const gone = new Promise((r) => { if (chrome.exitCode !== null || chrome.signalCode !== null) r(); else chrome.once('exit', r); });
  // 1. 自分で終了させる
  try {
    await Promise.race([new Promise((resolve) => {
      const w = new WebSocket(wsUrl);
      w.onopen = () => { try { w.send(JSON.stringify({ id: 1, method: 'Browser.close' })); } catch (e) { resolve(); } };
      w.onmessage = () => resolve(); w.onerror = () => resolve(); w.onclose = () => resolve();
    }), sleep(3000)]);
  } catch (e) { /* つながらなければ、強制終了へ */ }
  await Promise.race([gone, sleep(5000)]);
  // 2. 残っていれば、子プロセスごと落とす
  if (process.platform === 'win32') {
    await Promise.race([new Promise((r) => { const k = spawn('taskkill', ['/F', '/T', '/PID', String(chrome.pid)], { stdio: 'ignore' }); k.once('exit', r); k.once('error', r); }), sleep(8000)]);
  } else if (chrome.exitCode === null && chrome.signalCode === null) {
    try { chrome.kill('SIGKILL'); } catch (e) { /* もう終わっている */ }
  }
  await Promise.race([gone, sleep(3000)]);
}
