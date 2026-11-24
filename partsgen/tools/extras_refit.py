# -*- coding: utf-8 -*-
"""extras_refit.py <キャラ名> <番号> [--src 置いた絵.png] [--out 出力.png] [--keep-chain x1]

`PY place` で置いた追加の絵（<名前>_placed.png）を、基準画像（_ref_<番号>.json の from。3 倍の絵）の同じ物に、
**アフィン変換（縦横の伸び・傾きまで）**で合わせ直す。place（extras.py）は、拡大率・回転・位置しか合わせない。
描かせた絵は、形が少し違うことがある（例: 稲妻の飾りが、横幅が細く描かれ、端で 40 画素ずれた。合わせ直しで、面の重なりが 0.53 → 0.72）。

合わせ方: 置いた絵の中の「明るく、色のはっきりした」色（6 色に分けて、暗い色・灰色を外す）に近い面を、両方の絵で取り、
置いた絵の形のまわり（外へ 25 画素まで）だけで比べる（ECC）。輪郭の強さで比べると、基準画像の髪の線につられて合わなかった（相関 0.40）。
稲妻の飾りで、手で色を決めて合わせた結果と、ほぼ同じ（重なり 0.993）。基準画像には、まわりの物（髪・鎖など）も写っているので、
--keep-chain で、その x（3 倍の絵の座標）より左を、比べる範囲から外せる（例: 稲妻の左の端から下がる鎖。200）。
もとの <名前>_placed.png は、作業フォルダの _tries/ に 1 度だけ残す（2 回目からは上書きしない）。確認画像: _check/p_<番号>_refit.png（左 基準、中 合わせた絵、右 交互）
"""
import sys, os, json, shutil, argparse
import numpy as np, cv2
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kenv
ap = argparse.ArgumentParser()
ap.add_argument("char"); ap.add_argument("job")
ap.add_argument("--src"); ap.add_argument("--out"); ap.add_argument("--keep-chain", type=float)
ap.add_argument("--work", help="キャラの作業フォルダ（PY に --work を付けて作ったとき）")
o = ap.parse_args()
work = o.work or kenv.char_work(o.char)     # 作業フォルダの置き場所は kenv.py
conf = json.load(open(os.path.join(HERE, "..", "chars", o.char, "char.json"), encoding="utf-8"))
job = conf["extras"]["jobs"][o.job]
ref_ = json.load(open(os.path.join(work, "_ref_%s.json" % o.job), encoding="utf-8"))
placed_p = os.path.join(work, job["out"] + "_placed.png")
src_p = o.src or placed_p
out_p = o.out or placed_p
pl = np.asarray(Image.open(src_p).convert("RGBA")).astype(np.float32)
rf = np.asarray(Image.open(os.path.join(work, ref_.get("from", "00_base") + "_3x.png")).convert("RGBA")).astype(np.float32)
H, W = pl.shape[:2]
ys, xs = np.nonzero(pl[..., 3] > 128)
pad = 40
x0, y0, x1, y1 = max(0, xs.min() - pad), max(0, ys.min() - pad), min(W, xs.max() + pad), min(H, ys.max() + pad)
P, R = pl[y0:y1, x0:x1], rf[y0:y1, x0:x1]


def lab_of(im):
    return cv2.cvtColor(np.clip(im[..., :3], 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)


# 置いた絵の「明るく、色のはっきりした」色（6 色に分けて、暗い色・灰色を外す）。輪郭線や影の暗い色は、基準画像の髪とまぎれる
# （輪郭の強さで合わせたら、髪の線につられて、相関 0.40 でずれた）
LP = lab_of(P)
sel = (P[..., 3] > 230).reshape(-1)
pix = LP.reshape(-1, 3)[sel]
if len(pix) > 20000:
    pix = pix[np.random.default_rng(0).choice(len(pix), 20000, replace=False)]
_, lab_k, cen = cv2.kmeans(pix, 6, None, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0), 3, cv2.KMEANS_PP_CENTERS)
pal = [c for c in cen if c[0] > 90 and (np.hypot(c[1] - 128, c[2] - 128) > 25 or c[0] > 215)]
if not pal:
    pal = list(cen)
print("合わせる色（Lab）:", [tuple(int(v) for v in c) for c in pal])


def feat(im):
    L = lab_of(im)
    d = np.min(np.stack([((L - c) ** 2).sum(2) for c in pal]), 0)
    f = np.exp(-d / (2 * 18.0 ** 2)) * (im[..., 3] > 128)
    return cv2.GaussianBlur(f.astype(np.float32), (0, 0), 3)


fp, fr = feat(P), feat(R)
valid = cv2.dilate((P[..., 3] > 128).astype(np.uint8), np.ones((51, 51), np.uint8))
if o.keep_chain is not None:
    valid[:, :max(0, int(o.keep_chain - x0))] = 0
warp = np.eye(2, 3, dtype=np.float32)
cc, warp = cv2.findTransformECC(fr, fp, warp, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), valid, 5)
M = warp.copy()                           # 切り出しの座標 → キャンバスの座標
M[0, 2] += x0 - (M[0, 0] * x0 + M[0, 1] * y0); M[1, 2] += y0 - (M[1, 0] * x0 + M[1, 1] * y0)
pm = pl.copy(); pm[..., :3] *= pm[..., 3:4] / 255
res = cv2.warpAffine(pm, M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=0)
a = res[..., 3:4] / 255
res[..., :3] = np.where(a > 1e-4, res[..., :3] / np.maximum(a, 1e-4), 0)
if out_p == placed_p:
    os.makedirs(os.path.join(work, "_tries"), exist_ok=True)
    bak = os.path.join(work, "_tries", job["out"] + "_placed_before_refit.png")
    if not os.path.isfile(bak):
        shutil.copy(placed_p, bak)
Image.fromarray(np.clip(res, 0, 255).astype(np.uint8), "RGBA").save(out_p)
gr = lambda im: (im[..., :3] * (im[..., 3:4] / 255) + 90 * (1 - im[..., 3:4] / 255)).astype(np.uint8)
g1, g2 = gr(R), gr(np.clip(res[y0:y1, x0:x1], 0, 255))
ch = ((np.indices(g1.shape[:2]).sum(0) // 60) % 2 == 0)[..., None]
os.makedirs(os.path.join(work, "_check"), exist_ok=True)
chk = os.path.join(work, "_check", "p_%s_refit.png" % o.job)
Image.fromarray(np.hstack([g1, g2, np.where(ch, g1, g2)])).save(chk)
print("ECC 相関 %.3f  変換（縦横の伸び・傾き・ずれ）%s" % (cc, np.round(warp, 3).tolist()))
print("-> %s  確認画像 %s" % (out_p, chk))
