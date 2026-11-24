# -*- coding: utf-8 -*-
"""haircover.py <キャラ名> <front|back> [出力.png]

髪の房の目印（char.json の hair.<部分>.parts の多角形）を、髪のデザインの絵（作業フォルダの hair/src/design_<部分>.png）に
色を変えて重ね、**どの目印にも入らない髪を青で塗る**。100 画素ごとの目盛りと、目印の番号付き。覆えていない髪の割合を出す。

`HD parts` の前に、目印が房の全体を覆っているかを見るために使う（例: 最初の目印が、前の髪の 29%・後ろ髪の 43% を覆えていなかった。
覆えていない髪は、どの房にも入らず、下地のまま動かない）。前の髪は、頭頂の下地（`char.json` の `hair.front.top_cut` より上）、後ろ髪は、後頭部の丸いドーム（cap）は、
青のままでよい（下地・cap が受け持つ）。房のすき間・毛先の青を、目印を広げて消す。
出力は、省略すると 作業フォルダ/_obs/haircover_<部分>.png
"""
import sys, os, json
import numpy as np, cv2
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kenv
if len(sys.argv) < 3 or sys.argv[2] not in ("front", "back"):
    sys.exit(__doc__)
char, part = sys.argv[1], sys.argv[2]
work = kenv.char_work(char)                 # 作業フォルダの置き場所は kenv.py（hairdraw.py と同じ）
conf = json.load(open(os.path.join(HERE, "..", "chars", char, "char.json"), encoding="utf-8"))
parts = conf["hair"][part].get("parts", [])
out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(work, "_obs", "haircover_%s.png" % part)
D = np.asarray(Image.open(os.path.join(work, "hair", "src", "design_%s.png" % part)).convert("RGBA")).astype(np.float32)
op = D[..., 3] > 128
vis = D[..., :3] * 0.5 + 64
cols = [(255, 60, 60), (60, 200, 60), (255, 200, 0), (200, 60, 255), (0, 200, 255), (255, 120, 200), (120, 255, 120), (255, 255, 255), (255, 140, 0)]
any_ = np.zeros(op.shape, bool)
labels = []
for i, p in enumerate(parts):
    m = np.zeros(op.shape, np.uint8)
    cv2.fillPoly(m, [np.array(p["poly"], np.int32)], 1)
    m = (m > 0) & op
    any_ |= m
    vis[m] = vis[m] * 0.4 + np.array(cols[i % len(cols)], np.float32) * 0.6
    ys, xs = np.nonzero(m)
    if len(xs):
        labels.append(("%d %s" % (i, p.get("name", "")), (int(xs.mean()), int(ys.mean()))))
un = op & ~any_
vis[un] = (40, 60, 255)
vis = np.ascontiguousarray(np.clip(vis, 0, 255).astype(np.uint8))
H, W = op.shape
for v in range(100, max(H, W), 100):
    cv2.line(vis, (v, 0), (v, H), (255, 255, 255), 1)
    cv2.line(vis, (0, v), (W, v), (255, 255, 255), 1)
    cv2.putText(vis, str(v), (v + 2, 20), 0, 0.6, (255, 255, 255), 2)
    cv2.putText(vis, str(v), (2, v - 3), 0, 0.6, (255, 255, 255), 2)
for t, xy in labels:                     # 番号（日本語の名前は putText で描けないので、番号だけが読める）
    cv2.putText(vis, t.split()[0], xy, 0, 1.2, (0, 0, 0), 4)
    cv2.putText(vis, t.split()[0], xy, 0, 1.2, (255, 255, 255), 2)
os.makedirs(os.path.dirname(out), exist_ok=True)
Image.fromarray(vis).resize((W * 3 // 4, H * 3 // 4)).save(out)
print("目印 %d 個: %s" % (len(parts), "、".join(t for t, _ in labels)))
print("覆えていない髪 %.1f%%  -> %s" % (100 * un.sum() / max(op.sum(), 1), out))
