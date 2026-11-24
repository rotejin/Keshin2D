# -*- coding: utf-8 -*-
"""mview.py <モデルのフォルダ> <出力.png> <倍率> <レイヤー名> [<レイヤー名>+<レイヤー名> ...]

モデル（models/<名前>）のレイヤーを、名前で指定して、緑がかった灰色の背景に並べる。+ でつないだ名前は、重ねて 1 コマにする。
  例: mview.py models/kurage02 out.png 0.5 輪郭ベース 帽子 前髪下地+前房01
レイヤーの名前は、model.json の layers の name。
"""
import sys, os, json, numpy as np, cv2

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


if len(sys.argv) < 5:
    sys.exit(__doc__)
d, out, k = sys.argv[1], sys.argv[2], float(sys.argv[3])
m = json.load(open(os.path.join(d, "model.json"), encoding="utf-8"))
by = {l["name"]: l for l in m["layers"]}
tiles = []
for spec in sys.argv[4:]:
    names = spec.split("+")
    bad = [n for n in names if n not in by]
    if bad:
        sys.exit("そのレイヤーがありません: %s（あるレイヤー: %s）" % ("・".join(bad), " ".join(by)))
    ls = [by[n] for n in names]
    x0 = min(l["x"] for l in ls); y0 = min(l["y"] for l in ls)
    x1 = max(l["x"] + l["w"] for l in ls); y1 = max(l["y"] + l["h"] for l in ls)
    c = np.full((y1 - y0, x1 - x0, 3), (170, 200, 170), np.float32)
    for l in ls:
        im = imread(os.path.join(d, "parts", l["src"])).astype(np.float32)
        a = im[..., 3:4] / 255
        r = c[l["y"] - y0:l["y"] - y0 + l["h"], l["x"] - x0:l["x"] - x0 + l["w"]]
        r[:] = r * (1 - a) + im[..., :3] * a
    c = cv2.resize(c.astype(np.uint8), None, fx=k, fy=k, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    tiles.append(c)
h = max(t.shape[0] for t in tiles)
tiles = [np.vstack([t, np.full((h - t.shape[0], t.shape[1], 3), 255, np.uint8)]) for t in tiles]
imwrite(out, np.hstack(tiles))
