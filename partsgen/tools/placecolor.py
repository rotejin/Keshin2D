# -*- coding: utf-8 -*-
"""placecolor.py <キャラ名> <番号> --color R,G,B [--tol 28]

追加で描かせた絵（extras.jobs の番号）を、**その物だけにある色の面**（例: 動物の耳の内側のピンク、飾りの水色）で、もとの絵（3 倍の絵）の同じ物に合わせて、
手置きの値（char.json の extras.jobs.<番号>.place）を出す。絵は書き換えない（値を出すだけ）。

`PY place` の自動の位置合わせ（点の対応・形）は、模様の少ない絵や、もとの絵で一部が隠れている物（髪に隠れた耳の付け根）では、
拡大率が小さめに出たり（一致 0.85 でも、拡大率が 7% 小さかった）、まったく外れたりする（拡大率 0.15）。
`extras_refit.py`（アフィンで合わせ直す）も、まわりに似た色の物（白い髪）があると、横に 2 割 伸ばすことがあった。
その物だけにある色の面は、もとの絵でも、描かせた絵でも、同じ形で取れるので、面積と重心から、拡大率と位置が決まる。

出す値:
  place  [拡大率, 左, 上]                 拡大率 = 面積の比の平方根。位置 = 面の重心を合わせる
  place4 [横の拡大率, 縦の拡大率, 左, 上]   面の箱の幅・高さの比。描かせた絵の縦横の比が、もとの絵と数 % 違うとき
  それぞれ、もとの絵の面との重なり（IoU。1 に近いほど合っている）も出す。重なりの大きい方を、char.json に書いて、PY place <キャラ名> <番号>。

--color は、probe.py で、もとの絵のその面の色を測って書く。--tol は、その色からの、R・G・B の差の上限（書かなければ 28）。
"""
import sys, os, json, argparse
import numpy as np, cv2
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kenv

ap = argparse.ArgumentParser()
ap.add_argument("char"); ap.add_argument("job")
ap.add_argument("--color", required=True, help="その物だけにある色 R,G,B")
ap.add_argument("--tol", type=float, default=28.0)
ap.add_argument("--work", help="キャラの作業フォルダ（PY に --work を付けて作ったとき）")
o = ap.parse_args()
work = o.work or kenv.char_work(o.char)
conf = json.load(open(os.path.join(HERE, "..", "chars", o.char, "char.json"), encoding="utf-8"))
job = conf["extras"]["jobs"][o.job]
ref = json.load(open(os.path.join(work, "_ref_%s.json" % o.job), encoding="utf-8"))
x0, y0, x1, y1 = ref["box"]
col = np.array([float(v) for v in o.color.split(",")], np.float32)


def face(im):
    """その色の面のうち、いちばん大きい塊（マスク・箱・重心・面積）"""
    d = np.abs(im[..., :3].astype(np.float32) - col).max(2)
    m = ((im[..., 3] > 128) & (d <= o.tol)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    k, lab, st, cen = cv2.connectedComponentsWithStats(m, connectivity=8)
    if k <= 1:
        sys.exit("その色の面が見つかりません: %s（--tol を広げるか、--color を測り直す）" % o.color)
    big = 1 + int(np.argmax(st[1:, 4]))
    return lab == big, st[big], cen[big]


d = np.asarray(Image.open(os.path.join(work, job["out"] + ".png")).convert("RGBA"))
b = np.asarray(Image.open(os.path.join(work, ref.get("from", "00_base") + "_3x.png")).convert("RGBA"))[y0:y1, x0:x1]
md, sd, cd = face(d)
mb, sb, cb = face(b)


def iou(A):
    w = cv2.warpAffine(md.astype(np.uint8), A, (b.shape[1], b.shape[0]), flags=cv2.INTER_NEAREST) > 0
    return float((w & mb).sum()) / max(1.0, float((w | mb).sum()))


s = float(np.sqrt(sb[4] / sd[4]))
A1 = np.float32([[s, 0, cb[0] - s * cd[0]], [0, s, cb[1] - s * cd[1]]])
sx, sy = sb[2] / sd[2], sb[3] / sd[3]
bxc, byc = sb[0] + sb[2] / 2.0, sb[1] + sb[3] / 2.0
dxc, dyc = sd[0] + sd[2] / 2.0, sd[1] + sd[3] / 2.0
A2 = np.float32([[sx, 0, bxc - sx * dxc], [0, sy, byc - sy * dyc]])
print("番号 %s  色 %s ±%g  面: 描かせた絵 %d 画素（箱 %d×%d）・もとの絵 %d 画素（箱 %d×%d）" % (o.job, o.color, o.tol, sd[4], sd[2], sd[3], sb[4], sb[2], sb[3]))
print("place  %s  重なり %.3f" % (json.dumps([round(s, 4), round(float(x0 + A1[0, 2]), 1), round(float(y0 + A1[1, 2]), 1)]), iou(A1)))
print("place4 %s  重なり %.3f（横 %.4f・縦 %.4f。比の差 %.1f%%）" % (json.dumps([round(float(sx), 4), round(float(sy), 4), round(float(x0 + A2[0, 2]), 1), round(float(y0 + A2[1, 2]), 1)]), iou(A2), sx, sy, 100.0 * abs(sx / sy - 1)))
