# 片目を 肌 / 白目 / 瞳 / 上まぶたの線 / 下まぶたの線 / その他の線 に分ける
import sys, os, json, numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
CHAR = json.load(open(os.environ['CHARCFG'], encoding='utf-8')) if os.environ.get('CHARCFG') else {}


def signed_dist(mask):
    m = mask.astype(np.uint8)
    return cv2.distanceTransform(1 - m, cv2.DIST_L2, 5) - cv2.distanceTransform(m, cv2.DIST_L2, 5)


def fill_holes_(m):
    m = m.astype(np.uint8)
    ff = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    ff[1:-1, 1:-1] = m
    cv2.floodFill(ff, None, (0, 0), 2)
    return ff[1:-1, 1:-1] != 2


def largest_(m):
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
    return (lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])) if n > 1 else m.astype(bool)


def process_eye(roi8, excl, hue=tuple(CHAR.get('iris_hue', (268, 336))), circle0=None):
    """roi8: BGR。目尻が左・目頭が右の向き（画面左の目）で渡す。"""
    h, w = roi8.shape[:2]
    roi = roi8.astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    H, Sa, V = hsv_of(roi8)
    coarse = ((~skinlike_mask(roi)) & ~excl).astype(np.uint8) * 255
    coarse = cv2.dilate(cv2.morphologyEx(coarse, cv2.MORPH_CLOSE, ell(31)), ell(15))
    if CHAR.get('eye_fill_holes'):       # 白目の明るい所が肌に似た色でも、目の中の穴として埋める（消し残しのしみを防ぐ）
        ff_ = np.zeros((h + 2, w + 2), np.uint8); ff_[1:-1, 1:-1] = (coarse > 0)
        cv2.floodFill(ff_, None, (0, 0), 2)
        coarse[ff_[1:-1, 1:-1] == 0] = 255
    coarse[excl] = 0
    skin = skin_estimate(roi8, coarse)
    skin = np.where(excl[..., None], roi, skin)
    dark = V < 0.45
    # char.json の eye_line_smin（書かなければ 0.45 = 前と同じ）: 下まぶた・目尻の線（赤みのある線）と見なす、彩度の下限。
    # 線が、彩度の低い、ピンクがかった灰色（例 176,142,150 = 彩度 0.19）の絵柄は、線が「赤い線」に入らず、目の開きの下のふちと、目尻・目頭の端が取れない。
    # 線の彩度より小さく、肌の彩度（例 0.09）より大きい値を書く（例 0.15）
    red = ((H < 20) | (H > 335)) & (Sa > CHAR.get('eye_line_smin', 0.45)) & (V < 0.93)
    core = cv2.morphologyEx(((dark | red) & ~excl & (coarse > 0)).astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
    whitelike = (Sa < 0.22) & (V > 0.6)
    if circle0 is not None:
        # char.json の iris_circle（書かなければ、色で探す = 前と同じ）: {"L": [cx, cy, r], "R": [cx, cy, r]}。瞳の円を、拡大図（grid.py）から読んで、直接置く。
        # 座標は、目の箱と同じ（3 倍の絵の画素。R は、左右を返した絵の座標）。
        # 瞳の候補は「色相の範囲 + 彩度 0.2 超え」で探すので、色味のない灰色の瞳（彩度 0.1 以下）は、見つからない。
        # 灰色の瞳を「彩度が低く、白目より暗く、まつげより明るい所」で探すやり方は、白目の影の所が、いちばん大きい塊になって、外れた（試して、やめた）。
        # 円は、見えている左右のふちと、下のふちに合わせる（瞳孔の位置ではない。まぶたが下りた目は、瞳孔が、円のまん中より下に描かれる）
        cx, cy, r = [float(v_) for v_ in circle0]
        cand = (((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r) & (coarse > 0) & ~excl).astype(np.uint8)      # 目の開きを求める bounds_simple が使う
        info = dict(iris_circle=[cx, cy, r], iris_edge_points=0)
    else:
        # --- 瞳: 色で候補 → 白目との境目で円を合わせる
        cand = ((H > hue[0]) & (H < hue[1]) & (Sa > 0.2) & (V > CHAR.get('iris_vmin', 0.35)) & (coarse > 0) & ~excl).astype(np.uint8)
        cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, ell(7))
        n, lab, st, _ = cv2.connectedComponentsWithStats(cand)
        cand = (lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
        cnts = cv2.findContours(cand, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
        pts = max(cnts, key=cv2.contourArea)[:, 0, :].astype(np.float64)
        r0 = (pts[:, 0].max() - pts[:, 0].min()) / 2
        cx = (pts[:, 0].max() + pts[:, 0].min()) / 2
        cy = pts[:, 1].max() - r0
        bp = []
        for ang in np.deg2rad(np.arange(0, 360, 2)):
            for rr in np.arange(r0 - 12, r0 + 24, 0.5):
                x = int(round(cx + rr * np.cos(ang)))
                y = int(round(cy + rr * np.sin(ang)))
                x2 = int(round(cx + (rr + 2) * np.cos(ang)))
                y2 = int(round(cy + (rr + 2) * np.sin(ang)))
                if not (0 <= x2 < w and 0 <= y2 < h and 0 <= x < w and 0 <= y < h):
                    break
                if whitelike[y, x] and whitelike[y2, x2]:
                    bp.append((cx + rr * np.cos(ang), cy + rr * np.sin(ang), rr))
                    break
        bp = np.array(bp)
        bp = bp[np.abs(bp[:, 2] - np.median(bp[:, 2])) < 6]
        cx, cy, r = fit_circle(bp[:, :2])
        r += 1.5
        info = dict(iris_circle=[float(cx), float(cy), float(r)], iris_edge_points=int(len(bp)))
    circ = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    Vl = V.copy()
    # 瞳に濃い色のふち・瞳孔の線があるキャラ: その濃い画素を「線」にしない（線にすると、視線を動かしたとき取り残される）
    if CHAR.get('iris_dark_hue'):
        rr_ = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        h0, h1 = CHAR['iris_dark_hue']
        navy = (V < 0.5) & (H >= h0) & (H < h1) & (Sa > 0.12) & (rr_ < r + 10)   # ふちの外側は白目と混ざって彩度が低い
        g0, g1 = CHAR.get('iris_rim_hue', (h1, h1))
        rimp = (V < 0.5) & (H >= g0) & (H < g1) & (Sa > 0.12) & (rr_ < r + 8) & (rr_ > r - 16) & (yy > cy - CHAR.get("iris_rim_top", 0.25) * r)
        core = cv2.morphologyEx((core & ~(navy | rimp)).astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
        Vl[navy | rimp] = 1.0          # まつげの下端を探すときも、瞳の濃い線をまつげと見なさない

    def bounds(S, sd):
        """瞳の形 S と符号つき距離 sd から、目の開きの上端・下端を列ごとに求める"""
        line_out = core & ((sd > 6) | (red & (sd > 0) & (V < 0.9)))
        lineD = cv2.dilate(line_out.astype(np.uint8), ell(3)) > 0
        top = np.full(w, -1)
        bot = np.full(w, -1)
        cols = np.where(S.any(0))[0]
        xa, xb = cols.min(), cols.max()
        cxs, rxs = (xa + xb) / 2, (xb - xa) / 2
        for x in range(xa, xb + 1):
            ys = np.where(S[:, x])[0]
            ct, cb = ys.min(), ys.max()
            if abs(x - cxs) < 0.75 * rxs:
                t = int(ct)
                y = int(ct + 0.65 * (cb - ct))
                run = 0
                while y > ct:
                    run = run + 1 if Vl[y, x] < 0.4 else 0
                    if run >= 6:
                        t = y + 6
                        break
                    y -= 1
                top[x] = t
            b = -1
            central = abs(x - cxs) < 0.75 * rxs
            if not central:
                continue          # 瞳のわきの列は、あとで両側から補間する
            for y in range(int(ct + 0.8 * (cb - ct)), min(h, cb + 60)):
                if (red[y, x] and core[y, x] and V[y, x] < 0.9) or (lineD[y, x] and y > cb - 1):
                    b = y
                    break
            bot[x] = b if b >= 0 else cb + 1

        # まつげの下のふちは滑らか。まわりより大きく上へ外れた列は、検出の失敗として直す
        cc = np.where(top >= 0)[0]
        if len(cc) > 20:
            tv = top[cc].astype(np.float32)
            med = cv2.medianBlur(np.tile(tv[None, :], (3, 1)).astype(np.float32), 5)[1]
            k = 31
            pad = np.pad(tv, k // 2, mode="edge")
            med = np.array([np.median(pad[i:i + k]) for i in range(len(tv))])
            bad = tv < med - 10
            tv[bad] = med[bad]
            top[cc] = tv.astype(int)

        def scan(x, ym, lo, hi):
            """列 x で、ym の近く（前の列の開きの範囲 lo..hi の中）から上下の線を探す"""
            col = lineD[:, x]
            if col[ym]:
                free = np.where(~col[lo:hi + 1])[0] + lo
                if not len(free):
                    return None
                ym = int(free[np.argmin(np.abs(free - ym))])
                # 空きの並びの少し内側へ
                if ym + 4 <= hi and not col[min(h - 1, ym + 4)]:
                    ym += 4
                elif ym - 4 >= lo and not col[ym - 4]:
                    ym -= 4
            u = np.where(col[:ym])[0]
            dn = np.where(col[ym:])[0]
            t = u[-1] + 1 if (len(u) and ym - u[-1] < 110) else -1
            bb = ym + dn[0] if (len(dn) and dn[0] < 110) else -1
            return t, bb

        for step in (1, -1):
            last = int(cxs + step * 0.74 * rxs)
            x = int(cxs + step * (rxs + 4))
            ym = int(cy + 0.35 * r)
            skip = 0
            miss = []
            xe0 = int(cxs + step * 0.74 * rxs)
            lo, hi = int(top[xe0]) + 2, int(bot[xe0]) - 2
            while 0 <= x < w:
                res = scan(x, ym, lo, hi)
                if res is None:
                    skip += 1
                    x += step
                    if skip > 14:
                        break
                    continue
                skip = 0
                t, bb = res
                if t < 0:
                    break
                top[x] = t
                if bb >= 0:
                    bot[x] = bb
                    last = x
                    miss = []
                    ym = int((t + bb) / 2)
                    lo, hi = t + 1, bb - 1
                else:
                    miss.append(x)
                    ym = t + 5
                    lo, hi = t + 1, max(hi, t + 12)
                x += step
            if miss:
                xe = miss[-1]
                y0 = bot[last]
                y1 = top[xe] + 2
                for xm in miss:
                    bot[xm] = int(y0 + (y1 - y0) * (xm - last) / (xe - last))
        okt = np.where(top >= 0)[0]
        x_l, x_r = int(okt.min()), int(okt.max())
        for arr in (top, bot):
            ok = np.where(arr >= 0)[0]
            ok = ok[(ok >= x_l) & (ok <= x_r)]
            arr[x_l:x_r + 1] = np.interp(np.arange(x_l, x_r + 1), ok, arr[ok]).astype(int)
        W = np.zeros((h, w), bool)
        for x in range(x_l, x_r + 1):
            if bot[x] > top[x]:
                W[top[x]:bot[x], x] = True
        W = cv2.morphologyEx(W.astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
        return top, bot, W, line_out, lineD, x_l, x_r

    def bounds_simple(S, sd):
        """目の開きを「白目の白 + 瞳の色 + 瞳の中の濃い線」をつないだ形として求める（char.json の eye_open_simple）。
        瞳に太い黒のふち・瞳孔の輪があるキャラ、白目が縦に大きいキャラでは、上の bounds（瞳から外へ線を探す）が、
        瞳の中の線をまつげと見なしたり、白目の端まで届かなかったりする。使うのは白目の左右の端と下端だけなので、粗くてよい"""
        eo = CHAR['eye_open_simple'] if isinstance(CHAR['eye_open_simple'], dict) else {}
        strict = (Sa < eo.get('white_smax', 0.10)) & (V > eo.get('white_vmin', 0.7)) & ~excl      # 白目の白（肌は彩度で外れる）と、瞳の中の光
        M = cv2.morphologyEx((strict | (cand > 0)).astype(np.uint8), cv2.MORPH_OPEN, ell(5))
        M = cv2.morphologyEx(M, cv2.MORPH_CLOSE, ell(eo.get('close', 31))) > 0                   # 瞳のふち・瞳孔の輪をまたいでつなぐ
        M |= dark & circ & (yy > cy)                                                             # 瞳の下半分のふち（下まぶたの線の内側）
        M = fill_holes_(largest_(cv2.morphologyEx(M.astype(np.uint8), cv2.MORPH_OPEN, ell(5)) > 0))
        line_out = core & ~M & ((sd > 6) | (red & (sd > 0) & (V < 0.9)))
        lineD = cv2.dilate(line_out.astype(np.uint8), ell(3)) > 0
        cols = np.where(M.any(0))[0]
        x_l, x_r = int(cols.min()), int(cols.max())
        top = np.full(w, -1); bot = np.full(w, -1)
        for x in range(x_l, x_r + 1):
            ys = np.where(M[:, x])[0]
            if len(ys):
                top[x], bot[x] = ys.min(), ys.max() + 1
        for arr in (top, bot):
            ok = np.where(arr >= 0)[0]
            arr[x_l:x_r + 1] = np.interp(np.arange(x_l, x_r + 1), ok, arr[ok]).astype(int)
        return top, bot, M, line_out, lineD, x_l, x_r

    if CHAR.get('eye_open_simple'):
        bounds = bounds_simple
    # 1 回目: 円で目の開きを求める → 見えている瞳の実際の形を取る → 2 回目
    sd1 = signed_dist(circ)
    top, bot, W, line_out, lineD, x_l, x_r = bounds(circ, sd1)
    vis = cv2.dilate(W.astype(np.uint8), ell(5)).astype(bool) & ~whitelike & (sd1 < 16) & ~(red & core) & (yy < bot[None, :] + 2)
    vis = cv2.morphologyEx(vis.astype(np.uint8), cv2.MORPH_OPEN, ell(5))
    n, lab, st, _ = cv2.connectedComponentsWithStats(vis)
    if n > 1:
        vis = lab == lab[int(cy + 0.4 * r), int(cx)] if lab[int(cy + 0.4 * r), int(cx)] > 0 else lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
    S = vis.astype(bool) | circ
    S = cv2.morphologyEx(S.astype(np.uint8), cv2.MORPH_CLOSE, ell(27))
    S = cv2.morphologyEx(S, cv2.MORPH_OPEN, ell(7))
    ff = S.copy()
    cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 2)
    S = (S > 0) | (ff == 0)
    sd = signed_dist(S)
    top, bot, W, line_out, lineD, x_l, x_r = bounds(S, sd)
    info.update(eye_cols=[x_l, x_r])
    # --- 瞳の層: 隠れた部分は極座標で輪をつなぐ
    iris_known = cv2.erode((S & W & ~lineD).astype(np.uint8), ell(5)) > 0
    R = int(np.sqrt(((xx - cx) ** 2 + (yy - cy) ** 2)[S].max())) + 3
    NA = 720
    pol = cv2.warpPolar(roi8, (R, NA), (cx, cy), R, cv2.WARP_POLAR_LINEAR | cv2.INTER_LINEAR).astype(np.float32)
    kp = cv2.warpPolar(iris_known.astype(np.uint8) * 255, (R, NA), (cx, cy), R,
                       cv2.WARP_POLAR_LINEAR | cv2.INTER_NEAREST) > 127
    ang = np.arange(NA)
    for j in range(R - 1, -1, -1):
        k = kp[:, j]
        if k.sum() < 8:
            if j < R - 1:
                pol[:, j] = pol[:, j + 1]
            continue
        ka = ang[k]
        for c in range(3):
            v = pol[k, j, c]
            pol[:, j, c] = np.interp(ang, np.r_[ka - NA, ka, ka + NA], np.r_[v, v, v])
    pol = cv2.GaussianBlur(pol, (0, 0), sigmaX=0.6, sigmaY=3)
    back = cv2.warpPolar(pol.astype(np.uint8), (w, h), (cx, cy), R,
                         cv2.WARP_POLAR_LINEAR | cv2.WARP_INVERSE_MAP | cv2.INTER_LINEAR).astype(np.float32)
    km = soft(iris_known, 1.2)[..., None]
    iris_rgb = roi * km + back * (1 - km)
    iris_a = soft(S, 0.9)
    # --- 白目の層: 行ごとに左右の白目の色をつないで瞳の下を塗る
    wk = W & (sd >= 3) & ~(cv2.dilate(line_out.astype(np.uint8), ell(5)) > 0)
    wk = cv2.erode(wk.astype(np.uint8), ell(3)) > 0
    fill = roi.copy()
    got = wk.copy()
    for y in range(h):
        k = np.where(wk[y])[0]
        if len(k) >= 2:
            for c in range(3):
                fill[y, :, c] = np.interp(np.arange(w), k, roi[y, k, c])
            got[y, :] = True
    fill8 = cv2.inpaint(np.clip(fill, 0, 255).astype(np.uint8), (~got).astype(np.uint8) * 255, 5,
                        cv2.INPAINT_TELEA).astype(np.float32)
    fill8 = cv2.GaussianBlur(fill8, (0, 0), 2.0)
    wa = soft(wk, 1.0)[..., None]
    white_rgb = roi * wa + fill8 * (1 - wa)
    coreD = cv2.dilate(core.astype(np.uint8), ell(3)) > 0
    Wext = (cv2.dilate(W.astype(np.uint8), ell(25)) > 0) & (W | coreD | S)
    Wext = cv2.morphologyEx(Wext.astype(np.uint8), cv2.MORPH_OPEN, ell(5)) > 0
    white_a = soft(Wext, 1.0)
    # --- 線の層: 下の色から分ける
    under = over(skin, white_rgb, white_a)
    under = over(under, iris_rgb, iris_a * white_a)
    linecore = core & ~(S & W) & ((sd > 6) | ~W)
    region = (cv2.dilate(coarse, ell(9)) > 0) & ~excl
    F, a = unmix(roi, under, linecore)
    a = a * region
    # 瞳のふちの残りかす（白目の中、瞳の輪郭のすぐ外）は線にしない
    a[(sd > -4) & (sd < 10) & W & ~lineD] = 0
    # 上・下・その他に分ける。目尻より外は斜め 45°で分ける
    mid = np.zeros(w)
    mid[x_l:x_r + 1] = (top[x_l:x_r + 1] + bot[x_l:x_r + 1]) / 2
    mid[:x_l] = mid[x_l] + (x_l - np.arange(x_l)) * 1.0
    mid[x_r + 1:] = bot[x_r] + 3
    lower = yy > mid[None, :]
    solid = (a > 0.3).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(solid, ell(5)))
    ids, cnt = np.unique(lab[(lab > 0) & ~lower], return_counts=True)
    main = ids[np.argmax(cnt)]
    m_main = (lab == main) & ~lower
    near = cv2.dilate(m_main.astype(np.uint8), ell(17)) > 0
    m_lower = lower & (a > 0)
    m_upper = (~lower) & (a > 0) & near
    m_other = (a > 0) & ~m_lower & ~m_upper
    layers = dict(skin=(skin, np.ones((h, w), np.float32)), white=(white_rgb, white_a), iris=(iris_rgb, iris_a),
                  lash_upper=(F, a * m_upper), lash_lower=(F, a * m_lower), crease=(F, a * m_other))
    info.update(top=top.tolist(), bot=bot.tolist())
    dbg = np.zeros((h, w, 3), np.uint8)
    dbg[W] = (255, 255, 255)
    dbg[S & W] = (255, 0, 255)
    dbg[S & ~W] = (120, 0, 120)
    dbg[line_out] = (0, 0, 255)
    dbg[wk] = (255, 255, 0)
    info["_dbg"] = np.hstack([roi8, dbg])
    return layers, info


def compose(L, dx=0, dy=0):
    h, w = L["skin"][0].shape[:2]
    o = over(L["skin"][0].copy(), *L["white"])
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    o = over(o, cv2.warpAffine(L["iris"][0], M, (w, h)), cv2.warpAffine(L["iris"][1], M, (w, h)) * L["white"][1])
    for k in ("crease", "lash_lower", "lash_upper"):
        o = over(o, *L[k])
    return o


if __name__ == "__main__":
    # 右目(R)は左右反転した画像の座標で box と poly を渡す
    src, outdir, side = sys.argv[1], sys.argv[2], sys.argv[3]
    X0, Y0, X1, Y1 = [int(v) for v in sys.argv[4:8]]
    poly = json.loads(sys.argv[8]) if len(sys.argv) > 8 else []
    img = cv2.imread(src, cv2.IMREAD_UNCHANGED)
    flip = side == "R"
    if flip:
        img = img[:, ::-1]
    roi8 = img[Y0:Y1, X0:X1, :3].copy()
    excl = img[Y0:Y1, X0:X1, 3] < 250
    # 折れ線は 1 本でも複数でもよい（box の左上を原点にした座標）
    polys = poly if (poly and isinstance(poly[0][0], list)) else ([poly] if poly else [])
    for pl in polys:
        m = np.zeros(excl.shape, np.uint8)
        cv2.fillPoly(m, [np.array(pl, np.int32)], 1)
        excl |= m > 0
    ic_ = (CHAR.get('iris_circle') or {}).get(side)
    L, info = process_eye(roi8, excl, circle0=[ic_[0] - X0, ic_[1] - Y0, ic_[2]] if ic_ else None)
    roi = roi8.astype(np.float32)
    d_ = info.pop('_dbg')
    cv2.imwrite(outdir + '/eye%s_dbg.png' % side, cv2.resize(d_[:, d_.shape[1] // 2:], None, fx=2.5, fy=2.5, interpolation=cv2.INTER_NEAREST))   # 白=目の開き 桃=瞳 赤=線 水色=白目の確かな所
    cv2.imwrite(outdir + '/eye%s_mask.png' % side, cv2.resize(d_[100:320, 180:540].repeat(1,0), None, fx=1, fy=1))
    cv2.imwrite(outdir + '/eye%s_mask2.png' % side, cv2.resize(np.hstack([d_[130:310, 200:330], d_[130:310, 580+200:580+330]]), None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    c0 = compose(L)
    diff = np.abs(c0 - roi).max(-1)[~excl]
    info.update(recompose_mean=float(diff.mean()), recompose_over30_pct=float((diff > 30).mean() * 100))
    r = info["iris_circle"][2]
    rows = [np.hstack([label(roi, "original"), label(c0, "recomposed"), label(onbg(*L["white"]), "white")]),
            np.hstack([label(onbg(*L["iris"]), "iris"), label(onbg(*L["lash_upper"]), "lash upper"),
                       label(onbg(*L["lash_lower"]), "lash lower")]),
            np.hstack([label(onbg(*L["crease"]), "others"), label(compose(L, -0.3 * r, 0), "gaze -"),
                       label(compose(L, 0.3 * r, 0.1 * r), "gaze +")])]
    cv2.imwrite(outdir + "/eye%s_sheet.png" % side, np.vstack(rows))
    Wd = img.shape[1]
    for k, (rgb, a) in L.items():
        im = rgba(rgb, a)
        if flip:
            im = im[:, ::-1]
        cv2.imwrite(outdir + "/eye%s_%s.png" % (side, k), im)
    box = [Wd - X1, Y0, Wd - X0, Y1] if flip else [X0, Y0, X1, Y1]
    info.update(box=box, flipped=flip)
    json.dump(info, open(outdir + "/eye%s.json" % side, "w"))
    print(side, "iris", [round(v, 1) for v in info["iris_circle"]], "edge pts", info["iris_edge_points"], "cols",
          info["eye_cols"], "recompose mean %.2f over30 %.2f%%" % (info["recompose_mean"], info["recompose_over30_pct"]))
