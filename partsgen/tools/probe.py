# -*- coding: utf-8 -*-
"""probe.py <絵> <名前=x,y> ...

絵の、指定した点のまわり 7×7 画素の色（中央値）を出す。段階 4 で、色の条件（char.json）を決める前に、
このキャラの 肌・首の影・服・白目・瞳・まつげ・眉・髪 の色を実測するためのもの。

  例: probe.py 01_base_nohair_3x.png 肌=1550,1700 服=1450,2600 瞳=1260,2000 眉=1240,1578

出る値と、関係する char.json の項目:
  R-G      肌は大きく（30 前後）、白〜クリーム色の服は小さい（15 前後）。服が肌の条件を通るときは tone_rg_min を、その間の値にする
  H（色相） 瞳 → iris_hue、眉 → brow_hue
  S・V     白目（S が 0 に近い）と肌（S 0.15 前後）の差。eye_open_simple の white_smax
  A        不透明な所が 254 なら（1 行目の「不透明な所の中央値」か、点ごとの A）、char.json に alpha_full: 250 を入れる
"""
import sys, colorsys
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
im = np.asarray(Image.open(sys.argv[1]).convert("RGBA"))
_op = im[..., 3][im[..., 3] > 128]
# 拡大した絵は、最大が 255 でも、不透明な所のほとんどが 254 のことがある（拡大のにじみで、ごく一部だけ 255 になる）。中央値も出す
print("大きさ %dx%d  不透明度の最大 %d  不透明な所の中央値 %d" % (im.shape[1], im.shape[0], int(im[..., 3].max()), int(np.median(_op)) if _op.size else 0))
for arg in sys.argv[2:]:
    name, xy = arg.split("=")
    x, y = [int(v) for v in xy.split(",")]
    r, g, b, a = [int(v) for v in np.median(im[max(0, y - 3):y + 4, max(0, x - 3):x + 4].reshape(-1, 4), 0)]
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    print("%-10s (%4d,%4d)  RGB %3d %3d %3d  A %3d  R-G %4d  H %3.0f  S %.2f  V %.2f" % (name, x, y, r, g, b, a, r - g, h * 360, s, v))
