# -*- coding: utf-8 -*-
"""align.py <基準の絵> <描かせた絵> [x0 y0 x1 y1 ...]

描かせた絵が、基準の絵から、どれだけずれているかを測る（同じ大きさの 2 枚。例: 00_base.png と 01_base_nohair.png）。
  x0 y0 x1 y1: 比べる範囲（その絵の画素。体・顔など、両方の絵に同じ物が写っている範囲）。4 つずつ、いくつでも書ける
  例: align.py 00_base.png 01_base_nohair.png 380 700 640 900
出る値: shift dx・dy（ずれの画素。0.5 以内が目安）、resp（合い方の確かさ。1 に近いほど確か）、diff（色の差）。
範囲を書かなければ、大きさと、不透明度の分布だけを出す。
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


if len(sys.argv) < 3 or (len(sys.argv) - 3) % 4:
    sys.exit(__doc__)
ref = imread(sys.argv[1]); gen = imread(sys.argv[2])
print("size", ref.shape, gen.shape)
a = gen[..., 3] if gen.shape[2] == 4 else None
if a is not None:
    print("alpha: 0=%.1f%% 255=%.1f%% semi=%.1f%%" % ((a == 0).mean()*100, (a == 255).mean()*100, ((a > 0) & (a < 255)).mean()*100))
    print("alpha hist", [int(((a >= lo) & (a < lo+32)).sum()) for lo in range(0, 256, 32)])
boxes = [int(v) for v in sys.argv[3:]]
g1 = cv2.cvtColor(ref[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32); g2 = cv2.cvtColor(gen[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
for i in range(0, len(boxes), 4):
    x0, y0, x1, y1 = boxes[i:i+4]
    (dx, dy), resp = cv2.phaseCorrelate(g1[y0:y1, x0:x1], g2[y0:y1, x0:x1], cv2.createHanningWindow((x1-x0, y1-y0), cv2.CV_32F))
    d = np.abs(ref[y0:y1, x0:x1, :3].astype(int) - gen[y0:y1, x0:x1, :3].astype(int)).max(-1)
    print("box", (x0, y0, x1, y1), "shift dx=%.2f dy=%.2f resp=%.2f  diff mean %.1f over30 %.1f%%" % (dx, dy, resp, d.mean(), (d > 30).mean()*100))
