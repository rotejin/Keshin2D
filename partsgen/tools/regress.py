# -*- coding: utf-8 -*-
"""決まった姿勢を一括で撮り、前回と画素で比べる（回帰テスト）。

  regress.py shoot <モデル名> <出力フォルダ> [--only 接頭辞,接頭辞] [--size 1100] [--jobs 2] [--legacy]
      Keshin2D を自前のサーバーで配り、ヘッドレス Chrome で撮る（shoot.mjs。Chrome を起動したまま姿勢だけ切り替える。64 姿勢で約 30 秒）。
      --legacy で、以前の撮り方（1 枚ごとに Chrome を起動し直す。64 姿勢で 14〜45 分）。
      姿勢はすべて URL で固定するので、同じエンジン・同じモデルなら同じ絵になる。
  regress.py compare <フォルダA> <フォルダB> [--out 比較画像のフォルダ] [--tol 2]
      同じ名前の絵を画素で比べる。違う絵は「A | B | 差」を並べた画像を書く。
  regress.py sheet <フォルダ> <出力.png> [--only 接頭辞] [--cols 4] [--cell 800]
      撮った絵を 1 枚に並べる（目で見る用。1 コマ 800px 以上を保つ）

出力フォルダは英数字のパスにする。
"""
import sys, os, json, glob, shutil, subprocess, tempfile, threading, argparse, functools, socket, time, urllib.parse
import http.server
import numpy as np
sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))   # Keshin2D
def _chromes():
    """撮影に使うブラウザ（Chrome 系）の候補。環境変数 AVATAR_CHROME で指定できる（chromeclose.mjs の findChrome と同じ順）"""
    if os.environ.get("AVATAR_CHROME"):
        return [os.environ["AVATAR_CHROME"]]
    if sys.platform == "win32":
        bases = [b for b in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")) if b]
        return [os.path.join(b, "Google", "Chrome", "Application", "chrome.exe") for b in bases] + [os.path.join(b, "Microsoft", "Edge", "Application", "msedge.exe") for b in bases]
    if sys.platform == "darwin":
        return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    return [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge")]


CHROME = _chromes()

EYE = "zoom=4&cx=1320&cy=745"      # 画面左の目（モデルは顔を同じ座標に合わせてある）
MOUTH = "zoom=4&cx=1500&cy=1000"
FACE = "zoom=1.9&cx=1500&cy=700"
EXPRS = ["通常", "にこ", "笑顔", "閉じ目", "怒り", "蔑む", "青ざめ", "照れ", "ハート", "キラキラ", "ぐるぐる", "闇", "ω", "てへ"]

def poses():
    P = []
    for h in (1, 0):
        t = "h%d_" % h
        for name, qs in [("front", "yaw=0"), ("yawP", "yaw=30"), ("yawM", "yaw=-30"), ("pitchP", "pitch=25"), ("pitchM", "pitch=-25"),
                         ("rollP", "roll=25"), ("rollM", "roll=-25"), ("diagA", "yaw=30&pitch=25"), ("diagB", "yaw=-30&pitch=-25"),
                         ("diagC", "yaw=30&pitch=-25&roll=25")]:
            P.append((t + name, "hair=%d&%s" % (h, qs)))
    for i, e in enumerate(EXPRS):
        P.append(("exp%02d" % i, "hair=1&%s&exp=%s" % (FACE, e)))
    for name, qs in [("c", "yaw=0"), ("gl", "gazeX=-1"), ("gr", "gazeX=1"), ("gu", "gazeY=1"), ("gd", "gazeY=-1"),
                     ("half", "eyeR=0.5&eyeL=0.5"), ("close", "eyeR=0&eyeL=0"), ("smile", "eyeSmile=1&eyeR=0&eyeL=0"),
                     ("yawP", "yaw=30&gazeX=1"), ("yawM", "yaw=-30&gazeX=-1")]:
        P.append(("eye_" + name, "hair=0&%s&%s" % (EYE, qs)))
    for name, qs in [("o0", "mouthOpen=0"), ("o3", "mouthOpen=0.3"), ("o6", "mouthOpen=0.6"), ("o10", "mouthOpen=1"),
                     ("up", "pitch=25&mouthOpen=0.3"), ("formM", "mouthForm=-1&mouthOpen=0.4"), ("formP", "mouthForm=1&mouthOpen=0.4")]:
        P.append(("mouth_" + name, "hair=0&%s&%s" % (MOUTH, qs)))
    # マウス追従で実際に出る組み合わせ（横向き + かしげ + 視線の上下、見開き）。目の粗は、ここで初めて見えた
    MIX = "zoom=3.4&cx=1500&cy=745"
    for name, qs in [("a", "yaw=-28&roll=7&gazeX=-0.8&gazeY=0.8"), ("b", "yaw=-28&roll=7&gazeX=-0.8&gazeY=-0.8"),
                     ("c", "yaw=28&roll=-7&gazeX=0.8&gazeY=0.8"), ("d", "yaw=-28&roll=7&gazeX=-0.8&gazeY=0.8&eyeR=1.15&eyeL=1.15"),
                     ("e", "yaw=28&pitch=-20&roll=-7&gazeX=0.8&gazeY=-0.8"), ("f", "yaw=-28&pitch=20&roll=7&gazeX=0.8&gazeY=0.3")]:
        P.append(("mix_" + name, "hair=1&%s&%s" % (MIX, qs)))
    # 首まわり（髪なし）。体の絵を差し替えたとき、首が二重になったのを見落とした
    NECK = "zoom=3.4&cx=1500&cy=1230"
    for name, qs in [("c", "yaw=0"), ("yawP", "yaw=30"), ("rollP", "roll=25"), ("up", "pitch=25")]:
        P.append(("neck_" + name, "hair=0&%s&%s" % (NECK, qs)))
    # 姿勢を固定した絵でも、髪と瞳のばねは最初の一瞬だけ動く。4 秒ぶん進めて止まった所を撮る（撮るたびに絵が変わらないように）
    P = [(n, q + "&sim=4") for n, q in P]
    for s in ("3.2", "7.5", "11.3"):
        P.append(("demo_" + s, "hair=1&mode=demo&sim=%s&sway=0.1" % s))
    return P


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def shoot_fast(o):
    """Chrome を起動したまま、姿勢だけ切り替えて撮る（shoot.mjs。1 枚 1〜2 秒）。node が要る。"""
    os.makedirs(o.out, exist_ok=True)
    only = [s for s in (o.only or "").split(",") if s]
    plist = [tuple(x.split("=", 1)) for x in o.poses.split(";") if x] if o.poses else poses()
    items = []
    for name, qs in plist:
        if only and not any(name.startswith(p) for p in only):
            continue
        q = urllib.parse.quote("model=%s&%s%s" % (o.model, "" if o.ui else "ui=0&", qs), safe="=&.-,")
        items.append({"name": name, "url": "%s?%s" % (o.page, q)})
        dst = os.path.join(o.out, name + ".png")
        if os.path.isfile(dst):
            os.remove(dst)
    fd, lp = tempfile.mkstemp(prefix="shootlist_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    try:
        rc = subprocess.run([shutil.which("node"), os.path.join(HERE, "shoot.mjs"), lp, os.path.abspath(o.out),
                             "--size", str(o.size), "--jobs", str(o.jobs), "--timeout", str(o.timeout)]).returncode
    finally:
        os.remove(lp)
    sys.exit(rc)


def shoot(o):
    if not o.legacy and shutil.which("node"):
        return shoot_fast(o)
    chrome = next((c for c in CHROME if os.path.isfile(c)), None)
    if not chrome:
        sys.exit("Chrome / Edge が見つかりません")
    os.makedirs(o.out, exist_ok=True)
    only = [s for s in (o.only or "").split(",") if s]
    srv, port = serve()
    bad = []
    try:
        # --poses "名前=URL の指定;名前=URL の指定": 決まった姿勢の代わりに、指定した姿勢だけを撮る（揺れ物の確認など）
        plist = [tuple(x.split("=", 1)) for x in o.poses.split(";") if x] if o.poses else poses()
        for name, qs in plist:
            if only and not any(name.startswith(p) for p in only):
                continue
            q = urllib.parse.quote("model=%s&%s%s" % (o.model, "" if o.ui else "ui=0&", qs), safe="=&.-,")
            url = "http://127.0.0.1:%d/%s?%s" % (port, o.page, q)
            dst = os.path.abspath(os.path.join(o.out, name + ".png"))
            ok = False
            for _ in range(3):
                # 使い回すプロファイル（作っては消さない。シークレットモードなので、前の実行の状態は残らない。経緯は chromeclose.mjs）
                prof = os.path.join(os.environ.get("KESHIN2D_WORK") or os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "keshin2d_work"), "_chrome_prof", "legacy")
                os.makedirs(prof, exist_ok=True)
                if os.path.isfile(dst):
                    os.remove(dst)
                cmd = [chrome, "--headless=new", "--incognito", "--no-first-run", "--disable-component-update", "--disable-background-networking", "--disable-sync",
                       "--disable-gpu", "--enable-unsafe-swiftshader", "--hide-scrollbars",
                       "--window-size=%d,%d" % (o.size, o.size), "--virtual-time-budget=6000", "--enable-logging=stderr",
                       "--user-data-dir=" + prof, "--disk-cache-size=1", "--screenshot=" + dst, url]
                logp = os.path.join(prof, "_stderr.txt")
                # Chrome の出力はファイルへ書かせる（パイプで受けると、時間切れのあと子プロセスがパイプを握ったままになり、ここで待ち続ける）
                with open(logp, "wb") as lf:
                    pr = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=lf)
                    # Chrome は、絵を書き出したあと終了せずに固まることがある。絵が書き出されて大きさが変わらなくなったら、待たずに先へ進む
                    t0, last, stable, err = time.time(), -1, 0, []
                    while pr.poll() is None:
                        time.sleep(0.25)
                        sz = os.path.getsize(dst) if os.path.isfile(dst) else -1
                        stable = stable + 1 if (sz > 0 and sz == last) else 0
                        last = sz
                        if stable >= 6 or time.time() - t0 > o.timeout:
                            if stable < 6:
                                err = ["timeout"]
                            # 自分が起動した Chrome を、子プロセスごと終わらせる（残ると CPU を使い続け、後の撮影も遅くなる）
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pr.pid)], capture_output=True)
                            pr.wait(); break
                if not err:
                    with open(logp, "rb") as lf:
                        err = [l for l in lf.read().decode("utf-8", "replace").splitlines() if "Uncaught" in l or " 404 " in l]
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pr.pid)], capture_output=True)   # 残っていれば、子プロセスごと落とす（プロファイルは消さない）
                if os.path.isfile(dst) and not err:
                    ok = True; break
            print(("ok   " if ok else "FAIL ") + name + ("" if ok else "  " + (err[0][:160] if err else "no image")), flush=True)
            if not ok:
                bad.append(name)
    finally:
        srv.shutdown()
    print("done: %s  failed=%d %s" % (o.out, len(bad), ",".join(bad)))
    sys.exit(1 if bad else 0)


def compare(o):
    names = sorted(set(os.path.basename(p) for p in glob.glob(os.path.join(o.a, "*.png"))) |
                   set(os.path.basename(p) for p in glob.glob(os.path.join(o.b, "*.png"))))
    if o.out:
        os.makedirs(o.out, exist_ok=True)
    ndiff = 0
    for n in names:
        pa, pb = os.path.join(o.a, n), os.path.join(o.b, n)
        if not (os.path.isfile(pa) and os.path.isfile(pb)):
            print("MISSING %-18s %s" % (n, "A に無い" if not os.path.isfile(pa) else "B に無い")); ndiff += 1; continue
        A, B = Image.open(pa).convert("RGB"), Image.open(pb).convert("RGB")
        if A.size != B.size:
            print("SIZE    %-18s %s %s" % (n, A.size, B.size)); ndiff += 1; continue
        d = np.abs(np.asarray(A).astype(np.int16) - np.asarray(B).astype(np.int16)).max(axis=2)
        cnt = int((d > o.tol).sum())
        if cnt == 0:
            print("same    %-18s" % n); continue
        ndiff += 1
        ys, xs = np.where(d > o.tol)
        print("DIFF    %-18s 画素 %d (%.3f%%)  最大差 %d  範囲 x %d-%d y %d-%d" % (n, cnt, 100.0 * cnt / d.size, int(d.max()), xs.min(), xs.max(), ys.min(), ys.max()))
        if o.out:
            D = Image.fromarray(np.clip(d * 4, 0, 255).astype(np.uint8)).convert("RGB")
            c = Image.new("RGB", (A.width * 3 + 20, A.height), (255, 255, 255))
            c.paste(A, (0, 0)); c.paste(B, (A.width + 10, 0)); c.paste(D, (A.width * 2 + 20, 0)); c.save(os.path.join(o.out, n))
    print("比べた絵 %d 枚、違い %d 枚" % (len(names), ndiff))
    sys.exit(1 if ndiff else 0)


def sheet(o):
    only = [s for s in (o.only or "").split(",") if s]
    files = [p for p in sorted(glob.glob(os.path.join(o.dir, "*.png"))) if not only or any(os.path.basename(p).startswith(s) for s in only)]
    if not files:
        sys.exit("絵がありません")
    cols = min(o.cols, len(files)); rows = (len(files) + cols - 1) // cols; c = o.cell
    S = Image.new("RGB", (cols * c, rows * c), (255, 255, 255)); dr = ImageDraw.Draw(S)
    for i, p in enumerate(files):
        im = Image.open(p).convert("RGB").resize((c, c), Image.LANCZOS)
        x, y = (i % cols) * c, (i // cols) * c
        S.paste(im, (x, y)); dr.rectangle([x, y, x + 9 * len(os.path.basename(p)) + 8, y + 20], fill=(255, 255, 255)); dr.text((x + 4, y + 4), os.path.basename(p)[:-4], fill=(0, 0, 0))
    S.save(o.outfile); print(o.outfile, S.size)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("shoot"); a.add_argument("model"); a.add_argument("out"); a.add_argument("--only"); a.add_argument("--size", type=int, default=1100); a.add_argument("--poses"); a.add_argument("--ui", action="store_true", help="操作パネルを出したまま撮る"); a.add_argument("--page", default="index.html"); a.add_argument("--timeout", type=int, default=60, help="1 枚を待つ秒数（パーツの多いモデルは遅い）"); a.add_argument("--jobs", type=int, default=2, help="同時に動かす Chrome の数（GPU で描くので、2 つで足りる。PC を重くしない）"); a.add_argument("--legacy", action="store_true", help="以前の撮り方（1 枚ごとに Chrome を起動し直す。遅い）"); a.set_defaults(f=shoot)
    a = sub.add_parser("compare"); a.add_argument("a"); a.add_argument("b"); a.add_argument("--out"); a.add_argument("--tol", type=int, default=2); a.set_defaults(f=compare)
    a = sub.add_parser("sheet"); a.add_argument("dir"); a.add_argument("outfile"); a.add_argument("--only"); a.add_argument("--cols", type=int, default=4); a.add_argument("--cell", type=int, default=800); a.set_defaults(f=sheet)
    o = ap.parse_args(); o.f(o)
