# -*- coding: utf-8 -*-
"""extras.py <作業フォルダ> <番号>=<出力の名前> ...

追加で描かせた絵（揺れ物など。char.json の extras.jobs）を、もとの絵の中の位置へ置く。

描かせた絵は、見本（_ref_<番号>.png = もとの絵のその部分の拡大）と同じ物を、大きく清書したもの。
見本と描かせた絵の間で、同じ模様の点を対応させ（SIFT + RANSAC）、拡大率・回転・位置を求めて、
（模様の少ない小さな絵は点が取れないので、形と色を、大きさを変えながら見本の上で探す）
3 倍の絵と同じ大きさのキャンバスへ置く（<名前>_placed.png）。位置を合わせて描かせるより、位置も質も確実。

対応が取れないとき（模様の少ない小さな絵など）は、char.json の extras.jobs.<番号>.place = [拡大率, 左, 上]（3 倍の絵での値）で手で置く。
確認用に、もとの絵と重ねて比べる絵を _check/p_<番号>.png に出す（左: もとの絵、中: 置いた絵、右: 交互に重ねた絵）。
"""
import sys, os, json
import numpy as np
import cv2
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
CHAR = json.load(open(os.environ["CHARCFG"], encoding="utf-8")) if os.environ.get("CHARCFG") else {}
JOBS = (CHAR.get("extras") or {}).get("jobs") or {}


def premult(im):
    a = im[..., 3:4].astype(np.float32) / 255
    return np.dstack([im[..., :3].astype(np.float32) * a, a * 255])


def unpremult(pm):
    a = pm[..., 3:4] / 255
    rgb = np.where(a > 1e-4, pm[..., :3] / np.maximum(a, 1e-4), 0)
    return np.clip(np.dstack([rgb, pm[..., 3:4]]), 0, 255).astype(np.uint8)


def on_gray(rgba, bg=128):
    a = rgba[..., 3:4].astype(np.float32) / 255
    return (rgba[..., :3].astype(np.float32) * a + bg * (1 - a)).astype(np.uint8)


def register(gen, ref):
    """描かせた絵 gen（RGBA）→ 見本 ref（RGB）への相似変換（2x3）と、対応した点の数"""
    g = cv2.cvtColor(on_gray(gen), cv2.COLOR_RGB2GRAY)
    r = cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY)
    best = (None, 0)
    for sc in (1.0, 0.5):                                   # 大きさがかなり違うときのため、縮めた絵でも試す
        g2 = cv2.resize(g, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA) if sc != 1 else g
        sift = cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.02)
        k1, d1 = sift.detectAndCompute(g2, None)
        k2, d2 = sift.detectAndCompute(r, None)
        if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
            continue
        m = cv2.BFMatcher().knnMatch(d1, d2, k=2)
        good = [a for a, b in (p for p in m if len(p) == 2) if a.distance < 0.78 * b.distance]
        if len(good) < 8:
            continue
        p1 = np.float32([k1[a.queryIdx].pt for a in good]) / sc
        p2 = np.float32([k2[a.trainIdx].pt for a in good])
        M, inl = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=6.0, maxIters=5000, confidence=0.999)
        n = int(inl.sum()) if inl is not None else 0
        if M is not None and n > best[1]:
            best = (M, n)
    return best


def register_shape(gen, ref):
    """模様の少ない小さな絵（花・リボン・玉の並びなど）用: 描かせた絵の形と色を、大きさを変えながら見本の上で探す（回転なし）。
    戻り値は、相似変換（2x3）と、一致の度合い（-1〜1）"""
    a = gen[..., 3] > 128
    ys, xs = np.where(a)
    bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    g = on_gray(gen)[by0:by1, bx0:bx1]
    m = (a[by0:by1, bx0:bx1] * 255).astype(np.uint8)
    gl = max(g.shape[:2])

    def search(f, scales):
        r = cv2.resize(ref, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        best = (-2, None)
        for sc in scales:
            w, h = int(round(g.shape[1] * sc * f)), int(round(g.shape[0] * sc * f))
            if w < 12 or h < 12 or w > r.shape[1] or h > r.shape[0]:
                continue
            t = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA)
            tm = cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(r, t, cv2.TM_CCOEFF_NORMED, mask=tm)
            res[~np.isfinite(res)] = -2
            _, v, _, loc = cv2.minMaxLoc(res)
            if v > best[0]:
                best = (v, (sc, loc[0] / f, loc[1] / f))
        return best

    rl = max(ref.shape[:2])
    f0 = 320.0 / rl
    v, b = search(f0, np.geomspace(0.12 * rl / gl, 1.0 * rl / gl, 60))
    if b is None:
        return None, -2
    f1 = min(1.0, 800.0 / rl)
    v, b = search(f1, b[0] * np.linspace(0.93, 1.07, 29))
    sc, tx, ty = b
    return np.float64([[sc, 0, tx - sc * bx0], [0, sc, ty - sc * by0]]), v


def main():
    work = sys.argv[1]
    os.makedirs(os.path.join(work, "_check"), exist_ok=True)
    bad = 0
    for arg in sys.argv[2:]:
        n, out = arg.split("=")
        mir = JOBS.get(n, {}).get("mirror")
        if mir:
            # 左右で対になる物は、片方だけ描かせて、左右を返して使う。{"of": もとの番号, "axis": 返す軸の x（3 倍の絵で）。省略は "around" の絵の左右のまん中}
            srcp = Image.open(os.path.join(work, JOBS[mir["of"]]["out"] + "_placed.png")).convert("RGBA")
            ax = mir.get("axis")
            if ax is None:
                al = np.asarray(Image.open(os.path.join(work, JOBS[mir["around"]]["out"] + "_placed.png")).convert("RGBA"))[..., 3]
                xs = np.where(al.max(0) > 8)[0]
                ax = (xs.min() + xs.max() + 1) / 2.0
            Wm = srcp.width
            fl = srcp.transpose(Image.FLIP_LEFT_RIGHT)          # x -> Wm-1-x。軸 ax で返すには、さらに 2*ax-(Wm-1) だけずらす
            res_ = Image.new("RGBA", srcp.size, (0, 0, 0, 0))
            res_.paste(fl, (int(round(2 * ax - Wm)), 0))
            res_.save(os.path.join(work, out + "_placed.png"))
            print("%s %s: %s を左右に返して置いた（軸 x=%.1f）" % (n, out, JOBS[mir["of"]]["out"], ax))
            continue
        meta = json.load(open(os.path.join(work, "_ref_%s.json" % n)))
        src = os.path.join(work, out + "_3x.png")
        up = 3.0 if os.path.isfile(src) else 1.0            # Real-ESRGAN で拡大した絵があれば、それを置く
        if up == 1.0:
            src = os.path.join(work, out + ".png")
        gen = np.asarray(Image.open(src).convert("RGBA"))
        base = Image.open(os.path.join(work, meta["from"] + "_3x.png")).convert("RGBA")
        W, H = base.size
        x0, y0 = meta["box"][0], meta["box"][1]
        manual = JOBS.get(n, {}).get("place")
        if manual:
            # [拡大率, 左, 上]。4 つ書くと [横の拡大率, 縦の拡大率, 左, 上]（描かせた絵の縦横の比が、もとの絵と数 % 違うとき。3 つなら前と同じ）
            if len(manual) == 4:
                s, s2, tx, ty = manual
            else:
                s, tx, ty = manual; s2 = s
            A = np.float32([[s / up, 0, tx], [0, s2 / up, ty]]); info = "手置き"
        else:
            small = np.asarray(Image.open(os.path.join(work, out + ".png")).convert("RGBA"))
            ref = np.asarray(Image.open(os.path.join(work, "_ref_%s.png" % n)).convert("RGB"))
            M, cnt = register(small, ref)
            how = "対応 %d 点" % cnt
            if M is None or cnt < 40:                       # 模様の少ない絵は、点の対応が当てにならない。形と色で探す
                M, v = register_shape(small, ref)
                how = "形で合わせた（一致 %.2f）" % v
                if M is None or v < 0.25:
                    print("%s %s: 見本との対応が取れません（%s）。extras.jobs.%s.place で手で置いてください" % (n, out, how, n)); bad += 1; continue
            # 描かせた絵 → 見本 → 3 倍の絵。見本は、範囲 box を scale 倍したもの
            A = M.astype(np.float64) / meta["scale"]
            A[0, 2] += x0; A[1, 2] += y0
            A[:, :2] /= up
            A = A.astype(np.float32)
            sc = float(np.hypot(M[0, 0], M[1, 0])) / meta["scale"]
            info = "%s  拡大率 %.3f  回転 %.2f°" % (how, sc, np.degrees(np.arctan2(M[1, 0], M[0, 0])))
            if sc > 1.15 and up == 1.0:
                info += "  ※ 引き伸ばして置いています（先に upscale で拡大すると、線がくっきりします）"
        sc_net = float(np.hypot(A[0, 0], A[1, 0]))
        placed = cv2.warpAffine(premult(gen), A, (W, H), flags=cv2.INTER_AREA if sc_net < 0.7 else cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        res = unpremult(np.clip(placed, 0, 255))
        Image.fromarray(res).save(os.path.join(work, out + "_placed.png"))
        # 確認: もとの絵・置いた絵・市松に交互に重ねた絵（ずれていると、ます目の境で線が食い違う）
        ys, xs = np.where(res[..., 3] > 8)
        bx = [max(0, xs.min() - 40), max(0, ys.min() - 40), min(W, xs.max() + 40), min(H, ys.max() + 40)]
        a = on_gray(np.asarray(base.crop(tuple(bx))), 90); b = on_gray(res[bx[1]:bx[3], bx[0]:bx[2]], 90)
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        chk = np.where((((xx // 80) + (yy // 80)) % 2 == 0)[..., None], a, b)
        sheet = np.hstack([a, b, chk])
        im = Image.fromarray(sheet)
        if im.width > 3000:
            im = im.resize((3000, int(im.height * 3000 / im.width)), Image.LANCZOS)
        im.save(os.path.join(work, "_check", "p_%s.png" % n))
        print("%s %s: %s  範囲 %d,%d-%d,%d" % (n, out, info, xs.min(), ys.min(), xs.max(), ys.max()))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
