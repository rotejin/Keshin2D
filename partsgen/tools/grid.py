# -*- coding: utf-8 -*-
"""grid.py <絵> <出力.png> <x0> <y0> <x1> <y1> <倍率> <目盛りの間隔> [flip]

絵の、指定した範囲（x0,y0〜x1,y1）を拡大して、座標の目盛りを付けて書く。段階 4 で、目・眉・鼻・口の箱や、
輪郭線を外す折れ線の座標を読むためのもの。透過の絵は、緑がかった灰色の背景に重ねる。
  例: grid.py 01_base_nohair_3x.png eyes.png 1000 1400 2100 2000 2 50
目盛りの数字は、線のすぐ右（縦の線）・すぐ上（横の線）に書いてある（数字の左・下の線が、その値）。
座標は「切り出しの左上（x0, y0）+ 画面の画素 ÷ 倍率」で計算する。flip を付けると、絵を左右に返してから切り出す。
"""
import sys, os, numpy as np, cv2

for _f in (sys.stdout, sys.stderr):          # 出力は UTF-8（OS の文字コードのままだと、日本語の Windows 以外で、日本語の表示で止まる）
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def imread(p):
    """絵を読む（BGR または BGRA）。cv2.imread は、日本語を含むパスを読めないので、中身を読んでから解く"""
    a = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_UNCHANGED)
    if a is None:
        sys.exit("絵を読めません: " + p)
    return a


def imwrite(p, img):
    ok, buf = cv2.imencode(os.path.splitext(p)[1] or ".png", img)
    if not ok:
        sys.exit("絵を書けません: " + p)
    buf.tofile(p)


if len(sys.argv) < 9:
    sys.exit(__doc__)
src, out = sys.argv[1], sys.argv[2]
x0,y0,x1,y1,k,step = [int(v) for v in sys.argv[3:9]]
flip = len(sys.argv)>9 and sys.argv[9]=="flip"
img = imread(src)
if flip: img = img[:, ::-1]
c = img[y0:y1, x0:x1]
bg = np.full(c.shape[:2]+(3,), (120,160,120), np.float32)
a = c[...,3:4].astype(np.float32)/255 if c.shape[2]==4 else 1
c = (bg*(1-a) + c[...,:3]*a).astype(np.uint8)
c = cv2.resize(c, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
for x in range((x0//step+1)*step, x1, step):
    X = (x-x0)*k; cv2.line(c,(X,0),(X,c.shape[0]),(0,160,0),1); cv2.putText(c,str(x),(X+2,12),cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,0,255),1)
for y in range((y0//step+1)*step, y1, step):
    Y = (y-y0)*k; cv2.line(c,(0,Y),(c.shape[1],Y),(0,160,0),1); cv2.putText(c,str(y),(2,Y-2),cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,0,255),1)
imwrite(out, c)
