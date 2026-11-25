# -*- coding: utf-8 -*-
"""fidscale.py <キャラ名> <モデル名>[,<モデル名>…] <出力.png> [--box x0,y0,x1,y1[;x0,y0,x1,y1…]] [--fit s,ox,oy] [--cell 1000] [--work フォルダ] [--q "URL に足す指定"]

基準画像（00_base）とモデルの正面を、**同じ縮尺・同じ位置**で横に並べる（左: 基準画像、右: モデル。モデル名を並べると、その順に右へ足す = 直す前後の見比べ）。
`pipeline.py fidelity` の拡大は、それぞれの絵を別々に切り出すので、縮尺がそろわない（髪飾りが 1.5 倍大きいこと、房が目尻のはねを隠していることに、気づけなかった）。

  --box  見比べる範囲。3 倍の絵（00_base_3x.png）の座標の正方形。; で区切って何段でも。省略すると、頭の全体と、顔（眉〜あご）の 2 段
         （char.json の hair.center_x・head_r と、eyeL.box の高さから決める）
  --fit  3 倍の絵の座標 → モデルの座標（x' = ox + s・x）。省略すると、モデルの model.json の fit（build2.py が書く）。
         古いモデルで fit が無いときは、同じ基準画像から作った別のモデルの値を渡す
出力の 1 コマは --cell 画素。モデルの絵は、?hair=1&yaw=0&sim=3 に、その範囲の cx・cy・zoom を付けて撮る。
  --q    URL に足す指定。"hair=0" と書くと、モデルを髪なしで撮る（髪が、目尻のはねや眉を隠すキャラで、目の位置を測るとき）
"""
import sys, os, json, argparse, subprocess, shutil
from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import kenv
ap = argparse.ArgumentParser()
ap.add_argument("char"); ap.add_argument("models"); ap.add_argument("out")
ap.add_argument("--box"); ap.add_argument("--fit"); ap.add_argument("--cell", type=int, default=1000)
ap.add_argument("--work"); ap.add_argument("--q", default="")
o = ap.parse_args()
work = o.work or kenv.char_work(o.char)     # 作業フォルダの置き場所は kenv.py
conf = json.load(open(os.path.join(HERE, "..", "chars", o.char, "char.json"), encoding="utf-8"))
models = [m for m in o.models.split(",") if m]


def fit_of(model):
    if o.fit:
        s, ox, oy = [float(v) for v in o.fit.split(",")]
        return s, ox, oy
    f = json.load(open(os.path.join(ROOT, "models", model, "model.json"), encoding="utf-8")).get("fit")
    if not f:
        sys.exit("%s/model.json に fit がありません（--fit s,ox,oy で渡すか、PY model で書き出し直す）" % model)
    return f["s"], f["ox"], f["oy"]


if o.box:
    boxes = [[float(v) for v in b.split(",")] for b in o.box.split(";") if b]
    for b in boxes:
        if abs((b[2] - b[0]) - (b[3] - b[1])) > 1:      # 正方形でないと、基準画像だけが、縦横で別の倍率に引き伸ばされて、モデルと大きさが合わなく見える
            print("注意: --box %s は正方形ではありません（幅 %d・高さ %d）。基準画像とモデルの縮尺が、合わなくなります。正方形にしてください" % (",".join("%d" % v for v in b), b[2] - b[0], b[3] - b[1]))
else:
    h = conf.get("hair") or {}
    cx = float(h.get("center_x") or conf["build"]["seed_head"][0]); r = float(h.get("head_r") or 520)
    eb = conf["eyeL"]["box"]; ey = (eb[1] + eb[3]) / 2.0                                              # 目の高さ（3 倍の絵）
    boxes = [[cx - 1.33 * r, ey - 0.45 * r - 1.33 * r, cx + 1.33 * r, ey - 0.45 * r + 1.33 * r],      # 頭の全体（帽子のふち〜えり）
             [cx - 0.8 * r, ey + 0.2 * r - 0.8 * r, cx + 0.8 * r, ey + 0.2 * r + 0.8 * r]]            # 顔（眉〜あご）
base = Image.open(os.path.join(work, "00_base_3x.png")).convert("RGB")
C = o.cell
tmp = kenv.tmp_dir("fidscale_")             # 英数字だけのパスの一時フォルダ（kenv.py）
try:
    shots = {}
    for m in models:
        s, ox, oy = fit_of(m)
        poses = []
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            half = s * (y1 - y0) / 2
            hair = "" if "hair=" in o.q else "hair=1&"            # --q に hair=0 と書けば、髪なしで撮る（目・眉・輪郭を、髪に隠れない形で比べる）
            poses.append("b%d=%syaw=0&sim=3&zoom=%.4f&cx=%.1f&cy=%.1f%s" % (i, hair, 1060 / half, ox + s * (x0 + x1) / 2, oy + s * (y0 + y1) / 2, ("&" + o.q) if o.q else ""))
        d = os.path.join(tmp, m)
        rc = subprocess.run([sys.executable, "-I", os.path.join(HERE, "regress.py"), "shoot", m, d, "--poses", ";".join(poses), "--size", str(C), "--timeout", "120"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT).returncode
        if rc:
            print("%s: 撮影に失敗した絵があります" % m)
        shots[m] = d
    cols = 1 + len(models)
    S = Image.new("RGB", (cols * C + (cols - 1) * 8, len(boxes) * C + (len(boxes) - 1) * 8), (255, 255, 255)); dr = ImageDraw.Draw(S)
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        y = i * (C + 8)
        S.paste(base.crop((int(x0), int(y0), int(x1), int(y1))).resize((C, C), Image.LANCZOS), (0, y))
        dr.rectangle([0, y, 150, y + 20], fill=(0, 0, 0)); dr.text((4, y + 4), "00_base", fill=(255, 255, 255))
        for k, m in enumerate(models):
            p = os.path.join(shots[m], "b%d.png" % i); x = (k + 1) * (C + 8)
            if os.path.isfile(p):
                S.paste(Image.open(p).convert("RGB").resize((C, C), Image.LANCZOS), (x, y))
            dr.rectangle([x, y, x + 150, y + 20], fill=(0, 0, 0)); dr.text((x + 4, y + 4), m, fill=(255, 255, 255))
    os.makedirs(os.path.dirname(os.path.abspath(o.out)), exist_ok=True)
    S.save(o.out); print(o.out, S.size)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
