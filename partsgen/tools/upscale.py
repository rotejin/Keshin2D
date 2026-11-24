# -*- coding: utf-8 -*-
"""upscale.py <画像 or フォルダ>... [--scale 3] [--out フォルダ] [--force]
upscale.py --install                 Real-ESRGAN を取ってきて、作業フォルダの置き場所に置く（pipeline.py install-upscaler と同じ）

絵を拡大して <名前>_3x.png を書く（Photoshop の代わり）。
Real-ESRGAN (realesrgan-ncnn-vulkan、モデル realesrgan-x4plus-anime) で 4 倍にしてから、
Lanczos で目的の倍率へ縮める。透過は「色」と「不透明度」を別々に拡大して合わせる
（透明な画素に残った色が、ふちににじまないようにするため）。

Real-ESRGAN の場所は、次の順で探す:
  1. 環境変数 REALESRGAN_ROOT
  2. partsgen/upscaler.json の "root"
  3. partsgen/vendor/realesrgan-ncnn-vulkan
  4. <作業フォルダの置き場所>/_tools/realesrgan-ncnn-vulkan（--install が置く場所。置き場所の決め方は kenv.py）
そのフォルダに realesrgan-ncnn-vulkan.exe（Windows 以外は realesrgan-ncnn-vulkan）と models/realesrgan-x4plus-anime.{bin,param} が要る。
入手先とライセンスは partsgen/UPSCALER.md。
"""
import sys, os, json, glob, shutil, subprocess, argparse, hashlib, zipfile
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kenv

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
MODEL = "realesrgan-x4plus-anime"
# --install が取ってくる物: Real-ESRGAN の配布元（GitHub の xinntao/Real-ESRGAN）の v0.2.5.0 にある、OS ごとの zip。
# チェックサム（SHA-256）は、2026-11-24 に取ってきた物の値。違っていたら、置かずに止まる
RELEASE = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-%s.zip"
ZIPS = {"win32": ("windows", "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"),
        "linux": ("ubuntu", "e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96"),
        "darwin": ("macos", "e0ad05580abfeb25f8d8fb55aaf7bedf552c375b5b4d9bd3c8d59764d2cc333a")}


def install_dir():
    base, _ = kenv.work_base_info()
    return os.path.join(base, "_tools", "realesrgan-ncnn-vulkan") if base else None


def has_esrgan(c):
    """そのフォルダに、実行ファイルとモデルがそろっていれば、実行ファイルのパス。無ければ None"""
    exe = os.path.join(c, "realesrgan-ncnn-vulkan.exe")
    if not os.path.isfile(exe):
        exe = os.path.join(c, "realesrgan-ncnn-vulkan")
    ok = os.path.isfile(exe) and all(os.path.isfile(os.path.join(c, "models", MODEL + e)) for e in (".bin", ".param"))
    return exe if ok else None


def find_root():
    cands = []
    if os.environ.get("REALESRGAN_ROOT"):
        cands.append(os.environ["REALESRGAN_ROOT"])
    cfg = os.path.join(HERE, "..", "upscaler.json")
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8") as f:
            r = json.load(f).get("root")
        if r:
            cands.append(r)
    cands.append(os.path.join(HERE, "..", "vendor", "realesrgan-ncnn-vulkan"))
    if install_dir():
        cands.append(install_dir())
    for c in cands:
        exe = has_esrgan(c)
        if exe:
            return os.path.abspath(c), os.path.abspath(exe)
    sys.exit("Real-ESRGAN が見つかりません。pipeline.py install-upscaler で取ってくるか、partsgen/UPSCALER.md の手順で用意してください。\n探した場所:\n  "
             + "\n  ".join(os.path.abspath(c) for c in cands))


def install():
    """Real-ESRGAN（実行ファイルと、モデル realesrgan-x4plus-anime）を、配布元から取ってきて置く。同梱はしていないので、使う人の PC で 1 回だけ行う"""
    import urllib.request
    plat = "win32" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")
    osname, sha = ZIPS[plat]
    dest = install_dir()
    if not dest:
        sys.exit(kenv.work_base_info()[1])
    if has_esrgan(dest):
        print("もう置いてあります: " + dest)
        return dest
    url = RELEASE % osname
    tmp = kenv.tmp_dir("esrgan_")
    try:
        zp = os.path.join(tmp, "esrgan.zip")
        print("取ってきます（約 45〜52MB）: " + url, flush=True)
        h = hashlib.sha256(); got = 0
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(zp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0); step = 0
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b); h.update(b); got += len(b)
                    if total and got * 4 // total > step:
                        step = got * 4 // total; print("  %d%%" % (100 * got // total), flush=True)
        except OSError as e:
            sys.exit("取ってこられませんでした（%s）。ネットワークを確かめるか、partsgen/UPSCALER.md の手順で、手で置いてください。" % e)
        if h.hexdigest() != sha:
            sys.exit("取ってきた物のチェックサムが、控えと違います（置いていません）。\n  控え: %s\n  今回: %s\n配布物が変わった可能性があります。partsgen/UPSCALER.md の手順で、手で置いてください。" % (sha, h.hexdigest()))
        with zipfile.ZipFile(zp) as z:
            # 使う物だけを出す: 実行ファイル、その DLL、モデル realesrgan-x4plus-anime、配布元の説明（README_*.md）。どれも zip の直下か models/ の直下
            want = [n for n in z.namelist() if "\\" not in n and (
                ("/" not in n and (n.startswith("realesrgan-ncnn-vulkan") or n.lower().endswith(".dll") or n.startswith("README")))
                or (n.startswith("models/" + MODEL + ".") and n.count("/") == 1))]
            os.makedirs(dest, exist_ok=True)
            for n in want:
                z.extract(n, dest)
        exe = has_esrgan(dest)
        if not exe:
            sys.exit("展開しましたが、実行ファイルかモデルが見つかりません: " + dest)
        if plat != "win32":
            os.chmod(exe, 0o755)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("置きました: " + dest)
    print("ライセンス: Real-ESRGAN（モデルを含む）は BSD 3-Clause、Real-ESRGAN-ncnn-vulkan（実行ファイル）は MIT、ncnn は BSD 3-Clause（partsgen/UPSCALER.md）。")
    return dest


def esrgan(exe, root, src, dst, tile):
    r = subprocess.run([exe, "-i", src, "-o", dst, "-m", os.path.join(root, "models"), "-n", MODEL,
                        "-s", "4", "-t", str(tile), "-f", "png"], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(dst):
        sys.exit("Real-ESRGAN が失敗しました: " + src + "\n" + (r.stderr or "")[-600:])


def fill_transparent(rgb, a):
    """透明な画素の色を、近くの不透明な画素の色で埋める（拡大でふちに黒や白がにじまないように）"""
    import cv2
    out = rgb.astype(np.float32)
    w = (a > 8).astype(np.float32)
    acc, wacc = out * w[..., None], w.copy()
    known = w > 0
    for k in (3, 5, 9, 17, 33, 65, 129):
        if known.all():
            break
        s = cv2.blur(acc, (k, k)); sw = cv2.blur(wacc, (k, k))
        newly = (~known) & (sw > 1e-6)
        out[newly] = s[newly] / sw[newly][..., None]
        acc[newly] = out[newly]; wacc[newly] = 1
        known |= newly
    return np.clip(out, 0, 255).astype(np.uint8)


def upscale(exe, root, src, dst, scale, tile, tmp):
    im = Image.open(src).convert("RGBA")
    W, H = im.size
    arr = np.asarray(im)
    rgb, a = arr[..., :3], arr[..., 3]
    opaque = bool((a == 255).all())
    p_in, p_out = os.path.join(tmp, "in.png"), os.path.join(tmp, "out.png")
    Image.fromarray(rgb if opaque else fill_transparent(rgb, a), "RGB").save(p_in)
    esrgan(exe, root, p_in, p_out, tile)
    size = (round(W * scale), round(H * scale))
    big = Image.open(p_out).convert("RGB").resize(size, Image.LANCZOS)
    if opaque:
        alpha = Image.new("L", size, 255)
    else:
        # 不透明度も同じモデルで拡大する（ふちの鋭さを色とそろえる）
        Image.merge("RGB", [Image.fromarray(a, "L")] * 3).save(p_in)
        esrgan(exe, root, p_in, p_out, tile)
        alpha = Image.open(p_out).convert("L").resize(size, Image.LANCZOS)
        soft = Image.fromarray(a, "L").resize(size, Image.BICUBIC)
        aa, sa = np.asarray(alpha).astype(np.int16), np.asarray(soft).astype(np.int16)
        aa[sa == 0] = 0          # 元が完全に透明な所は透明のまま
        aa[sa == 255] = 255      # 元が完全に不透明な所は不透明のまま
        alpha = Image.fromarray(np.clip(aa, 0, 255).astype(np.uint8), "L")
    big.putalpha(alpha)
    big.save(dst)
    for p in (p_in, p_out):
        if os.path.isfile(p):
            os.remove(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="*")
    ap.add_argument("--scale", type=float, default=3)
    ap.add_argument("--out", default=None, help="出力フォルダ（既定は入力と同じ場所）")
    ap.add_argument("--tile", type=int, default=128)
    ap.add_argument("--force", action="store_true", help="出力があっても作り直す")
    ap.add_argument("--install", action="store_true", help="Real-ESRGAN を取ってきて置く（絵は拡大しない）")
    o = ap.parse_args()
    if o.install:
        install()
        return
    if not o.inputs:
        ap.error("拡大する絵かフォルダを指定してください")
    root, exe = find_root()
    tag = "_%gx" % o.scale
    files = []
    for p in o.inputs:
        files += sorted(glob.glob(os.path.join(p, "*.png"))) if os.path.isdir(p) else [p]
    files = [f for f in files if not os.path.splitext(os.path.basename(f))[0].endswith(tag) and not os.path.basename(f).startswith("_")]
    tmp = kenv.tmp_dir("upscale_")   # 一時フォルダは、英数字だけのパスにする（Real-ESRGAN は日本語のパスを読めない。kenv.py）
    try:
        for f in files:
            d = o.out or os.path.dirname(os.path.abspath(f))
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, os.path.splitext(os.path.basename(f))[0] + tag + ".png")
            if os.path.isfile(dst) and not o.force:
                print("skip", os.path.basename(dst)); continue
            upscale(exe, root, f, dst, o.scale, o.tile, tmp)
            print("ok  ", os.path.basename(dst), Image.open(dst).size)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
