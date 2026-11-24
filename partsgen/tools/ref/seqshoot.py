# -*- coding: utf-8 -*-
"""seqshoot.py <モデル名> <出力フォルダ> --q "URL の指定" --from 秒 --to 秒 [--fps 60] [--size 700] [--crop x0,y0,x1,y1] [--noshoot] [--cols 10]
   seqshoot.py <モデル名> <出力フォルダ> --q "hair=0&zoom=5&cx=1320&cy=745&sim=3" --sweep eyeR,eyeL:1:0 [--n 61]

動きの途中を、決まったコマ数（既定 60fps）で連続して撮り、**となりのコマとの変化の大きさ**を出す（「ガクッ」と段になる所を探す）。
止めた絵を 0.5 秒おきに見比べても、動きの段（絵の入れ替わり・値の飛び）は見えない。ここでは 1 コマずつ撮って、数字と絵の両方で見る。
--sweep は、時刻の代わりに、値（目の開き・口の開きなど）を少しずつ変えて撮る（頭を止めて、目や口の変形だけの段を見る）。

  各コマは、?sim=秒 で、最初からその時刻まで進めた絵（demo・yawTest・exprTest など、時刻で決まる動きに使う）。
  自動まばたき・視線は乱数なので、mode=mouse や demo では、撮るたびに目のあたりが変わる（yawTest・exprTest は乱数を使わない）。

出力:
  <出力フォルダ>/frames/f00000.png …      撮った絵
  <出力フォルダ>/diff.csv                  コマごとの「前のコマとの差」（平均の絶対差）と、段の強さ（前後の差の平均に対する比）
  <出力フォルダ>/strip_XX.png              コマを順に並べた一覧（--crop の範囲。段の強さが大きいコマに赤い印）
段の強さ = d[i] / ((d[i-1] + d[i+1]) / 2)。なめらかな動きなら 1 前後。2 を超える所は、絵を見て確かめる。
"""
import sys, os, json, argparse, subprocess, shutil, tempfile, urllib.parse
import numpy as np
from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ap = argparse.ArgumentParser()
ap.add_argument("model"); ap.add_argument("out")
ap.add_argument("--q", default="hair=1&yawTest=1"); ap.add_argument("--from", dest="t0", type=float, default=0.0); ap.add_argument("--to", dest="t1", type=float, default=1.0)
ap.add_argument("--fps", type=float, default=60); ap.add_argument("--size", type=int, default=700); ap.add_argument("--crop")
ap.add_argument("--noshoot", action="store_true"); ap.add_argument("--cols", type=int, default=10); ap.add_argument("--cell", type=int, default=260)
ap.add_argument("--page", default="index.html"); ap.add_argument("--jobs", type=int, default=2)
ap.add_argument("--sweep", help="時刻の代わりに、値を少しずつ変えて撮る: 名前,名前:はじめ:おわり（例 eyeR,eyeL:1:0）。--n コマ。--q に sim=3 などを書く")
ap.add_argument("--n", type=int, default=61)
o = ap.parse_args()
fdir = os.path.join(o.out, "frames"); os.makedirs(fdir, exist_ok=True)
if o.sweep:
    keys, a_, b_ = o.sweep.split(":"); keys = keys.split(","); a_, b_ = float(a_), float(b_)
    n = o.n
    times = [a_ + (b_ - a_) * i / (n - 1) for i in range(n)]          # ここでは「時刻」ではなく、値
else:
    n = int(round((o.t1 - o.t0) * o.fps)) + 1
    times = [o.t0 + i / o.fps for i in range(n)]
names = ["f%05d" % i for i in range(n)]
if not o.noshoot:
    items = []
    for nm, t in zip(names, times):
        if o.sweep:
            qs = urllib.parse.quote("model=%s&ui=0&%s&%s" % (o.model, o.q, "&".join("%s=%.5f" % (k, t) for k in keys)), safe="=&.-,")
        else:
            qs = urllib.parse.quote("model=%s&ui=0&%s&sim=%.5f" % (o.model, o.q, max(t, 1 / 60)), safe="=&.-,")
        items.append({"name": nm, "url": "%s?%s" % (o.page, qs)})
    fd, lp = tempfile.mkstemp(prefix="seqlist_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    try:
        rc = subprocess.run([shutil.which("node"), os.path.join(TOOLS, "shoot.mjs"), lp, os.path.abspath(fdir), "--size", str(o.size), "--jobs", str(o.jobs), "--timeout", "120"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        print(rc.stdout.strip().splitlines()[-1] if rc.stdout.strip() else "（撮影の出力なし）")
    finally:
        os.remove(lp)
crop = [int(v) for v in o.crop.split(",")] if o.crop else None
ims = []
for nm in names:
    p = os.path.join(fdir, nm + ".png")
    if not os.path.isfile(p):
        ims.append(None); continue
    im = Image.open(p).convert("RGB")
    ims.append(im.crop(crop) if crop else im)
d = [0.0]
for i in range(1, n):
    if ims[i] is None or ims[i - 1] is None:
        d.append(float("nan")); continue
    a, b = np.asarray(ims[i - 1]).astype(np.int16), np.asarray(ims[i]).astype(np.int16)
    d.append(float(np.abs(a - b).mean()))
jerk = [0.0] * n
for i in range(2, n - 1):
    m = (d[i - 1] + d[i + 1]) / 2
    jerk[i] = d[i] / m if m > 0.02 else (d[i] / 0.02 if d[i] > 0.04 else 0.0)
with open(os.path.join(o.out, "diff.csv"), "w", encoding="utf-8") as f:
    f.write("frame,time,diff,jerk\n")
    for i in range(n):
        f.write("%d,%.4f,%.4f,%.3f\n" % (i, times[i], d[i], jerk[i]))
bad = [i for i in range(n) if jerk[i] > 2.0]
if o.sweep:
    print("コマ %d 枚（%s を %g → %g）  差の平均 %.3f  最大 %.3f（%d コマ目）" % (n, o.sweep.split(":")[0], times[0], times[-1], float(np.nanmean(d[1:])), float(np.nanmax(d[1:])), int(np.nanargmax(d[1:])) + 1))
else:
    print("コマ %d 枚（%.3f〜%.3f 秒、%g fps）  差の平均 %.3f  最大 %.3f（%d コマ目）" % (n, o.t0, o.t1, o.fps, float(np.nanmean(d[1:])), float(np.nanmax(d[1:])), int(np.nanargmax(d[1:])) + 1))
print("段の強さが 2 を超えるコマ: " + (", ".join("%d(%s %.3f 比%.1f 差%.2f)" % (i, "値" if o.sweep else "秒", times[i], jerk[i], d[i]) for i in bad) if bad else "なし"))
C = o.cell; per = o.cols * 6
for page in range((n + per - 1) // per):
    sub = list(range(page * per, min(n, (page + 1) * per)))
    rows = (len(sub) + o.cols - 1) // o.cols
    S = Image.new("RGB", (o.cols * C, rows * C), (30, 30, 30)); dr = ImageDraw.Draw(S)
    for k, i in enumerate(sub):
        if ims[i] is None:
            continue
        x, y = (k % o.cols) * C, (k // o.cols) * C
        im = ims[i].copy(); im.thumbnail((C, C), Image.LANCZOS); S.paste(im, (x, y))
        hot = jerk[i] > 2.0
        dr.rectangle([x, y, x + 118, y + 14], fill=(200, 0, 0) if hot else (0, 0, 0))
        dr.text((x + 3, y + 1), "%d %.3fs d%.2f" % (i, times[i], d[i]), fill=(255, 255, 255))
    p = os.path.join(o.out, "strip_%02d.png" % page); S.save(p); print(p, S.size)
