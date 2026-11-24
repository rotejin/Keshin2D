# 基準画像 2 枚（髪あり B・髪なし N）から全パーツを切り出す
#   python build.py <base3x.png> <nohair3x.png> <eye の出力フォルダ> <出力フォルダ>
import sys, os, json, numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

CFG = dict(
    seed_head=(1536, 1150), seed_neck=(1420, 2200),
    brow_L=[990, 1255, 1440, 1375], brow_R=[1630, 1255, 2080, 1375],
    nose=[1484, 1690, 1591, 1830], mouth=[1400, 1890, 1680, 1990],
)

# キャラごとの値は設定ファイル（環境変数 CHARCFG）で上書きする
CHAR = json.load(open(os.environ['CHARCFG'], encoding='utf-8')) if os.environ.get('CHARCFG') else {}
CFG.update(CHAR.get('build', {}))
EAR_YMAX = CHAR.get('ear_ymax', 2050)


def fill_holes(m):
    m = m.astype(np.uint8)
    h, w = m.shape
    ff = np.zeros((h + 2, w + 2), np.uint8)
    ff[1:-1, 1:-1] = m
    cv2.floodFill(ff, None, (0, 0), 2)
    return (ff[1:-1, 1:-1] != 2)


def flood(mask, seed):
    m = mask.astype(np.uint8).copy()
    assert m[seed[1], seed[0]] == 1, "seed is not inside the mask: %s" % (seed,)
    cv2.floodFill(m, None, seed, 2)
    return m == 2


def extend_nearest(rgb, mask, grow, blur=3.0):
    """grow の範囲を、mask 内のいちばん近い画素の色で埋める（隠れる部分の塗り足し）"""
    src = mask.astype(np.uint8)
    dist, lab = cv2.distanceTransformWithLabels(1 - src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.where(src > 0)
    lut = np.zeros((lab.max() + 1, 2), np.int32)
    lut[lab[ys, xs]] = np.c_[ys, xs]
    out = rgb.copy()
    g = grow & ~mask
    gy, gx = np.where(g)
    ll = lab[gy, gx]
    out[gy, gx] = rgb[lut[ll, 0], lut[ll, 1]]
    if blur > 0:
        b = cv2.GaussianBlur(out, (0, 0), blur)
        out[g] = b[g]
    return out


def unmix_safe(p, U, core, band=6, minmag=6):
    if core.sum() < 10:
        diff = p - U
        pos = np.where(diff > 0, diff / np.maximum(255 - U, 1), -diff / np.maximum(U, 1))
        a = np.clip(pos.max(-1), 0, 1)
        a[np.abs(diff).max(-1) < minmag] = 0
        return np.clip(U + diff / np.maximum(a, 1e-3)[..., None], 0, 255), a
    return unmix(p, U, core, band, minmag)


def feature(Nrgb, box, hue=None):
    x0, y0, x1, y1 = box
    roi8 = Nrgb[y0:y1, x0:x1].copy()
    roi = roi8.astype(np.float32)
    H, Sa, V = hsv_of(roi8)
    coarse = (~skinlike_mask(roi)).astype(np.uint8) * 255
    if hue:      # [色相の下限, 上限, 彩度の下限]。肌と色相が違う薄い線（眉尻など）も拾う。拾わないと頭に消し残る
        coarse[(H > hue[0]) & (H < hue[1]) & (Sa > hue[2])] = 255
    coarse = cv2.dilate(cv2.morphologyEx(coarse, cv2.MORPH_CLOSE, ell(15)), ell(CHAR.get('feature_grow', 9)))   # 線のふちの、肌と混ざった薄い画素まで消す幅
    coarse[:3] = 0; coarse[-3:] = 0; coarse[:, :3] = 0; coarse[:, -3:] = 0
    skin = skin_estimate(roi8, coarse)
    core = ((V < 0.6) | (Sa > 0.4)) & (coarse > 0)
    core = cv2.morphologyEx(core.astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
    F, a = unmix_safe(roi, skin, core)
    a = a * (cv2.dilate(coarse, ell(5)) > 0)
    return skin, F, a


def main():
    fB, fN, eyedir, out = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    B = cv2.imread(fB, cv2.IMREAD_UNCHANGED)
    N = cv2.imread(fN, cv2.IMREAD_UNCHANGED)
    Hh, Ww = N.shape[:2]
    Nrgb8 = N[..., :3].copy()
    Nrgb = Nrgb8.astype(np.float32)
    aN = N[..., 3].astype(np.float32) / 255
    Brgb = B[..., :3].astype(np.float32)
    aB = B[..., 3].astype(np.float32) / 255
    yy, xx = np.mgrid[0:Hh, 0:Ww]
    layers = {}          # name -> (rgb float, alpha float)   全キャンバス
    notes = {}

    # ---------- 1. 髪なし画像を 頭 / 耳 / 首 / 体 に分ける
    b_, g_, r_ = Nrgb[..., 0], Nrgb[..., 1], Nrgb[..., 2]
    # ゆるい肌の条件（首・耳）。服が白〜クリーム色のキャラは、服が肌に入るので、赤と緑の差の下限を上げる（char.json の tone_rg_min）
    toneL = (r_ > 200) & (g_ > 125) & (b_ > 130) & (r_ - g_ > CHAR.get('tone_rg_min', 8)) & (aN > 0.9)
    # 頭の塗りつぶしだけ、緑の下限を上げられる（輪郭線が薄いキャラは、線が肌の条件を通って耳とつながる）
    tone = toneL & (g_ > CHAR.get('tone_head_gmin', 125))
    if CHAR.get('tone_head_white'):      # 輪郭線の内側の白いハイライトも頭の肌に含める（含めないと、その外の輪郭線が頭から外れる）
        tone |= (r_ > 240) & (g_ > 228) & (b_ > 228) & (aN > 0.9)
    H0 = flood(tone, CFG["seed_head"])
    dH = cv2.distanceTransform((~H0).astype(np.uint8), cv2.DIST_L2, 5)
    Hc = cv2.morphologyEx(H0.astype(np.uint8), cv2.MORPH_CLOSE, ell(81)) > 0
    head = fill_holes(H0 | (~tone & (dH <= 7) & (aN > 0.05)) | (Hc & ~tone & (aN > 0.05)))
    K0 = flood(toneL & ~head, CFG["seed_neck"])
    cloth = cv2.morphologyEx((~toneL & (aN > 0.5) & ~head).astype(np.uint8), cv2.MORPH_OPEN, ell(15))
    n, lab, st, _ = cv2.connectedComponentsWithStats(cloth)
    cloth = lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
    kc = np.where(K0.any(0))[0]
    neck = np.zeros((Hh, Ww), bool)
    for x in range(kc.min() - 12, kc.max() + 13):
        hb = np.where(head[:, x])[0]
        if not len(hb):
            continue
        cl = np.where(cloth[hb.max():, x])[0]
        if len(cl):
            neck[hb.max() + 1:hb.max() + cl[0], x] = True
    neck &= aN > 0.05
    E0 = toneL & ~head & ~K0 & (yy < EAR_YMAX)
    n, lab, st, _ = cv2.connectedComponentsWithStats(E0.astype(np.uint8))
    ears = np.zeros((Hh, Ww), bool)
    ear_n = 0
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] > 5000:
            ears |= lab == i
            ear_n += 1
    dE = cv2.distanceTransform((~ears).astype(np.uint8), cv2.DIST_L2, 5)
    ears = fill_holes(ears | (~toneL & (dE <= 7) & ~head & (aN > 0.05) & (yy < EAR_YMAX)))
    ears &= ~head
    body = (aN > 0.02) & ~head & ~ears & ~neck
    # 体は首より下にあるはず。上に残った切れ端は除く
    n, lab, st, _ = cv2.connectedComponentsWithStats(body.astype(np.uint8))
    body = lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
    notes["regions_px"] = dict(head=int(head.sum()), neck=int(neck.sum()), ears=int(ears.sum()), ear_count=ear_n,
                               body=int(body.sum()))

    # ---------- 2. 顔のパーツ
    head_rgb = Nrgb.copy()
    for side in ("L", "R"):
        info = json.load(open(os.path.join(eyedir, "eye%s.json" % side)))
        x0, y0, x1, y1 = info["box"]
        for k, name in (("white", "20_eye_white"), ("iris", "21_iris"), ("lash_upper", "22_lash_upper"),
                        ("lash_lower", "23_lash_lower"), ("crease", "24_eyelid_crease")):
            im = cv2.imread(os.path.join(eyedir, "eye%s_%s.png" % (side, k)), cv2.IMREAD_UNCHANGED)
            rgb = np.zeros((Hh, Ww, 3), np.float32)
            a = np.zeros((Hh, Ww), np.float32)
            rgb[y0:y1, x0:x1] = im[..., :3]
            a[y0:y1, x0:x1] = im[..., 3].astype(np.float32) / 255
            layers["%s_%s" % (name, side)] = (rgb, a)
        sk = cv2.imread(os.path.join(eyedir, "eye%s_skin.png" % side), cv2.IMREAD_UNCHANGED)
        head_rgb[y0:y1, x0:x1] = sk[..., :3]
        notes["eye_" + side] = dict(box=info["box"], iris_circle_in_box=info["iris_circle"])
    for key, name in (("brow_L", "13_brow_L"), ("brow_R", "13_brow_R"), ("nose", "12_nose"), ("mouth", "14_mouth_line")):
        x0, y0, x1, y1 = CFG[key]
        skin, F, a = feature(Nrgb8, CFG[key], CHAR.get('brow_hue') if key.startswith('brow') else None)
        head_rgb[y0:y1, x0:x1] = skin
        rgb = np.zeros((Hh, Ww, 3), np.float32)
        al = np.zeros((Hh, Ww), np.float32)
        rgb[y0:y1, x0:x1] = F
        al[y0:y1, x0:x1] = a
        layers[name] = (rgb, al)
    # 目の箱の中に残った、まつげの先の黒い点を埋める（輪郭線を外す折れ線の中に入ったぶん）
    if CHAR.get('head_dark_fix'):
        for side in ("L", "R"):
            x0, y0, x1, y1 = notes["eye_" + side]["box"]
            sub = np.clip(head_rgb[y0:y1, x0:x1], 0, 255).astype(np.uint8)
            dk = cv2.dilate(((sub.max(-1) < 255 * CHAR['head_dark_fix']) & head[y0:y1, x0:x1]).astype(np.uint8), ell(7))
            head_rgb[y0:y1, x0:x1] = cv2.inpaint(sub, dk * 255, 5, cv2.INPAINT_TELEA)
    # 唇の塗り（口の線の下の淡い色とハイライト）を頭から外して、口と一緒に動くレイヤーにする
    if CHAR.get('lip'):
        x0, y0, x1, y1 = CFG["mouth"]
        y1 = y1 + int(CHAR['lip'].get('down', 40))
        ml = layers["14_mouth_line"][1][y0:y1, x0:x1]
        ly = int(np.median(np.where(ml > 0.5)[0]))
        sub = np.clip(head_rgb[y0:y1, x0:x1], 0, 255).astype(np.uint8)
        mk = np.zeros(sub.shape[:2], np.uint8)
        mk[max(4, ly - 14):-10, 24:-24] = 255
        est = skin_estimate(sub, mk, k=4, rad=9)
        Fl, al = unmix_safe(sub.astype(np.float32), est, np.zeros(mk.shape, bool), minmag=4)
        al = al * (mk > 0)
        rgb = np.zeros((Hh, Ww, 3), np.float32); a_ = np.zeros((Hh, Ww), np.float32)
        rgb[y0:y1, x0:x1] = Fl; a_[y0:y1, x0:x1] = al
        layers["17_lip"] = (rgb, a_)
        head_rgb[y0:y1, x0:x1] = est
    head_a = soft(head, 0.8) * aN
    head_a[cv2.erode(head.astype(np.uint8), ell(5)) > 0] = 1
    layers["10_head"] = (head_rgb, head_a)

    # ---------- 3. 耳（頭の下へ塗り足す）
    grow = (cv2.dilate(ears.astype(np.uint8), ell(61)) > 0) & head
    ear_rgb = extend_nearest(Nrgb, ears, grow)
    layers["11_ears"] = (ear_rgb, np.maximum(soft(ears, 0.8) * aN, soft(grow, 1.0)))

    # ---------- 4. 首（あごの下と襟の下へ塗り足す）
    cols = np.where(K0.any(0))[0]
    nx0, nx1 = cols.min() - 10, cols.max() + 10
    ys = np.where(neck.any(1))[0]
    ny0, ny1 = ys.min(), ys.max()
    up = (xx >= nx0) & (xx <= nx1) & (yy >= ny0 - 150) & (yy <= ny1) & head
    dn = (xx >= nx0) & (xx <= nx1) & (yy > ny0) & (yy <= ny1 + 60) & body
    growk = (up | dn) & ~neck
    neck_rgb = Nrgb.copy()
    # 列ごとに、見えている首の上端・下端の色を縦に延ばす
    for x in range(max(0, nx0), min(Ww, nx1 + 1)):
        col = np.where(neck[:, x])[0]
        if not len(col):
            continue
        t, b = col.min(), col.max()
        neck_rgb[ny0 - 150:t, x] = Nrgb[min(t + 5, b), x]
        neck_rgb[b + 1:ny1 + 61, x] = Nrgb[max(b - 5, t), x]
    colmask = np.zeros((Hh, Ww), bool)
    colmask[:, max(0, nx0):nx1 + 1] = neck.any(0)[None, max(0, nx0):nx1 + 1]
    growk &= colmask
    blur = cv2.GaussianBlur(neck_rgb, (0, 0), sigmaX=0.8, sigmaY=4)
    neck_rgb[growk] = blur[growk]
    layers["40_neck"] = (neck_rgb, np.maximum(soft(neck, 0.8) * aN, soft(growk, 1.0)))

    # ---------- 5. 体
    body_a = soft(body, 0.8) * aN
    body_a[cv2.erode(body.astype(np.uint8), ell(5)) > 0] = aN[cv2.erode(body.astype(np.uint8), ell(5)) > 0]
    layers["41_body"] = (Nrgb.copy(), body_a)

    # ---------- 6. 髪（髪あり − 髪なし）
    if CHAR.get('skip_hair_diff'):
        empty = (np.zeros((Hh, Ww, 3), np.float32), np.zeros((Hh, Ww), np.float32))
        for nm in ('30_hair_front', '31_hair_side', '32_hair_back', '34_ribbons'):
            layers[nm] = empty
        rib_n = 0
    else:
        diff = np.abs(Brgb - Nrgb).max(-1)
        hm = (aB > 0.05) & ((aN < 0.5) | (diff > 20))
        hm = cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
        # 髪なし画像の輪郭線が少し違うだけの細い線は髪にしない（太い髪の近くか、ピンク色の所だけ残す）
        Hc_, Sc_, Vc_ = hsv_of(B[..., :3].copy())
        thick = cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, ell(11))
        near_thick = cv2.dilate(thick, ell(25)) > 0
        pinkish = (Hc_ > 290) & (Hc_ < 355) & (Sc_ > 0.25) & (Vc_ > 0.3)
        darkline = (Vc_ < 0.45) & near_thick
        # 髪の色（ピンク）か、髪のそばの濃い線だけを髪にする。肌色で上書きしているだけの所は髪にしない
        hm = hm & (pinkish | darkline | (aN < 0.5))
        hm = cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
        # 髪に囲まれた小さな穴（肌と似た色のハイライトなど）は髪に含める
        holes = fill_holes(hm) & ~hm & (aB > 0.5)
        n, lab, st, _ = cv2.connectedComponentsWithStats(holes.astype(np.uint8))
        small = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] < 20000])
        forced = small & (aN > 0.5)
        hm |= small
        ys, xs = np.where(hm)
        hy0, hy1, hx0, hx1 = max(0, ys.min() - 10), min(Hh, ys.max() + 10), max(0, xs.min() - 10), min(Ww, xs.max() + 10)
        sl = (slice(hy0, hy1), slice(hx0, hx1))
        F, a = unmix(Brgb[sl], Nrgb[sl], hm[sl], band=5, minmag=8)
        inN = aN[sl] > 0.98
        near = cv2.dilate((hm & (aN > 0.98))[sl].astype(np.uint8), ell(5)) > 0
        hair_a = np.zeros((Hh, Ww), np.float32)
        hair_rgb = Brgb.copy()
        hair_a[sl] = np.where(inN, a * near, np.where(hm[sl], aB[sl], aB[sl] * (1 - aN[sl])))
        hair_rgb[sl] = np.where(inN[..., None], F, Brgb[sl])
        hair_rgb[forced] = Brgb[forced]
        hair_a[forced] = 1
        # リボン: 上の方にある、黒っぽい大きな塊
        Hc, Sc, Vc = Hc_, Sc_, Vc_
        blk = (hair_a > 0.5) & (Vc < 0.42) & (Sc < 0.45) & (yy < 1300)
        blk = cv2.morphologyEx(blk.astype(np.uint8), cv2.MORPH_OPEN, ell(9))
        n, lab, st, _ = cv2.connectedComponentsWithStats(blk)
        rib = np.zeros((Hh, Ww), bool)
        rib_n = 0
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] > 6000:
                rib |= lab == i
        # 同じリボンの左右の羽と留め具をひとまとめにする
        rib = fill_holes(cv2.morphologyEx(rib.astype(np.uint8), cv2.MORPH_CLOSE, ell(141)))
        rib_n = cv2.connectedComponents(rib.astype(np.uint8))[0] - 1
        rib = (cv2.dilate(rib.astype(np.uint8), ell(11)) > 0) & (hair_a > 0)
        pink = (Hc > 295) & (Hc < 350) & (Sc > 0.35) & (Vc > 0.5)
        rib &= ~(cv2.morphologyEx(pink.astype(np.uint8), cv2.MORPH_OPEN, ell(5)) > 0)
        rib = cv2.morphologyEx(rib.astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
        notes["ribbon_count"] = rib_n
        rib_s = soft(rib, 0.8)
        layers["34_ribbons"] = (hair_rgb.copy(), hair_a * rib_s)
        pink_a = hair_a * (1 - rib_s)
        over_face = head | ears | neck
        over_body = body & ~over_face
        inside = aN > 0.5
        # 体の輪郭のふち（半透明の帯）に見えている髪は、手前の髪のすぐ近くでなければ後ろ髪
        front_solid = cv2.dilate((hm & (aN > 0.98)).astype(np.uint8), ell(9)) > 0
        back_m = (~inside) | ((aN < 0.98) & ~front_solid)
        front_m = ~back_m & ~over_body
        side_m = ~back_m & over_body
        def drop_small(a, amin=800):
            n, lab, st, _ = cv2.connectedComponentsWithStats((a > 0.15).astype(np.uint8))
            keep = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= amin])
            return a * (cv2.dilate(keep.astype(np.uint8), ell(5)) > 0)
        layers["30_hair_front"] = (hair_rgb.copy(), drop_small(pink_a * front_m))
        layers["31_hair_side"] = (hair_rgb.copy(), drop_small(pink_a * side_m))
        # 後ろ髪: 体の輪郭の外に見えている髪 + 頭と体の裏側への塗り足し
        back_vis = (pink_a > 0.5) & back_m
        back_vis = cv2.morphologyEx(back_vis.astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
        back_vis &= ~(cv2.dilate(rib.astype(np.uint8), ell(9)) > 0)
        growb = inside & (cv2.dilate(back_vis.astype(np.uint8), ell(301)) > 0)
        back_rgb = extend_nearest(hair_rgb, back_vis, growb, blur=6.0)
        edgefill = (cv2.dilate(growb.astype(np.uint8), ell(9)) > 0) & (cv2.dilate(back_vis.astype(np.uint8), ell(9)) > 0)
        back_rgb = extend_nearest(back_rgb, back_vis | growb, edgefill, blur=0)
        back_a = np.maximum(pink_a * back_m, soft(growb | edgefill, 1.0))
        # リボンの下にも髪を塗り足す
        growr = rib & ~inside
        srcb = (back_vis | growb) & ~(cv2.dilate(rib.astype(np.uint8), ell(31)) > 0)
        growr = (cv2.dilate(rib.astype(np.uint8), ell(31)) > 0) & ~inside & (hair_a > 0.5)
        back_rgb = extend_nearest(back_rgb, srcb, growr, blur=4.0)
        back_a = np.maximum(back_a, soft(growr, 1.0) * (hair_a > 0))
        layers["32_hair_back"] = (back_rgb, back_a)

    # ---------- 7. 口の中・舌（元絵に無いので図形で作った仮のもの）
    ma = layers["14_mouth_line"][1]
    ys, xs = np.where(ma > 0.5)
    mcx, mcy, mw = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2, xs.max() - xs.min()
    e = ((xx - mcx) / (mw * 0.62)) ** 2 + ((yy - (mcy + mw * 0.18)) / (mw * 0.42)) ** 2
    ia = np.clip((1 - e) * 12, 0, 1).astype(np.float32)
    g = np.clip((yy - (mcy - mw * 0.25)) / (mw * 0.85), 0, 1)[..., None]
    irgb = (np.array([70, 40, 110], np.float32) * (1 - g) + np.array([95, 60, 165], np.float32) * g)
    layers["15_mouth_inside"] = (irgb.astype(np.float32), ia)
    e2 = ((xx - mcx) / (mw * 0.38)) ** 2 + ((yy - (mcy + mw * 0.42)) / (mw * 0.22)) ** 2
    ta = np.clip((1 - e2) * 10, 0, 1).astype(np.float32)
    trgb = np.empty((Hh, Ww, 3), np.float32)
    trgb[:] = (150, 125, 240)
    layers["16_tongue"] = (trgb, ta)
    notes["mouth"] = dict(center=[float(mcx), float(mcy)], width=float(mw))

    # ---------- 書き出し
    order = ["32_hair_back", "40_neck", "41_body", "11_ears", "10_head",
             "20_eye_white_L", "21_iris_L", "20_eye_white_R", "21_iris_R",
             "24_eyelid_crease_L", "24_eyelid_crease_R", "23_lash_lower_L", "23_lash_lower_R",
             "22_lash_upper_L", "22_lash_upper_R", "12_nose", "15_mouth_inside", "16_tongue"] + (["17_lip"] if "17_lip" in layers else []) + ["14_mouth_line",
             "13_brow_L", "13_brow_R", "31_hair_side", "30_hair_front", "34_ribbons"]
    hidden = {"15_mouth_inside", "16_tongue"}
    clip = {"21_iris_L": "20_eye_white_L", "21_iris_R": "20_eye_white_R"}
    man = dict(canvas=[Ww, Hh], order=order, hidden=sorted(hidden), clip=clip, layers={}, notes=notes)
    comp = np.zeros((Hh, Ww, 3), np.float32)
    ca = np.zeros((Hh, Ww), np.float32)
    for name in order:
        rgb, a = layers[name]
        a = np.clip(a, 0, 1).astype(np.float32)
        ys, xs = np.where(a > 0.004)
        if not len(ys):
            man["layers"][name] = dict(empty=True)
            continue
        bx = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        cv2.imwrite(os.path.join(out, name + ".png"), rgba(rgb, a))
        # ふちの硬さ: 半透明の画素が、ふちの画素に占める割合
        edge = (a > 0.004) & (cv2.erode((a > 0.004).astype(np.uint8), np.ones((3, 3), np.uint8)) == 0)
        semi = float(((a[edge] > 0.02) & (a[edge] < 0.98)).mean()) if edge.any() else 1.0
        man["layers"][name] = dict(bbox=bx, area=int((a > 0.5).sum()), edge_semi_ratio=round(semi, 3))
        if name in hidden:
            continue
        if name in clip:          # 瞳は白目の形で切り抜いて重ねる（PSD ではクリッピング）
            a = a * np.clip(layers[clip[name]][1], 0, 1)
        comp = comp * (1 - a[..., None]) + rgb * a[..., None]
        ca = ca + a * (1 - ca)
    cv2.imwrite(os.path.join(out, "_composite.png"), rgba(comp, ca))
    # 重ね直しの検査（髪ありの基準画像と比べる）
    both = (aB > 0.5)
    d = np.abs(comp - Brgb).max(-1)
    man["check"] = dict(recompose_mean=float(d[both].mean()), recompose_over30_pct=float((d[both] > 30).mean() * 100),
                        alpha_missing_pct=float(((aB > 0.9) & (ca < 0.6)).sum() / max(1, (aB > 0.9).sum()) * 100),
                        alpha_extra_px=int(((aB < 0.05) & (ca > 0.5)).sum()))
    dm = np.zeros((Hh, Ww, 3), np.uint8)
    dm[..., 2] = np.clip(d * 4, 0, 255) * both
    dm[..., 1] = (((aB > 0.9) & (ca < 0.6)) * 255).astype(np.uint8)
    cv2.imwrite(os.path.join(out, "_diff.png"), cv2.resize(dm, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
    json.dump(man, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    print(json.dumps(man["check"]), json.dumps(notes["regions_px"]), "ribbons", rib_n)
    for k, v in man["layers"].items():
        print(k, v)


main()
