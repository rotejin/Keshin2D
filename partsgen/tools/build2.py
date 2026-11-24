# 生成した差分の絵（前髪・後ろ髪・ツインテール・開いた口）と、切り出し済みの顔・体のパーツから、
# エンジン（js/avatar.js）が読めるモデル（parts/Lxxx.png と model.json）を書き出す
#   python build2.py <nohair3x> <03_front_hair_3x> <04_back_hair_3x> <05_twintails_3x> <06_mouth_open_3x> <切り出し済み parts> <出力モデルフォルダ>
import sys, os, json, numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

fN, f03, f04, f05, f06, pdir, out = sys.argv[1:8]
os.makedirs(os.path.join(out, "parts"), exist_ok=True)


# 描かせた絵は、不透明な所の不透明度が 254 のことがある（255 でない）。そのまま重ねると、どのレイヤーも 0.4% 透けて、
# 顔の下の首の形が、顔を透かしてうっすら見える。char.json の alpha_full（例 250）以上を、完全な不透明として扱う（既定は何もしない）
ALPHA_FULL = CHAR.get("alpha_full")


def load(p):
    im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    if im.shape[2] == 3:
        return im.astype(np.float32), np.ones(im.shape[:2], np.float32)
    a = im[..., 3].astype(np.float32) / 255
    if ALPHA_FULL:
        a[im[..., 3] >= ALPHA_FULL] = 1.0
    return im[..., :3].astype(np.float32), a


def imread_rgba(p):
    """清書した絵（大きく描かせた絵）を読む。alpha_full があれば、不透明な所を 255 にする"""
    im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    if ALPHA_FULL and im is not None and im.ndim == 3 and im.shape[2] == 4:
        im = im.copy()
        im[..., 3][im[..., 3] >= ALPHA_FULL] = 255
    return im


def part(name):
    p = os.path.join(pdir, name + ".png")
    if not os.path.exists(p):
        return np.zeros((Hh, Ww, 3), np.float32), np.zeros((Hh, Ww), np.float32)
    return load(p)


def fill_holes(m):
    m = m.astype(np.uint8)
    ff = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    ff[1:-1, 1:-1] = m
    cv2.floodFill(ff, None, (0, 0), 2)
    return ff[1:-1, 1:-1] != 2


def largest(m):
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
    if n < 2:
        return m.astype(bool)
    return lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])


Nrgb, aN = load(fN)
Hh, Ww = aN.shape
yy, xx = np.mgrid[0:Hh, 0:Ww]
L = {}
for n in ["10_head", "11_ears", "12_nose", "13_brow_L", "13_brow_R", "14_mouth_line", "40_neck", "41_body"] + \
         ["%s_%s" % (k, s) for k in ("20_eye_white", "21_iris", "22_lash_upper", "23_lash_lower", "24_eyelid_crease") for s in "LR"]:
    L[n] = part(n)
if os.path.exists(os.path.join(pdir, "17_lip.png")):
    L["17_lip"] = part("17_lip")       # 唇の塗り（口と一緒に動く）

def extend_fill(rgb, mask, grow):
    """grow のうち mask の外を、いちばん近い mask 内の色で埋める"""
    src = mask.astype(np.uint8)
    dist, lab = cv2.distanceTransformWithLabels(1 - src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys_, xs_ = np.where(src > 0)
    lut = np.zeros((lab.max() + 1, 2), np.int32)
    lut[lab[ys_, xs_]] = np.c_[ys_, xs_]
    out = rgb.copy()
    gy, gx = np.where(grow & ~mask)
    out[gy, gx] = rgb[lut[lab[gy, gx], 0], lut[lab[gy, gx], 1]]
    return out


# ---------- 目のパーツを「大きく清書させた絵」に差し替える（EYE_FRAME・IRIS_BASE）
# 髪なしの絵から色で切り抜いた目のパーツは、上まつげの下端がギザつき、瞳のふちが角ばり、まつげに隠れた側の瞳は作り物の模様になる。
# 片目を大きく描かせた絵（瞳なしの目の枠／瞳だけ）を、切り抜きで分かった左右の目の位置と大きさへ合わせて置く。
# 切り抜いたパーツは、位置と大きさを知るためだけに使う。
def _place(pm, nw, nh, px0, py0):
    """乗算済み BGRA（float）を nw×nh に縮めて、全体のキャンバスの (px0, py0) に置く。色と不透明度を返す"""
    pm = cv2.resize(pm, (max(1, nw), max(1, nh)), interpolation=cv2.INTER_AREA)
    full = np.zeros((Hh, Ww, 4), np.float32)
    x0, y0 = max(0, px0), max(0, py0)
    x1, y1 = min(Ww, px0 + nw), min(Hh, py0 + nh)
    full[y0:y1, x0:x1] = pm[y0 - py0:y1 - py0, x0 - px0:x1 - px0]
    fa = full[..., 3] / 255
    return np.where(fa[..., None] > 1e-3, full[..., :3] / np.maximum(fa[..., None], 1e-3), 0), fa


def _premult(rgb, a):
    return np.dstack([rgb * a[..., None], a * 255]).astype(np.float32)


def _bbox(m):
    ys_, xs_ = np.where(m)
    return xs_.min(), xs_.max() + 1, ys_.min(), ys_.max() + 1


def split_eye_frame(path):
    """瞳なしの目の枠を、白目・上まつげ（二重の線を含む）・下まつげに分ける。大きい絵のまま返す"""
    im = imread_rgba(path)
    if im is None or im.ndim != 3 or im.shape[2] != 4:
        raise SystemExit("目の枠の絵が読めないか、透過ではありません: " + path)
    a = im[..., 3].astype(np.float32) / 255
    rgb = im[..., :3].astype(np.float32)
    h_, w_ = a.shape
    _, S_, V_ = hsv_of(im[..., :3])
    cf = CHAR.get("eye_frame", {})
    k = max(3, int(round(w_ / 170)) | 1)                     # 絵の大きさに合わせた、ならしの幅
    W = (a > 0.5) & (V_ > cf.get("white_vmin", 0.55)) & (S_ < cf.get("white_smax", 0.30))
    W = largest(cv2.morphologyEx(W.astype(np.uint8), cv2.MORPH_OPEN, ell(k)))
    W = fill_holes(cv2.morphologyEx(W.astype(np.uint8), cv2.MORPH_CLOSE, ell(2 * k + 1)))
    Ws = soft(W, 1.0)
    line_a = a * (1 - Ws)
    # 線の色: 白目との境目の画素は白と混ざっているので、線の芯の色で塗り直す（瞳の上に薄い白いふちが出ないように）
    core = (line_a > 0.97) & ~(cv2.dilate(W.astype(np.uint8), ell(k)) > 0)
    line_rgb = extend_fill(rgb, core, line_a > 0.02)
    # 上と下: 白目の、その列での上下のまん中より上を上まつげ、下を下まつげにする（目頭・目尻の外は、端の列の高さで分ける）
    cols = np.where(W.any(0))[0]
    mid = np.zeros(w_, np.float32)
    for x in cols:
        r = np.where(W[:, x])[0]
        mid[x] = (r.min() + r.max()) / 2.0
    mid[:cols.min()] = mid[cols.min()]
    mid[cols.max() + 1:] = mid[cols.max()]
    mid = cv2.GaussianBlur(mid.reshape(1, -1), (0, 0), k).ravel()
    up = np.clip((mid[None, :] - np.arange(h_, dtype=np.float32)[:, None]) / 4.0 + 0.5, 0, 1)
    # 目尻のはねなど、太い線が上下の境目をまたぐキャラは、境目で 2 枚とも半透明になり、肌が細い線になって透ける。
    # eye_frame.seam_overlap（大きい絵での画素数）だけ、下まつげを上へ重ねて、境目を不透明にする（既定 0 は今までどおり）
    ov_ = float(cf.get("seam_overlap", 0))
    up_lo = np.clip((mid[None, :] - ov_ - np.arange(h_, dtype=np.float32)[:, None]) / 4.0 + 0.5, 0, 1) if ov_ else up
    up_a, lo_a = line_a * up, line_a * (1 - up_lo)
    # 白目のふちに沿って残る、ごく薄い筋を落とす（線として太さのある所と、そのすぐそばだけ残す）
    def _solid(a_):
        keep = cv2.dilate(cv2.morphologyEx((a_ > 0.5).astype(np.uint8), cv2.MORPH_OPEN, ell(3)), ell(2 * k + 1)) > 0
        return a_ * keep
    up_a, lo_a = _solid(up_a), _solid(lo_a)
    # 白目は、上まつげの下へ少しもぐらせる（まつげと白目が別々に動いたとき、すき間から肌や瞳のふちが見えないように）
    thick = cv2.erode((up_a > 0.9).astype(np.uint8), ell(3)) > 0
    Wx = W | ((cv2.dilate(W.astype(np.uint8), ell(4 * k + 1)) > 0) & thick)
    Wx = (cv2.morphologyEx(Wx.astype(np.uint8), cv2.MORPH_CLOSE, ell(2 * k + 1)) > 0) & (a > 0.5)     # 白目と、もぐらせた部分の間のすき間を埋める
    w_rgb = extend_fill(rgb, cv2.erode(W.astype(np.uint8), ell(k)) > 0, Wx)
    return dict(W=W, white=(w_rgb, np.maximum(soft(Wx, 1.0) * (Wx | W), Ws * a)), upper=(line_rgb, up_a), lower=(line_rgb, lo_a))


CLEAN_EYES = bool(os.environ.get("EYE_FRAME"))
if CLEAN_EYES:
    fr_ = split_eye_frame(os.environ["EYE_FRAME"])
    gx0, gx1, gy0, gy1 = _bbox(fr_["W"])
    fh_, fw_ = fr_["W"].shape
    # 切り抜いた白目から使うのは「左右の端」と「下の端」だけ（上の端は、まつげの下へ塗り足してあって当てにならない）。
    # 縦横は同じ倍率にし、左右の目で同じ大きさにする（倍率は左右の平均）
    tb_ = {s_: _bbox(L["20_eye_white_" + s_][1] > 0.5) for s_ in "LR"}
    sc_ = float(np.mean([(tb_[s_][1] - tb_[s_][0]) / float(gx1 - gx0) for s_ in "LR"])) * CHAR.get("eye_frame", {}).get("scale", 1.0)
    nw_, nh_ = int(round(fw_ * sc_)), int(round(fh_ * sc_))
    for s_ in "LR":
        tx0, tx1, ty0, ty1 = tb_[s_]
        tcx = (tx0 + tx1) / 2.0
        for key_, nm_ in (("white", "20_eye_white_"), ("upper", "22_lash_upper_"), ("lower", "23_lash_lower_")):
            r_, a_ = fr_[key_]
            pm_ = _premult(r_, a_)
            gcx = (gx0 + gx1) / 2.0
            if s_ == "R":                                              # 描かせたのは画面左の目。画面右の目は左右を返して使う
                pm_ = pm_[:, ::-1]
                gcx = fw_ - gcx
            L[nm_ + s_] = _place(pm_, nw_, nh_, int(round(tcx - gcx * sc_)), int(round(ty1 - gy1 * sc_)))
        L["24_eyelid_crease_" + s_] = (np.zeros((Hh, Ww, 3), np.float32), np.zeros((Hh, Ww), np.float32))   # 二重の線は上まつげに含める
        print("eye frame %s scale %.3f" % (s_, sc_))
if os.environ.get("IRIS_BASE"):
    v_ = imread_rgba(os.environ["IRIS_BASE"])
    if v_ is None or v_.ndim != 3 or v_.shape[2] != 4:
        raise SystemExit("瞳の絵が読めないか、透過ではありません: " + os.environ["IRIS_BASE"])
    bx0, bx1, by0, by1 = _bbox(v_[..., 3] > 127)
    v_ = v_[by0:by1, bx0:bx1].astype(np.float32)
    pmv = _premult(v_[..., :3], v_[..., 3] / 255)
    # 元の絵の瞳は、上をまつげに、下を下まぶたに隠された大きな円。切り抜きのとき、見えているふちに当てはめた円
    # （face/manifest.json の iris_circle_in_box）の中心と半径に合わせて置く。左右で同じ大きさにする（半径は左右の平均）
    man_ = json.load(open(os.path.join(pdir, "manifest.json"), encoding="utf-8")) if os.path.isfile(os.path.join(pdir, "manifest.json")) else {}
    man_ = man_.get("notes", man_)
    circ_ = {}
    for s_ in "LR":
        e_ = man_.get("eye_" + s_)
        if e_:
            cx_, cy_, r_ = e_["iris_circle_in_box"]; bx_ = e_["box"]
            circ_[s_] = ((bx_[2] - cx_) if s_ == "R" else (bx_[0] + cx_), bx_[1] + cy_, r_)   # 画面右の目は、左右を返した絵で測ってある
        else:                                         # 記録が無いとき: 切り抜いた瞳の幅と、いちばん幅の広い行
            tx0, tx1, ty0, ty1 = _bbox(L["21_iris_" + s_][1] > 0.5)
            circ_[s_] = ((tx0 + tx1) / 2.0, ty0 + int(np.argmax((L["21_iris_" + s_][1][ty0:ty1] > 0.5).sum(1))), (tx1 - tx0) / 2.0)
    sc_ = 2 * float(np.mean([circ_[s_][2] for s_ in "LR"])) * CHAR.get("iris_scale", 1.0) / float(v_.shape[1])
    nw_, nh_ = int(round(v_.shape[1] * sc_)), int(round(v_.shape[0] * sc_))
    for s_ in "LR":
        cyi = circ_[s_][1]
        if CLEAN_EYES:
            # 高さは、目の開いている範囲（上まつげの下端〜下まぶた）のまん中に瞳の中心を置く。
            # 当てはめた円の中心は、見えているふちが左右の弧だけなので上下にずれやすい（クラゲちゃんでは、瞳孔より 0.22 半径ぶん上になった）
            col_ = np.where(L["20_eye_white_" + s_][1][:, int(round(circ_[s_][0]))] > 0.5)[0]
            if len(col_):
                cyi = (col_.min() + col_.max()) / 2.0 + 3
        cyi += CHAR.get("iris_dy", 0)
        circ_[s_] = (circ_[s_][0], cyi, circ_[s_][2])
        # char.json の iris_mirror: 画面右の瞳は、左右を返した絵にする（書かなければ、左右とも同じ向き = 前と同じ）。
        # 瞳孔や光が、瞳のまん中から鼻の側へ寄っている絵柄（左右の瞳が、鏡写し）で使う。同じ向きのままだと、画面右の目だけ、外を見ているように見える。
        # 光が、左右の瞳で同じ側（光源の側）にある絵柄では、使わない
        pm_ = pmv[:, ::-1] if (s_ == "R" and CHAR.get("iris_mirror")) else pmv
        L["21_iris_" + s_] = _place(pm_, nw_, nh_, int(round(circ_[s_][0] - nw_ / 2.0)), int(round(cyi - nh_ / 2.0)))
    print("iris scale %.3f size %dx%d centers" % (sc_, nw_, nh_), [tuple(round(float(t), 1) for t in circ_[s_]) for s_ in "LR"])

# ---------- 片目の拡大の上に描かせた絵（閉じた目・笑って閉じた目・片目の涙）を、左右の目の位置へ置く
# 見本（_eyec_ref.png）は、画面左の目のまわりを横 3:縦 2 で切り出したもの。描かせた絵は、それと同じキャンバス・同じ位置に描いてある。
# 切り出した範囲（_eyec_ref.json）へ縮めて置き、画面右の目へは、左右を返して、瞳の中心を合わせて置く
def eye_canvas(env_name):
    path = os.environ.get(env_name)
    jp = os.path.join(os.environ.get("EXTRAS_DIR", ""), "_eyec_ref.json")
    mp = os.path.join(pdir, "manifest.json")
    if not path or not os.path.isfile(jp) or not os.path.isfile(mp):
        return None
    v = imread_rgba(path)
    if v is None or v.ndim != 3 or v.shape[2] != 4:
        raise SystemExit("絵が読めないか、透過ではありません: " + path)
    ref = json.load(open(jp))
    x0, y0, x1, y1 = ref["box"]
    cxL, cyL = ref["center"]
    eR = json.load(open(mp, encoding="utf-8"))["notes"]["eye_R"]
    cxR, cyR = eR["box"][2] - eR["iris_circle_in_box"][0], eR["box"][1] + eR["iris_circle_in_box"][1]     # 画面右の目は、左右を返した絵で測ってある
    pm = _premult(v[..., :3].astype(np.float32), v[..., 3].astype(np.float32) / 255)
    nw, nh = x1 - x0, y1 - y0
    out = {"L": _place(pm, nw, nh, x0, y0)}
    out["R"] = _place(pm[:, ::-1], nw, nh, int(round(cxR - (x1 - cxL))), int(round(y0 + (cyR - cyL))))
    for s_ in "LR":                                       # 帯から離れた小さなごみを落とす
        r_, a_ = out[s_]
        n_, lab_, st_, _ = cv2.connectedComponentsWithStats((a_ > 0.1).astype(np.uint8))
        keep_ = np.isin(lab_, [i for i in range(1, n_) if st_[i, cv2.CC_STAT_AREA] >= 60])
        out[s_] = (r_, a_ * (cv2.dilate(keep_.astype(np.uint8), ell(3)) > 0))
    print("eye canvas %s -> box %s, R center %.1f %.1f" % (env_name, ref["box"], cxR, cyR))
    return out


EYE_CLOSED, EYE_SMILE, TEARS_EYE = eye_canvas("EYE_CLOSED"), eye_canvas("EYE_SMILE"), eye_canvas("TEARS_EYE")
# 差分シートの途中のコマ（まばたきの途中の目）。エンジンが、開いた目と閉じた目の間に、順に見せる。
# 前の作り方（コマを切り替える目と口）で、今の手順では使わない。コマを切り出す道具は、このリポジトリに入れていない
EYE_FRAMES = {k_: eye_canvas("EYE_FRAME_C" + k_) for k_ in ("2", "3", "4", "6") if os.environ.get("EYE_FRAME_C" + k_)}   # 6 は、笑って細めた目
# 差分シートの口のコマ（閉じ・あ・い・う・え・お・小さく開いた口・笑っている口・への字）。見本の範囲（MOUTH_SHEET_REF の box）へ縮めて置く。
# エンジンが、ベクターの口の代わりに、このコマを切り替えて見せる
MOUTH_FRAMES = {}
if os.environ.get("MOUTH_SHEET_REF") and os.path.isfile(os.environ["MOUTH_SHEET_REF"]):
    mb_ = json.load(open(os.environ["MOUTH_SHEET_REF"]))["box"]
    for k_ in "123456789":
        mp_ = os.environ.get("MOUTH_FRAME_C" + k_)
        if mp_ and os.path.isfile(mp_):
            v_ = imread_rgba(mp_)
            pm_ = _premult(v_[..., :3].astype(np.float32), v_[..., 3].astype(np.float32) / 255)
            MOUTH_FRAMES[k_] = _place(pm_, mb_[2] - mb_[0], mb_[3] - mb_[1], mb_[0], mb_[1])
    print("mouth sheet -> box %s, frames %s" % (mb_, "".join(sorted(MOUTH_FRAMES))))

# ---------- キーの形（keyshape.py の出力。<作業フォルダ>/key）。エンジンが、キーとキーの間を、線の変形でつなぐ
# 目: key/eye.json と key/eye_<名前>.png（まつげだけ）、key/eye_under.png（下まつげ・目尻の線・二重の線）。画面左の目の見本の範囲へ置き、
#     画面右の目へは、左右を返して、瞳の中心を合わせて置く。線（T・B・L）は、書き出しの最後に、モデルの座標へ直す
# 口: key/mouth.json と key/mouth_<名前>.png
KEY_DIR = os.environ.get("KEY_DIR", "")
KEY_EYE, KEY_EYE_IMG, KEY_EYE_POS, KEY_MOUTH, KEY_MOUTH_IMG = None, {}, None, None, {}
if KEY_DIR and os.path.isfile(os.path.join(KEY_DIR, "eye.json")) and os.path.isfile(os.path.join(pdir, "manifest.json")):
    KEY_EYE = json.load(open(os.path.join(KEY_DIR, "eye.json")))
    kb_ = KEY_EYE["box"]
    nt_ = json.load(open(os.path.join(pdir, "manifest.json"), encoding="utf-8"))["notes"]
    cxL_, cyL_ = nt_["eye_L"]["box"][0] + nt_["eye_L"]["iris_circle_in_box"][0], nt_["eye_L"]["box"][1] + nt_["eye_L"]["iris_circle_in_box"][1]
    cxR_, cyR_ = nt_["eye_R"]["box"][2] - nt_["eye_R"]["iris_circle_in_box"][0], nt_["eye_R"]["box"][1] + nt_["eye_R"]["iris_circle_in_box"][1]
    x0R_, dyR_ = int(round(cxR_ - (kb_[2] - cxL_))), int(round(cyR_ - cyL_))
    KEY_EYE_POS = (x0R_, dyR_)
    # キーの絵と線を、上下にずらす（3 倍の絵の画素。char.json の key_eye_dy。＋で下へ）。描かせたシートの目は、基準画像の目と、高さが少しずれる
    # （kurage02: 上まぶた・下まぶたとも、基準より 6〜10 画素高かった）。fidscale.py で、基準画像と同じ縮尺に並べて測って決める
    KDY_ = int(round(float(CHAR.get("key_eye_dy", 0))))
    # キーの絵と線を、瞳の中心を軸に縮める（char.json の key_eye_scale。数 1 つか [横, 縦]。書かなければ 1 = 前と同じ）。
    # 描かせたシートの目が、基準画像の目より大きく描かれたとき（例: 横 1.15 倍・縦 1.3 倍）。fidscale.py の目の拡大で測って決める
    KSC_ = CHAR.get("key_eye_scale", 1.0)
    KSX_, KSY_ = (float(KSC_[0]), float(KSC_[1])) if isinstance(KSC_, list) else (float(KSC_), float(KSC_))
    kw_, kh_ = kb_[2] - kb_[0], kb_[3] - kb_[1]
    kwS_, khS_ = int(round(kw_ * KSX_)), int(round(kh_ * KSY_))
    kxL_ = int(round(cxL_ - (cxL_ - kb_[0]) * KSX_)); kxR_ = int(round(cxR_ - (cxR_ - x0R_) * KSX_))
    kyL_ = int(round(cyL_ - (cyL_ - kb_[1]) * KSY_))
    for nm_ in list(KEY_EYE["keys"]) + ["crease", "under", "corner"]:
        fp_ = os.path.join(KEY_DIR, "eye_%s.png" % nm_)
        if not os.path.isfile(fp_):
            continue
        v_ = imread_rgba(fp_)
        pm_ = _premult(v_[..., :3].astype(np.float32), v_[..., 3].astype(np.float32) / 255)
        KEY_EYE_IMG[nm_] = {"L": _place(pm_, kwS_, khS_, kxL_, kyL_ + KDY_),
                            "R": _place(pm_[:, ::-1], kwS_, khS_, kxR_, kyL_ + dyR_ + KDY_)}
    print("key eye: box %s, keys %s, R at x %d dy %+d" % (kb_, " ".join(KEY_EYE["keys"]), x0R_, dyR_))
if KEY_DIR and os.path.isfile(os.path.join(KEY_DIR, "mouth.json")):
    KEY_MOUTH = json.load(open(os.path.join(KEY_DIR, "mouth.json")))
    mb2_ = KEY_MOUTH["box"]
    # char.json の key_mouth_scale: {"キーの名前": 横の倍率}（書かなければ 1 = 前と同じ）。そのキーの絵と線を、口のまん中を軸に、横へ縮める・広げる。
    # 描かせたシートの「閉じた口」（closed）が、基準画像の口より幅広く描かれたときに使う（fidscale.py の口の拡大で、幅を比べて決める）。
    # 高さは変えない（口の位置を動かさない）。開いた口の大きさは、画面の「母音の口の大きさ」（keyMouthShapes）で決める
    def key_mouth_box(nm_):
        sx_ = float((CHAR.get("key_mouth_scale") or {}).get(nm_, 1.0))
        bw_ = mb2_[2] - mb2_[0]
        if sx_ == 1.0:
            return mb2_[0], bw_
        k_ = KEY_MOUTH["keys"][nm_]
        cx_ = mb2_[0] + (k_["xa"] + k_["xb"] + 1) / 2.0 * bw_ / float(KEY_MOUTH["canvas"][0])
        nw_ = int(round(bw_ * sx_))
        return int(round(cx_ - (cx_ - mb2_[0]) * sx_)), nw_
    for nm_ in KEY_MOUTH["keys"]:
        v_ = imread_rgba(os.path.join(KEY_DIR, "mouth_%s.png" % nm_))
        pm_ = _premult(v_[..., :3].astype(np.float32), v_[..., 3].astype(np.float32) / 255)
        kx0_, kbw_ = key_mouth_box(nm_)
        KEY_MOUTH_IMG[nm_] = _place(pm_, kbw_, mb2_[3] - mb2_[1], kx0_, mb2_[1])
    print("key mouth: box %s, keys %s" % (mb2_, " ".join(KEY_MOUTH["keys"])))

# ---------- 目の線のレイヤーから「肌色で上書きしているだけ」の画素を外す（閉じ目・笑い目で肌色の三角になって見えるため）
for s_ in ("" if CLEAN_EYES else "LR"):
    cover_all = np.zeros((Hh, Ww), np.float32)
    wp_rgb = np.zeros((Hh, Ww, 3), np.float32)      # 線のパーツに紛れていた「白目の色の画素」。白目へ戻す
    wp_a = np.zeros((Hh, Ww), np.float32)
    for k in ("22_lash_upper", "23_lash_lower", "24_eyelid_crease"):
        rgb_, a_ = L["%s_%s" % (k, s_)]
        solid_ = np.zeros((Hh, Ww), bool)
        if k == "22_lash_upper" and CHAR.get('lash_solid'):
            # 上まつげの本体の内側は、元の絵の色のまま不透明にする。まつげの中のつや（瞳と近い色・白い点）が
            # 「瞳で説明できる」「肌で上書きしているだけ」と判定されて、半透明や穴になるのを防ぐ
            # 守るのは「暗いまつげ色の部分」と、それに囲まれた小さなつやだけ（とげの間の肌色は守らない）
            Vn_ = Nrgb.max(-1) / 255.0
            body_l = fill_holes(cv2.morphologyEx(((a_ > 0.5) & (Vn_ < 0.7)).astype(np.uint8), cv2.MORPH_CLOSE, ell(5)))
            solid_ = cv2.erode(body_l.astype(np.uint8), ell(CHAR['lash_solid'])) > 0
            rgb_ = np.where(solid_[..., None], Nrgb, rgb_)
            a_ = np.where(solid_, 1.0, a_).astype(np.float32)
        Hl, Sl, Vl = hsv_of(np.clip(rgb_, 0, 255).astype(np.uint8))
        cover = (Vl > 0.75) & (Sl < 0.5) & (a_ > 0) & ~solid_
        # 明るい画素のうち、肌色のものは「肌で上書きしているだけ」、白っぽいものは「白目の一部」
        light_ = (Vl > 0.75) & (Sl < 0.5) & (a_ > 0) & ~solid_
        skin_ = light_ & skinlike_mask(rgb_)
        white_ = light_ & ~skin_ & (Sl < 0.2)
        cover_all = np.maximum(cover_all, a_ * skin_)
        take_ = white_ & (a_ > wp_a)
        wp_rgb[take_] = rgb_[take_]
        wp_a[take_] = a_[take_]
        # 瞳のふちから紛れ込んだ紫のかけらも外す
        ih_ = CHAR.get('lash_iris_bits')          # [色相の下限, 上限, 明度の下限]。まつげ自体が紫のキャラでは、まつげを消さない範囲にする
        if ih_:
            # まつげ自体が瞳と近い色（紫のつや）を持つキャラ: まつげの内側は消さず、ふちと外側にある瞳の色だけ消す
            inner_ = (cv2.erode((a_ > 0.5).astype(np.uint8), ell(CHAR.get('lash_keep_inner', 13))) > 0) | solid_
            purple = (Hl > ih_[0]) & (Hl < ih_[1]) & (Sl > 0.25) & (Vl > ih_[2]) & ~inner_
        else:
            purple = (Hl > 255) & (Hl < 325) & (Sl > 0.3) & (Vl > 0.25)
        a_ = a_ * ~cover * ~purple
        # 小さな切れ端を落とす
        n_, lab_, st_, _ = cv2.connectedComponentsWithStats((a_ > 0.2).astype(np.uint8))
        keep_ = np.isin(lab_, [i for i in range(1, n_) if st_[i, cv2.CC_STAT_AREA] >= 120])
        a_ = a_ * (cv2.dilate(keep_.astype(np.uint8), ell(3)) > 0)
        L["%s_%s" % (k, s_)] = (rgb_, a_)
    # 上書きが要った所 = 白目と瞳の塗り足しが線の外へはみ出していた所。そこは白目を出さない
    wr, wa_ = L["20_eye_white_" + s_]
    wa_ = wa_ * (1 - np.clip(cv2.dilate(cover_all, ell(3)), 0, 1))
    # 白目の色の画素を白目へ戻す（目頭の白目が欠けて、横を向くと肌色が見えていた）
    wp_a = wp_a * (cv2.morphologyEx((wp_a > 0.3).astype(np.uint8), cv2.MORPH_OPEN, ell(5)) > 0)
    wr = wr * (1 - wp_a[..., None]) + wp_rgb * wp_a[..., None]
    wa_ = np.maximum(wa_, wp_a)
    # 白目のふちをなめらかにする（ガタつきは目を動かしたときに見える）
    wm = cv2.morphologyEx((wa_ > 0.5).astype(np.uint8), cv2.MORPH_CLOSE, ell(9))
    wm = cv2.morphologyEx(wm, cv2.MORPH_OPEN, ell(9))
    wm = cv2.GaussianBlur(wm.astype(np.float32), (0, 0), 3) > 0.5
    wm = largest(wm)                                   # 離れた小さな点は白目にしない
    wfill = extend_fill(wr, wa_ > 0.5, wm)
    # 白目の明るい所がピンクがかっていて、目頭では肌と見分けがつかなかった。
    # 上まぶたの影（暗い所）は残し、明るい所だけ白へ寄せる
    mx_ = wfill.max(-1)
    k_ = (np.clip((mx_ - 205) / 30.0, 0, 1) * 0.85)[..., None]
    wfill = wfill * (1 - k_) + np.array([252, 249, 250], np.float32) * k_
    L["20_eye_white_" + s_] = (wfill, soft(wm, 1.2))
# ---------- 頭・眉・耳を「大きく清書させた絵」に差し替える（HEAD・BROW・EAR）。目と同じ考え方で、切り抜きは位置と大きさを知るためだけに使う
if os.environ.get("HEAD"):
    # 頭だけ（耳・目・眉・鼻・口・首なし）を、輪郭線が一周つながった絵として大きく描かせたもの。
    # 切り抜いた頭は、耳を切り離した所の輪郭線が途切れ、欠けやにじみが残っていた。
    # 切り抜いた頭の「左右の端・てっぺん・あご先」にぴったり合わせて置く（縦横は別々の倍率。顔の中のパーツの位置を変えないため）
    v_ = imread_rgba(os.environ["HEAD"])
    if v_ is None or v_.ndim != 3 or v_.shape[2] != 4:
        raise SystemExit("頭の絵が読めないか、透過ではありません: " + os.environ["HEAD"])
    hm_ = largest(v_[..., 3] > 127)
    bx0, bx1, by0, by1 = _bbox(hm_)
    v_ = (v_.astype(np.float32) * hm_[..., None])[by0:by1, bx0:bx1]
    ox0, ox1, oy0, oy1 = _bbox(L["10_head"][1] > 0.5)
    # char.json の head_fit_pad: [左, 上, 右, 下]（3 倍の絵の画素。書かなければ 0 = 前と同じ）。切り抜いた頭の範囲を、このぶん広げてから、描かせた頭を合わせる。
    # あごの輪郭線が、首の影とつながった太い黒で描かれた絵柄では、切り抜いた頭が、あごの線の内側（肌の端）で終わる。描かせた頭は、線の外側を
    # そこへ合わせるので、あごが、線の太さのぶん短くなる（chiwa: 16 画素。口からあご先までが 1 割短かった）。fidscale.py の顔の拡大で、あご先の線の高さを比べて決める
    hp_ = [int(round(float(t_))) for t_ in (CHAR.get("head_fit_pad") or [0, 0, 0, 0])]
    ox0, oy0, ox1, oy1 = ox0 - hp_[0], oy0 - hp_[1], ox1 + hp_[2], oy1 + hp_[3]
    or_, oa2 = L["10_head"]
    nr_, na_ = _place(_premult(v_[..., :3], v_[..., 3] / 255), int(ox1 - ox0), int(oy1 - oy0), int(ox0), int(oy0))
    if CHAR.get("head_fit_jaw"):
        # char.json の head_fit_jaw: 描かせた頭の左右の位置を、切り抜いた頭の「あごのあたりの、左右のまん中」に合わせる（書かなければ、左右の端に合わせる = 前と同じ）。
        # 切り抜いた頭は、耳を切り離した所（こめかみの高さ）が、左右で同じ幅に切れるとは限らない。片方だけ外へ出ていると、左右の端のまん中が、
        # 顔のまん中からずれ、描かせた頭（左右対称）が、目鼻口に対して横へずれて置かれる（chiwa: 14 画素。横を向いたとき、奥の目と輪郭の余裕が、左右で 21 画素違った）。
        # あごのあたり（頭の高さの 70〜93%）は、耳の切り口の影響を受けない
        def jaw_cx_(a_):
            ysj_ = np.where((a_ > 0.5).any(1))[0]
            tj_, bj_ = int(ysj_.min()), int(ysj_.max())
            rows_ = [np.where(a_[y_] > 0.5)[0] for y_ in range(int(tj_ + 0.70 * (bj_ - tj_)), int(tj_ + 0.93 * (bj_ - tj_)), 10)]
            return float(np.median([(r_.min() + r_.max()) / 2.0 for r_ in rows_ if len(r_)]))
        dxh_ = int(round(jaw_cx_(oa2) - jaw_cx_(na_)))
        if dxh_:
            nr_, na_ = _place(_premult(v_[..., :3], v_[..., 3] / 255), int(ox1 - ox0), int(oy1 - oy0), int(ox0) + dxh_, int(oy0))
        print("head_fit_jaw: 頭を横へ %+d 画素（あごのまん中に合わせた）" % dxh_)
    # 肌のゆるやかな色合い（頬の赤み、額からあごへの濃淡）は、元の絵のものへ戻す。描かせた頭は、赤みが薄く・位置が少し違って出る。
    # 移すのは大きくぼかした差だけなので、切り抜いた頭に残っていた細かい跡は移らない
    both_ = (oa2 > 0.9) & (na_ > 0.9)
    if CHAR.get("head_tone_gain"):
        # char.json の head_tone_gain: 描かせた頭の肌の色を、切り抜いた頭の肌の色（中央値）へ、色ごとの倍率 1 つで合わせる（書かなければ、しない = 前と同じ）。
        # head_tone: 0（場所ごとの色合いを移さない。セル塗り）にしたキャラで、描かせた頭の肌が、全体に少しピンク寄り・黄色寄りになったときに使う。
        # 倍率なので、黒い輪郭線は黒いまま。場所ごとの差は移さないので、切り抜いた頭に残った跡も移らない
        sk_ = both_ & (or_.min(-1) > 150) & (nr_.min(-1) > 150)
        if int(sk_.sum()) > 1000:
            gn_ = np.median(or_[sk_], 0) / np.maximum(np.median(nr_[sk_], 0), 1.0)
            nr_ = np.clip(nr_ * gn_, 0, 255)
            print("head_tone_gain (BGR) %.3f %.3f %.3f" % tuple(float(t_) for t_ in gn_))
    sg_ = 0.018 * (oy1 - oy0)
    wb_ = cv2.GaussianBlur(both_.astype(np.float32), (0, 0), sg_)
    dl_ = cv2.GaussianBlur((or_ - nr_) * both_[..., None], (0, 0), sg_) / np.maximum(wb_[..., None], 1e-3)
    L["10_head"] = (np.clip(nr_ + dl_ * CHAR.get("head_tone", 1.0), 0, 255), na_)
    print("head scale %.3f %.3f" % ((ox1 - ox0) / float(v_.shape[1]), (oy1 - oy0) / float(v_.shape[0])))
# char.json の eye_marks: {"boxes": [[x0, y0, x1, y1], …]}（3 倍の絵の画素。書かなければ、しない = 前と同じ）。
# 頭の絵に描かれている、目のすぐ下の印（ほほの斜線・点・ほくろ）を、別のレイヤー「目の下の印」に分けて、エンジンに、目と一緒に動かさせる（model.json の eyeAttach）。
# 頭の絵（肌）は、輪郭と一緒に動く。目は、顔の中で、肌とは別に動く（下を向くと下へ滑り、上を向くと上へ滑る）。印を肌の絵に入れたままだと、
# 下を向くと、目が印の上へ来て隠れ、上を向くと、印が口の横まで取り残される（chiwa: 目の下の赤い斜線 3 本）。
# 範囲には、肌と印だけを入れる（まつげ・輪郭線・鼻を入れない）。印は、範囲の肌の色（印を消して埋めた肌）との色の差で取り出し、
# ふちの半透明も、肌の色を引いて取る（動いた先の肌の色になじむ。印のまわりに、元の場所の肌の色を持って行かない）
EYE_MARKS = None
EM_ = CHAR.get("eye_marks") or {}
if EM_.get("boxes"):
    hr_, ha_ = L["10_head"]
    hr_ = hr_.copy()
    mk_r_, mk_a_ = np.zeros_like(hr_), np.zeros((Hh, Ww), np.float32)
    thr_, mg_ = float(EM_.get("thr", 14)), 16
    for bx_ in EM_["boxes"]:
        x0_, y0_, x1_, y1_ = [int(round(float(t_))) for t_ in bx_]
        X0_, Y0_, X1_, Y1_ = max(x0_ - mg_, 0), max(y0_ - mg_, 0), min(x1_ + mg_, Ww), min(y1_ + mg_, Hh)      # 埋めるときに使う、まわりの肌
        reg_, ra_ = hr_[Y0_:Y1_, X0_:X1_].copy(), ha_[Y0_:Y1_, X0_:X1_]
        inb_ = np.zeros(reg_.shape[:2], bool)
        inb_[y0_ - Y0_:y1_ - Y0_, x0_ - X0_:x1_ - X0_] = True
        ok_ = inb_ & (ra_ > 0.9)
        if int(ok_.sum()) < 50:
            print("eye_marks: 範囲 %s は、頭の絵の外です（とばします）" % bx_)
            continue
        skin0_ = np.median(reg_[ok_], 0)                                        # 範囲の大半は、肌
        m0_ = ok_ & (np.abs(reg_ - skin0_).max(-1) > thr_)
        if not m0_.any():
            print("eye_marks: 範囲 %s に、印が見つかりません（肌との色の差が %g より大きい画素が無い）" % (bx_, thr_))
            continue
        edge_ = m0_ & ~cv2.erode(inb_.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        if edge_.any():
            print("注意: eye_marks の範囲 %s のふちに、肌と違う色がかかっています（%d 画素）。印が切れているか、まつげ・輪郭線が入っています。範囲を直してください" % (bx_, int(edge_.sum())))
        mm_ = cv2.dilate(m0_.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))).astype(bool) & (ra_ > 0.5)
        fill_ = cv2.inpaint(np.clip(reg_, 0, 255).astype(np.uint8), mm_.astype(np.uint8), 7, cv2.INPAINT_TELEA).astype(np.float32)
        d_ = reg_ - fill_
        dn_ = np.sqrt((d_ ** 2).sum(-1))
        core_ = m0_ & (dn_ >= 0.6 * float(dn_[m0_].max()))
        lc_ = np.median(reg_[core_], 0)                                         # 印の芯の色
        v_ = lc_[None, None, :] - fill_
        al_ = np.clip((d_ * v_).sum(-1) / np.maximum((v_ ** 2).sum(-1), 1.0), 0, 1) * mm_
        col_ = np.where((al_ > 0.2)[..., None], np.clip(fill_ + d_ / np.maximum(al_, 0.2)[..., None], 0, 255), lc_[None, None, :])
        err_ = float(np.abs(al_[..., None] * col_ + (1 - al_[..., None]) * fill_ - reg_)[mm_].max())
        n_ = cv2.connectedComponents((al_ > 0.5).astype(np.uint8))[0] - 1
        hr_[Y0_:Y1_, X0_:X1_] = np.where(mm_[..., None], fill_, reg_)
        mk_r_[Y0_:Y1_, X0_:X1_] = np.where(mm_[..., None], col_, mk_r_[Y0_:Y1_, X0_:X1_])
        mk_a_[Y0_:Y1_, X0_:X1_] = np.maximum(mk_a_[Y0_:Y1_, X0_:X1_], al_ * ra_)
        print("eye_marks: 範囲 %s から、印 %d 個（%d 画素。芯の色 BGR %d,%d,%d）を分けました。重ね直した絵と、もとの頭の差は、最大 %.1f"
              % (bx_, n_, int((al_ > 0.5).sum()), lc_[0], lc_[1], lc_[2], err_))
    if mk_a_.max() > 0.5:
        L["10_head"] = (hr_, ha_)
        EYE_MARKS = (mk_r_, mk_a_)
if os.environ.get("BROW"):
    v_ = imread_rgba(os.environ["BROW"])
    if v_ is None or v_.ndim != 3 or v_.shape[2] != 4:
        raise SystemExit("眉の絵が読めないか、透過ではありません: " + os.environ["BROW"])
    bx0, bx1, by0, by1 = _bbox(v_[..., 3] > 127)
    v_ = v_[by0:by1, bx0:bx1].astype(np.float32)
    pmb = _premult(v_[..., :3], v_[..., 3] / 255)
    # 切り抜いた眉は、中が半透明に抜け、ふちに切れ端が散っている。薄い所もつないでから、太さのあるいちばん大きな塊の範囲を使う
    def _brow_box(a_):
        m_ = cv2.morphologyEx((a_ > 0.2).astype(np.uint8), cv2.MORPH_CLOSE, ell(15))
        return _bbox(largest(cv2.morphologyEx(m_, cv2.MORPH_OPEN, ell(5))))
    bb_ = {s_: _brow_box(L["13_brow_" + s_][1]) for s_ in "LR"}
    sc_ = float(np.mean([bb_[s_][1] - bb_[s_][0] for s_ in "LR"])) * CHAR.get("brow_scale", 1.0) / float(v_.shape[1])
    nw_, nh_ = int(round(v_.shape[1] * sc_)), int(round(v_.shape[0] * sc_))
    for s_ in "LR":
        tx0, tx1, ty0, ty1 = bb_[s_]
        L["13_brow_" + s_] = _place(pmb[:, ::-1] if s_ == "R" else pmb, nw_, nh_,
                                    int(round((tx0 + tx1) / 2.0 - nw_ / 2.0)), int(round((ty0 + ty1) / 2.0 - nh_ / 2.0)))
    print("brow scale %.3f size %dx%d" % (sc_, nw_, nh_))
if os.environ.get("EAR"):
    # 片耳（画面左の耳）を、頭に隠れる付け根の側まで大きく描かせた絵。切り抜いた耳の「外側の端・上端・下端」に合わせて置く。
    # 画面右の耳は左右を返して使う。大きさは左右で同じ（高さの平均）
    v_ = imread_rgba(os.environ["EAR"])
    if v_ is None or v_.ndim != 3 or v_.shape[2] != 4:
        raise SystemExit("耳の絵が読めないか、透過ではありません: " + os.environ["EAR"])
    bx0, bx1, by0, by1 = _bbox(v_[..., 3] > 127)
    v_ = v_[by0:by1, bx0:bx1].astype(np.float32)
    pme = _premult(v_[..., :3], v_[..., 3] / 255)
    hx0, hx1, _, _ = _bbox(L["10_head"][1] > 0.5)
    hcx = (hx0 + hx1) // 2
    oa_ = L["11_ears"][1] > 0.5
    eb_ = [_bbox(oa_ & ((xx < hcx) if i_ == 0 else (xx >= hcx))) for i_ in (0, 1)]
    sc_ = float(np.mean([b_[3] - b_[2] for b_ in eb_])) * CHAR.get("ear_scale", 1.0) / float(v_.shape[0])
    nw_, nh_ = int(round(v_.shape[1] * sc_)), int(round(v_.shape[0] * sc_))
    er_, ea_ = np.zeros((Hh, Ww, 3), np.float32), np.zeros((Hh, Ww), np.float32)
    for i_, (ox0, ox1, oy0, oy1) in enumerate(eb_):
        r_, a_ = _place(pme if i_ == 0 else pme[:, ::-1], nw_, nh_, int(ox0) if i_ == 0 else int(ox1 - nw_), int(round((oy0 + oy1) / 2.0 - nh_ / 2.0)))
        take = a_ > ea_
        er_[take] = r_[take]
        ea_ = np.maximum(ea_, a_)
    L["11_ears"] = (er_, ea_)
    print("ear scale %.3f size %dx%d" % (sc_, nw_, nh_))
else:
    # ---------- 耳の、頭に隠れる側の塗り足しをなめらかな肌色にする
    er, ea = L["11_ears"]
    He, Se, Ve = hsv_of(np.clip(er, 0, 255).astype(np.uint8))
    ed_ = CHAR.get('ear_dark', [0.4, 0.45])           # [明度の上限, 彩度の上限]
    darkbit = cv2.dilate(((Ve < ed_[0]) & (Se < ed_[1]) & (ea > 0.2)).astype(np.uint8), ell(7)) > 0   # 耳に付いたまつげのかけら
    # かけらは消さずに、まわりの耳の色で塗りつぶす（形は残す）。耳の本体から離れた切れ端だけ落とす
    er = extend_fill(er, (ea > 0.5) & ~darkbit, darkbit & (ea > 0.2))
    body_ = cv2.morphologyEx(((ea > 0.5) & ~darkbit).astype(np.uint8), cv2.MORPH_OPEN, ell(15))
    ea = ea * (cv2.dilate(body_, ell(21)) > 0)
    # 頭に隠れる側は、耳の明るい肌色で塗り、内側へ向かって薄く消す（濃い板に見えないように）
    hidm = (L["10_head"][1] > 0.9) & (ea > 0.02)
    vis_ = (ea > 0.5) & ~hidm
    He, Se, Ve = hsv_of(np.clip(er, 0, 255).astype(np.uint8))
    skinc = np.median(er[vis_ & (Ve > 0.9)], axis=0) if (vis_ & (Ve > 0.9)).any() else np.array([225, 215, 250], np.float32)
    dv = cv2.distanceTransform((~vis_).astype(np.uint8), cv2.DIST_L2, 5)
    fade = np.clip(1 - dv / 28.0, 0, 1)
    er2 = er.copy()
    er2[hidm] = skinc
    L["11_ears"] = (er2, np.where(hidm, ea * fade, ea))

# ---------- 前髪と横の髪: 「03（髪なし + 前の髪）」と髪なしの差
A, aA = load(f03)
A8 = np.clip(A, 0, 255).astype(np.uint8)
diff = np.abs(A - Nrgb).max(-1)
Hc, Sc, Vc = hsv_of(A8)
hm = (aA > 0.5) & ((aN < 0.5) | (diff > 22))
hm = cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
thick = cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, ell(11))
near_thick = cv2.dilate(thick, ell(25)) > 0
# 髪の塗り = はっきりしたピンク。髪の線 = 赤紫がかった濃い色で、髪の塗りのすぐそばにあるもの
# （耳や肌の薄いピンク、まつげや服の黒、輪郭線の描き直しの差は髪にしない）
pinkish = (Hc > 290) & (Hc < 355) & (Sc > 0.38) & (Vc > 0.3)
fillpx = cv2.morphologyEx((hm & pinkish).astype(np.uint8), cv2.MORPH_OPEN, ell(5))
near_fill = cv2.dilate(fillpx, ell(13)) > 0
hairline = (Vc < 0.6) & (Sc > 0.3) & (Hc > 295) & (Hc < 358) & near_fill
hm &= pinkish | hairline | (aN < 0.5)
eyes = (L["20_eye_white_L"][1] > 0.3) | (L["20_eye_white_R"][1] > 0.3)
hm &= ~(cv2.dilate(eyes.astype(np.uint8), ell(5)) > 0)
# 耳の上では、濃いピンクの髪と、そのすぐそばの線だけを髪にする（耳の影や耳の輪郭線を拾わない）
earm = cv2.dilate((L["11_ears"][1] > 0.3).astype(np.uint8), ell(9)) > 0
strong = cv2.morphologyEx((pinkish & (Sc > 0.5)).astype(np.uint8), cv2.MORPH_OPEN, ell(7))
hm &= ~earm | (strong > 0) | (hairline & (cv2.dilate(strong, ell(9)) > 0))
hm = cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, ell(3)) > 0
holes = fill_holes(hm) & ~hm & (aA > 0.5)
n, lab, st, _ = cv2.connectedComponentsWithStats(holes.astype(np.uint8))
hm |= np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] < 90000])
# いちばん大きな塊（頭の髪）につながっている所だけを髪にする。服のピンクの拾いすぎを落とす
hm = largest(cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_CLOSE, ell(9))) & hm
# 細いひげ状の拾いすぎを落とす（太さ 5px 以上の所と、その近くだけ残す）
hm &= cv2.dilate(cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, ell(5)), ell(11)) > 0
front_a = soft(hm, 0.9) * aA
front_a[cv2.erode(hm.astype(np.uint8), ell(3)) > 0] = aA[cv2.erode(hm.astype(np.uint8), ell(3)) > 0]
L["front"] = (A, front_a)
# 「前髪だけを透過で描いた絵」があれば、差から取ったものの代わりにそれを使う（ふちがきれい）
if os.environ.get("FRONT_ONLY"):
    F_, aF_ = load(os.environ["FRONT_ONLY"])
    aF_[aF_ < 0.03] = 0
    L["front"] = (F_, aF_)
# 肩にかかる横の髪（あごより下）は別レイヤーにして、前髪より大きく揺らす
ys = np.where((L["10_head"][1] > 0.5).any(1))[0]
head_top, chin = int(ys.min()), int(ys.max())
cut = chin - int(0.10 * (chin - head_top))
wgt = np.clip((yy - cut) / 40.0, 0, 1).astype(np.float32)

# ---------- 後ろ髪・ツインテール: 生成した絵をそのまま使う
B4, a4 = load(f04)
a4[a4 < 0.03] = 0
L["back"] = (B4, a4)
T5, a5 = load(f05) if f05 != 'none' else (np.zeros((Hh, Ww, 3), np.float32), np.zeros((Hh, Ww), np.float32))
a5[a5 < 0.03] = 0
cxm = float(np.median([(np.where(r > 0.5)[0].min() + np.where(r > 0.5)[0].max()) / 2
                       for r in L["10_head"][1][head_top + 50:chin - 50:20]]))
L["tail_R"] = (T5, a5 * (xx < cxm))        # R = 画面左（キャラから見て右）
L["tail_L"] = (T5, a5 * (xx >= cxm))

# ---------- 口の中と舌: 「06（口を開けた絵）」から
if f06 == 'none':          # 開いた口の絵が無い（口はベクターで描く）。エンジンが名前で探すので空のレイヤーを置く
    L['mouth_in'] = L['tongue'] = (np.zeros((Hh, Ww, 3), np.float32), np.zeros((Hh, Ww), np.float32))
    mo = tongue = np.zeros((Hh, Ww), bool); dy = 0
else:
    M, aM = load(f06)
    ml = L["14_mouth_line"][1]
    mys, mxs = np.where(ml > 0.5)
    mcx, mcy, mw = (mxs.min() + mxs.max()) / 2, float(np.median(mys)), mxs.max() - mxs.min()
    bx0, bx1 = int(mcx - mw * 1.1), int(mcx + mw * 1.1)
    by0, by1 = int(mcy - mw * 0.75), int(mcy + mw * 1.25)
    box = np.zeros((Hh, Ww), bool)
    box[by0:by1, bx0:bx1] = True
    M8 = np.clip(M, 0, 255).astype(np.uint8)
    Hm_, Sm_, Vm_ = hsv_of(M8)
    dm = np.abs(M - Nrgb).max(-1)
    mo = box & (dm > 30) & ~skinlike_mask(M)
    mo = fill_holes(largest(cv2.morphologyEx(mo.astype(np.uint8), cv2.MORPH_CLOSE, ell(15))))
    mo = cv2.morphologyEx(mo.astype(np.uint8), cv2.MORPH_OPEN, ell(7)) > 0
    tongue = mo & (Vm_ > 0.72) & (Sm_ > 0.22) & (Sm_ < 0.75) & (yy > np.where(mo.any(1))[0].mean())
    tongue = fill_holes(largest(cv2.morphologyEx(tongue.astype(np.uint8), cv2.MORPH_OPEN, ell(9))))
    tg = cv2.dilate(tongue.astype(np.uint8), ell(9))
    inner8 = cv2.inpaint(M8, (tg & mo).astype(np.uint8) * 255, 7, cv2.INPAINT_TELEA)
    top_mo = int(np.where(mo.any(1))[0].min())
    dy = int(mcy - 14 - top_mo)                      # 開いた口の上端を、閉じた口の線のすぐ上へ寄せる
    Ms = np.float32([[1, 0, 0], [0, 1, dy]])
    def shift(img):
        return cv2.warpAffine(img, Ms, (Ww, Hh))
    L["mouth_in"] = (shift(inner8.astype(np.float32)), shift(soft(mo, 1.0)))
    L["tongue"] = (shift(M), shift(soft(tongue, 1.0)))

# ---------- エンジンの座標系へ合わせる（頭頂 y=111、あご先 y=1167、顔の中心 x=1500。最初のモデル（パーツ分け済みの PSD）の座標）
S = 1056.0 / (chin - head_top)
OW, OH, YMAX = 3000, 2362, 2360
PADY = int(CHAR.get('pad_top', 0))      # 頭頂より上へはみ出すパーツ（帽子など）のための余白。レイヤーの y は負になる
ox, oy = int(round(1500 - S * cxm)), int(round(111 - S * head_top))
sw, sh = int(round(Ww * S)), int(round(Hh * S))


def place(rgb, a):
    pm = np.dstack([rgb * a[..., None], a * 255]).astype(np.float32)
    sm = cv2.resize(pm, (sw, sh), interpolation=cv2.INTER_AREA)
    c = np.zeros((OH + PADY, OW, 4), np.float32)
    yo = oy + PADY
    x0, y0 = max(0, ox), max(0, yo)
    x1, y1 = min(OW, ox + sw), min(OH + PADY, yo + sh)
    c[y0:y1, x0:x1] = sm[y0 - yo:y1 - yo, x0 - ox:x1 - ox]
    al = c[..., 3] / 255
    return np.where(al[..., None] > 1e-4, c[..., :3] / np.maximum(al[..., None], 1e-4), 0), al


EMPTY = (np.zeros((Hh, Ww, 3), np.float32), np.zeros((Hh, Ww), np.float32))
fr_rgb, fr_a = L["front"]
# 「前髪だけ」「左右の横髪だけ」を別々に描かせた絵があれば、房ごとに別レイヤーにする（BANGS_ONLY・SIDE_ONLY）
SIDE_R = SIDE_L = HAIR_BASE = None
if os.environ.get("BANGS_ONLY") and os.environ.get("SIDE_ONLY"):
    # 髪の下地: 分ける前の前髪の絵の、耳より上の部分。前髪と横髪が別々に動いてすき間ができたとき、
    # 頭の肌ではなく髪が見えるようにする（横を向くと、こめかみに肌色が見えた）
    # 髪のふちを、はっきりさせる。描かせた絵は、毛先や房のふちの不透明度がぼけていて（半透明の毛先・もや・細いひげ）、
    # 肌の上で毛先が透けて見えた。不透明度 0.5 の線で切り、細いひげを落として、ふちだけを 1px ほどなめらかにする
    def harden(a, r=5, keep=400):
        m = cv2.morphologyEx((a > 0.5).astype(np.uint8), cv2.MORPH_OPEN, ell(r))
        n_, lab_, st_, _ = cv2.connectedComponentsWithStats(m)
        m = np.isin(lab_, [i for i in range(1, n_) if st_[i, cv2.CC_STAT_AREA] >= keep])
        return soft(m, 1.0).astype(np.float32)
    base_rgb, base_a = fr_rgb, fr_a
    fr_rgb, fr_a = load(os.environ["BANGS_ONLY"])
    fr_a[fr_a < 0.03] = 0
    sd_rgb, sd_a = load(os.environ["SIDE_ONLY"])
    sd_a[sd_a < 0.03] = 0
    if not CHAR.get("hair_soft_edge"):
        fr_a, sd_a = harden(fr_a), harden(sd_a)
    # 髪の下地は、前髪のまわり（こめかみのすき間）だけにする。前は、横髪の写しを下までぼかして敷いていたので、
    # 横髪が揺れると、動かない写しのぼけた切れ目が、ほおの上に見えた
    # 広げるのは横へだけ（下へ広げると、前髪の毛先の下に、切り口の平らな髪が出る）
    br = int(CHAR.get("hair_base_grow", 16))
    near_bangs = cv2.dilate((fr_a > 0.5).astype(np.uint8), np.ones((5, 2 * br + 1), np.uint8)) > 0
    HAIR_BASE = (base_rgb, (harden(base_a) if not CHAR.get("hair_soft_edge") else base_a) * soft(near_bangs, 1.2))
    SIDE_R = (sd_rgb, sd_a * (xx < cxm))
    SIDE_L = (sd_rgb, sd_a * (xx >= cxm))
# char.json の neck_clean: 体の絵に残った「首の輪郭線の切れ端」を消す。
# 首と体を分けるとき、首の輪郭線の外側が、体の側に細い縦の線で残ることがある（えりの中。左右 1 本ずつ）。体だけを描き直させた絵（extras）にも、
# 見本から写って残る。この線は体について動くので、首が動くと、首のふちが 2 本に見える（「首が二重」）。
# 直すのは、首のそば（首の形から 30 画素以内）にあって、色が首の線・肌に近い（赤み。服の色ではない）所だけ:
#   服の外へ細く出ている所（幅 17 画素未満）は、消す。服の中（えりの裏など）に入っている所は、穴にせず、となりの服の色で塗る
# 服そのものが赤・肌色のキャラでは、服まで直してしまうので、使わない（neck_clean を書かない）
NECK_MASK = None
def cut_neck_slivers(rgb_, a_, name_):
    if NECK_MASK is None or not CHAR.get("neck_clean"):
        return rgb_, a_
    near_ = cv2.dilate(NECK_MASK.astype(np.uint8), ell(61)) > 0
    op_ = a_ > 0.5
    b_, g_, r_ = rgb_[..., 0], rgb_[..., 1], rgb_[..., 2]
    red_ = op_ & near_ & (r_ - b_ > 20) & (r_ - g_ > 20) & (r_ > 90)           # 首の輪郭線（赤茶）・肌の色。紺・黒・白の服は入らない
    if not red_.any():
        return rgb_, a_
    red_ = (cv2.dilate(red_.astype(np.uint8), ell(5)) > 0) & near_ & (a_ > 0.02)      # 服の色とまじった、ふちの画素も
    wide_ = cv2.morphologyEx((op_ & ~red_).astype(np.uint8), cv2.MORPH_OPEN, ell(17)) > 0
    inside_ = red_ & (cv2.morphologyEx((wide_ | red_).astype(np.uint8), cv2.MORPH_OPEN, ell(17)) > 0)   # 服の中に入っている所
    # 首の形（輪郭線を含む）と重なる所は、塗らずに消す（塗ると、その下にある首の輪郭線が、服の色で隠れて、線が途切れる）
    inside_ &= ~(cv2.dilate(NECK_MASK.astype(np.uint8), ell(3)) > 0)
    out_ = red_ & ~inside_                                                              # 服の外へ、細く出ている所・首と重なる所
    rgb2_ = extend_fill(rgb_, op_ & ~red_, red_)
    ys_, xs_ = np.where(red_)
    print("neck_clean: %s に残っていた、首の線の切れ端を直しました（%d 画素。x %d〜%d y %d〜%d。消した %d・服の色で塗った %d）" % (
        name_, int(red_.sum()), xs_.min(), xs_.max(), ys_.min(), ys_.max(), int(out_.sum()), int(inside_.sum())))
    return rgb2_, a_ * (1 - np.clip(soft(out_, 0.7) * 1.6, 0, 1) * (~(inside_ | wide_)))


# char.json の neck_clean: えりの裏（首の後ろに回っている、えりの内側）を、首の下に敷く 1 枚にする（レイヤー「えり裏」。体について動く）。
# 体の絵は、首のあった所が、首の形の穴になっている。止まっていれば首が穴をふさぐが、首は頭について少し動くので（かしげ・横向き）、
# 穴のふちと首の間にすき間が開き、後ろ髪や背景がのぞく。穴を、左右の えり の色でつないで塗った絵を、首の下に置く
def collar_back(rgb_, a_):
    op_ = a_ > 0.5
    ys_, xs_ = np.where(NECK_MASK)
    cx_ = int((xs_.min() + xs_.max()) // 2)
    lim0_, lim1_ = xs_.min() - 60, xs_.max() + 60
    prgb_ = np.zeros_like(rgb_)
    pm_ = np.zeros(a_.shape, bool)
    for y in range(int(ys_.min()), min(int(ys_.max()) + 40, a_.shape[0])):
        row = op_[y]
        if row[cx_]:
            continue                                   # まん中が服 = 穴は、ここで終わり
        lx_ = np.where(row[:cx_])[0]
        rx_ = np.where(row[cx_:])[0]
        if not len(lx_) or not len(rx_):
            continue
        xl_, xr_ = int(lx_.max()), cx_ + int(rx_.min())
        if xl_ < lim0_ or xr_ > lim1_:
            continue                                   # 左右のどちらかに、えりが無い行（えりより上）
        cl_, cr_ = rgb_[y, max(xl_ - 4, 0)], rgb_[y, min(xr_ + 4, a_.shape[1] - 1)]
        a0_, a1_ = max(xl_ - 4, 0), min(xr_ + 5, a_.shape[1])
        t_ = np.linspace(0, 1, a1_ - a0_, dtype=np.float32)[:, None]
        prgb_[y, a0_:a1_] = cl_[None, :] * (1 - t_) + cr_[None, :] * t_
        pm_[y, a0_:a1_] = True
    if not pm_.any():
        return None
    ys2_, xs2_ = np.where(pm_)
    print("えり裏（首の下に敷く絵。neck_clean・neck_back） x %d〜%d y %d〜%d" % (xs2_.min(), xs2_.max(), ys2_.min(), ys2_.max()))
    return prgb_, np.clip(soft(pm_, 0.8) * 1.3 - 0.15, 0, 1) * pm_


# 「首から下だけ」を 1 枚で描かせた絵があれば、首と体をそこから取る（NECKDOWN）。
# 首と体の色・影・線がつながった絵なので、別々に描かせた首より自然になる
if os.environ.get("NECKDOWN"):
    D_rgb, D_a = load(os.environ["NECKDOWN"])
    D_a[D_a < 0.03] = 0
    db, dg, dr = D_rgb[..., 0], D_rgb[..., 1], D_rgb[..., 2]
    # 服が白〜クリーム色のキャラは、赤と緑の差の下限を上げる（tone_rg_min）。肌の影が、青の少ない濃い色のキャラは、青の下限を下げる（tone_bmin。build.py と同じ項目）
    toneD = (dr > 200) & (dg > 125) & (db > CHAR.get('tone_bmin', 130)) & (dr - dg > CHAR.get('tone_rg_min', 8)) & (D_a > 0.9)
    old_a = L["40_neck"][1]
    oy_, ox_ = np.where(old_a > 0.5)
    lab_n, lab_ = cv2.connectedComponents(toneD.astype(np.uint8))
    ids_, cnt_ = np.unique(lab_[oy_, ox_][lab_[oy_, ox_] > 0], return_counts=True)
    K = lab_ == ids_[np.argmax(cnt_)]                       # 首の肌
    cloth = largest(cv2.morphologyEx((~toneD & (D_a > 0.5)).astype(np.uint8), cv2.MORPH_OPEN, ell(15)))
    # char.json の neck_clean: 首の輪郭線のうち、えりの裏（首の後ろに回るえり）と接している所は、服とつながった塊になるので「服」に入ってしまう。
    # すると、その線は体の絵に残り（動かない赤い線）、首のほうは、えりの手前で輪郭線が途切れる。首の肌のすぐ外の、線の色（赤茶）の画素は、首に入れる
    if CHAR.get("neck_clean"):
        nline_ = (cv2.dilate(K.astype(np.uint8), ell(int(CHAR.get("neck_grow", 15)))) > 0) & (D_a > 0.5) & (dr - db > 20) & (dr - dg > 20) & (dr > 90)
        print("neck_clean: 服から首へ移した、輪郭線の画素", int((cloth & nline_).sum()))
        cloth = cloth & ~nline_
    # 首の肌から、輪郭線のぶんだけ外へ広げて首にする。線の太い絵柄では、線の外側が体のレイヤーに細い筋で残り、
    # 首をかしげると、えりの中に動かない線が見える。char.json の neck_grow（既定 15）を大きくする
    ring_ = (cv2.dilate(K.astype(np.uint8), ell(int(CHAR.get("neck_grow", 15)))) > 0) & (D_a > 0.05)
    if CHAR.get("neck_line_lum"):
        # char.json の neck_line_lum: 広げた所へ入れるのは、首の輪郭線（この明るさより暗い画素）だけにする（書かなければ前と同じ）。
        # 輪郭線を黒で描く絵柄で、えり・ヘッドホンなどが首に接しているキャラ用（輪郭線が赤茶の絵柄は neck_clean）。
        #  (1) 「服」は、肌でない所を 15 画素で開いた、いちばん大きい塊。えりがリブ編みで、リブの影の線が肌に近い色だと、えりが影の線で
        #      細かく切れて、首に接した切れ端が服から外れ、首のレイヤーに入る（首をかしげると、えりの切れ端が首と一緒に動く）。
        #      → 明るい画素（えり）は、首に入れない
        #  (2) 輪郭線が、暗い色の服（首の後ろを回るバンド・えりの裏）と接している所は、線と服が 1 つの太い塊になって「服」に入り、
        #      線が体の絵に残る（首の輪郭線に切れ目ができ、首をかしげると、体に残った線の切れ端が見える）。
        #      → char.json の neck_line_black（黒の明るさの上限。書かなければ、しない）: 首の肌の「左右の隣」にある、これより暗い画素（黒い輪郭線）は、
        #        服から外して、首に入れる。こげ茶の服（明るさ 30 前後）は入れない値にする（線の芯は 0〜6。例 12）。
        #        左右の隣だけにするのは、首の下にある服のふちの線（服のもの）を、首へ取らないため
        lum_ = 0.114 * db + 0.587 * dg + 0.299 * dr
        dark_ = ring_ & (lum_ < float(CHAR["neck_line_lum"]))
        edge_ = (cv2.dilate(K.astype(np.uint8), ell(7)) > 0) & (D_a > 0.05)      # 肌と線の境目の、色のまじった画素
        if CHAR.get("neck_line_black"):
            gw_ = int(CHAR.get("neck_grow", 15))
            side_ = cv2.dilate(K.astype(np.uint8), np.ones((1, 2 * gw_ + 1), np.uint8)) > 0
            black_ = ring_ & side_ & (lum_ < float(CHAR["neck_line_black"]))
            cloth = cloth & ~black_
            print("neck_line_black: 服から外して首に入れた輪郭線の画素 %d" % int(black_.sum()))
        grown_ = ring_ & ~cloth & (K | dark_ | edge_)
        print("neck_line_lum: 首に入れた輪郭線の画素 %d" % int((dark_ & ~cloth & ~K).sum()))
    else:
        grown_ = ring_ & ~cloth
    neckm = fill_holes(grown_)
    neckm = largest(neckm)
    bodym = largest((D_a > 0.02) & ~neckm)
    # 襟の下へ少し塗り足す（列ごとに、首の下端の色を下へ延ばす）
    # char.json の neck_clean: 首と、塗り足した所の境目を消す。
    #   首の下の端（えりの線と接する所）の数画素は、えりの線とにじんだ色（明るい線）になっている。前は、下の端から 6 画素上の色を延ばし、
    #   塗り足した所だけを横にならしていたので、境目に明るい線と、色の段が残った。ふだんは えりに隠れているが、首をかしげると、えりの上に出てきて、
    #   首の下に、もう 1 枚 首があるように見える。→ 下の端から 14 画素上の色を、境目の帯ごと下へ延ばし、ならしは、境目から離れるほど強くする
    nk = D_rgb.copy()
    grow_ = np.zeros((Hh, Ww), bool)
    clean_ = bool(CHAR.get("neck_clean"))
    up_ = 14 if clean_ else 6
    deep_ = np.zeros((Hh, Ww), np.float32)                  # 延ばしはじめた行からの距離（neck_clean）
    skrun_ = np.zeros((Hh, Ww), bool)                       # 肌の色を延ばした所（neck_clean）
    okc_ = (toneD | nline_) if clean_ else None            # 延ばしてよい色（肌・首の輪郭線）。えりの黒い線・ボタンの色は、延ばさない
    for x in np.where(neckm.any(0))[0]:
        col = np.where(neckm[:, x])[0]
        b_ = col.max()
        s_ = max(b_ - up_, col.min())
        band_ok_ = clean_
        if clean_:
            # 下の端から 14 画素より上で、いちばん下にある画素。肌を先に探し、無い列（輪郭線の列）だけ、線の色を使う
            # （えりの切れ込みの中では、えりの黒い線と肌のまじった暗い画素が「線の色」に見える。それを延ばすと、切れ込みに暗い縦の筋が出る）
            s0_ = s_
            c0_ = int(col.min())
            sk_r = np.where(toneD[c0_:s0_ + 1, x])[0]
            ln_w = okc_[max(c0_, s0_ - 40):s0_ + 1, x]
            skin_s_ = True
            if len(sk_r) and s0_ - (c0_ + sk_r.max()) <= 40:
                s_ = c0_ + int(sk_r.max())                              # 肌
            elif ln_w.mean() >= 0.6:
                s_ = max(c0_, s0_ - 40) + int(np.where(ln_w)[0].max())  # 輪郭線の列（上から下まで、線の色が続いている）
                skin_s_ = False
            elif len(sk_r):
                s_ = c0_ + int(sk_r.max())                              # 切れ込みの底など（ボタンの色がまじった所）: その列の、いちばん下の肌から延ばす
            else:
                s_ = max(b_ - 6, c0_); band_ok_ = False                 # 見つからない列は、前と同じ
        nk[b_ + 1:b_ + 61, x] = D_rgb[s_, x]
        grow_[b_ + 1:b_ + 61, x] = True
        if band_ok_:
            nk[s_ + 1:b_ + 1, x] = D_rgb[s_, x]
            n_ = min(b_ + 61, Hh) - (s_ + 1)
            deep_[s_ + 1:s_ + 1 + n_, x] = np.arange(1, n_ + 1)
            if skin_s_:
                skrun_[s_ + 1:s_ + 1 + n_, x] = True
    grow_ &= bodym
    # 塗り足した所は、列ごとに色を延ばしただけなので縦すじになる。横にならす（襟に隠れる所だが、体が動くと少し見える）
    nb_ = cv2.GaussianBlur(nk * grow_[..., None], (0, 0), 14) / np.maximum(cv2.GaussianBlur(grow_.astype(np.float32), (0, 0), 14), 1e-3)[..., None]
    if clean_:
        w_ = np.clip((deep_ - up_) / 40.0, 0, 1)[..., None]
        nk = np.where(grow_[..., None], nk * (1 - w_) + nb_ * w_, nk)
        # 肌の色を延ばした所（境目の帯と、えりの切れ込みの中）も、となりの列と色が段になるので、延ばしはじめから離れるほど、肌どうしでならす（輪郭線の列は、ならさない）
        sr_ = skrun_ & (neckm | grow_)
        nb2_ = cv2.GaussianBlur(nk * sr_[..., None], (0, 0), 5) / np.maximum(cv2.GaussianBlur(sr_.astype(np.float32), (0, 0), 5), 1e-3)[..., None]
        w2_ = (np.clip(deep_ / 10.0, 0, 1) * sr_)[..., None]
        nk = nk * (1 - w2_) + nb2_ * w2_
    else:
        nk = np.where(grow_[..., None], nb_, nk)
    na_ = np.maximum(soft(neckm, 0.8) * D_a, soft(grow_, 1.0))
    # 首と、襟の下へ塗り足した部分の間に残る細い筋を埋める
    seam_ = (cv2.morphologyEx((neckm | grow_).astype(np.uint8), cv2.MORPH_CLOSE, ell(11)) > 0) & ~(cv2.erode((neckm | grow_).astype(np.uint8), ell(3)) > 0)
    nk = extend_fill(nk, (neckm | grow_) & ~seam_, seam_)
    na_ = np.maximum(na_, soft(cv2.morphologyEx((neckm | grow_).astype(np.uint8), cv2.MORPH_CLOSE, ell(11)) > 0, 0.8) * (cv2.dilate((na_ > 0.5).astype(np.uint8), ell(9)) > 0))
    # char.json の neck_clean: 首のふちの外に出る、明るい細い筋を消す。
    # 上の「筋を埋める」は、首の形の中を全部 不透明にするので、描かせた絵では半透明だった「輪郭線の外側のふち」まで不透明になる。
    # そこの色は、背景を抜いたあとの残り（明るい色）なので、輪郭線の外に、明るい筋が 1 本出る（首が二重に見える原因の 1 つ）。
    # ふち（描かせた絵が半透明の所）は、描かせた絵の不透明度に戻し、色は、すぐ内側の線の色にする。襟の下へ塗り足した所のそばは、そのまま
    if CHAR.get("neck_clean"):
        half_ = neckm & (D_a < 0.9) & ~(cv2.dilate(grow_.astype(np.uint8), ell(7)) > 0)
        na_ = np.where(half_, np.minimum(na_, D_a), na_)
        nk = extend_fill(nk, (neckm & (D_a >= 0.9)) | grow_, half_)
        print("neck_clean: 首のふちの半透明の画素", int(half_.sum()))
        # 輪郭線の色をそろえる。描かせた絵は、同じ 1 本の線でも、途中から明るい赤になることがある（えりのそばの数十画素）。
        # 行ごと・左右ごとに、線の芯（いちばん緑の少ない画素）の色を見て、基準（線の芯の色の中央値）より明るければ、線の濃さに比例して基準へ寄せる
        band_ = (neckm | grow_) & ~(cv2.erode((neckm | grow_).astype(np.uint8), ell(31)) > 0)      # ふちから 15 画素の帯
        lt_ = np.clip((170.0 - nk[..., 1]) / 130.0, 0, 1) * band_                                  # 線らしさ（緑: 肌 170 以上 → 0、線 40 → 1）
        lt_ = lt_ * ((nk[..., 2] - nk[..., 0] > 20) & (nk[..., 2] - nk[..., 1] > 20))              # 赤茶の線だけ（えりの黒い線とまじった画素は、入れない）
        cx_n = int(np.where(neckm.any(0))[0].mean())
        cores_ = []
        rows_ = np.where(band_.any(1))[0]
        for y in rows_:
            for sl in (slice(0, cx_n), slice(cx_n, Ww)):
                t_ = lt_[y, sl]
                if t_.max() > 0.6:
                    cores_.append((y, sl, nk[y, sl][int(np.argmax(t_))].copy()))
        if cores_:
            ref_ = np.median(np.array([c for _, _, c in cores_]), axis=0)
            nfix_ = 0
            for y, sl, c_ in cores_:
                if c_[2] > ref_[2] + 25:                                                       # 赤が、基準より明るい行
                    nk[y, sl] = np.clip(nk[y, sl] + lt_[y, sl][:, None] * (ref_ - c_)[None, :], 0, 255)
                    nfix_ += 1
            print("neck_clean: 輪郭線の色をそろえた行", nfix_, "基準の色(BGR)", ref_.round(0))
    NECK_MASK = neckm
    L["40_neck"] = (nk, na_)
    ba = soft(bodym, 0.8) * D_a
    inner_ = cv2.erode(bodym.astype(np.uint8), ell(5)) > 0
    ba[inner_] = D_a[inner_]
    L["41_body"] = cut_neck_slivers(D_rgb, ba, "体")
    print("neckdown: neck px", int(neckm.sum()), "body px", int(bodym.sum()))
# 「首だけ」を描かせた絵があれば、あごに隠れる側まで描いてあるそれを使う（NECK_ONLY）
if os.environ.get("NECK_ONLY") and not os.environ.get("NECKDOWN"):
    nk_rgb, nk_a = load(os.environ["NECK_ONLY"])
    nk_a[nk_a < 0.03] = 0
    L["40_neck"] = (nk_rgb, nk_a)
ear_rgb, ear_a = L["11_ears"]
# (名前, パス, 素材, 非表示)   下から上の順
spec = [
    ("後ろ髪2", "後ろ髪", L["back"], False),
    ("後ろ髪1R", "後ろ髪", L["tail_R"], False),
    ("後ろ髪1L", "後ろ髪", L["tail_L"], False),
    ("首", "上半身", L["40_neck"], False),
    ("シャツ", "上半身", L["41_body"], False),
    ("カーディガン影R", "カーディガン", None, False),
    ("カーディガン影L", "カーディガン", None, False),
    ("耳R", "頭/耳", (ear_rgb, ear_a * (xx < cxm)), False),
    ("耳L", "頭/耳", (ear_rgb, ear_a * (xx >= cxm)), False),
    ("輪郭ベース", "頭/顔/輪郭", L["10_head"], False),
    ("鼻", "頭/顔/鼻", L["12_nose"], False),
    ("口内", "頭/顔/口", L["mouth_in"], True),
    ("舌", "頭/顔/口", L["tongue"], True),
    ("下唇線", "頭/顔/口", L["14_mouth_line"], False),
    ("リップ", "頭/顔/口", L.get("17_lip"), False),
] + [("口コマ" + k_, "頭/顔/口", MOUTH_FRAMES[k_], False) for k_ in sorted(MOUTH_FRAMES)] + [("口キー_" + k_, "頭/顔/口", KEY_MOUTH_IMG[k_], True) for k_ in KEY_MOUTH_IMG]
for tom, mine in (("R", "L"), ("L", "R")):       # エンジンの R = 画面左 = こちらの _L
    p = "頭/顔/瞳" + tom
    spec += [
        ("白目" + tom, p, L["20_eye_white_" + mine], False),
        ("瞳ベース" + tom, p, L["21_iris_" + mine], False),
        ("ハイライト1" + tom, p, None, False),
        ("下まつげ" + tom, p, L["23_lash_lower_" + mine], bool(KEY_EYE_IMG)),
        ("二重" + tom, p, L["24_eyelid_crease_" + mine], bool(KEY_EYE_IMG)),
        ("アイライン線" + tom, p, L["22_lash_upper_" + mine], bool(KEY_EYE_IMG)),
    ]
    # キーの形の目（まつげの絵。エンジンが、今のまぶたの線へ変形して重ねる）。under は、下まつげ・目尻の線・二重の線
    # crease は、二重の線（半目のコマから取った 1 本。まつげの下に敷く）
    for k_ in [k2_ for k2_ in ("crease", "under", "corner") if k2_ in KEY_EYE_IMG] + [k2_ for k2_ in KEY_EYE_IMG if k2_ not in ("crease", "under", "corner")]:
        spec.append(("目キー_" + k_ + tom, p, KEY_EYE_IMG[k_][mine], k_ not in ("open", "crease", "under", "corner")))
    # 清書した「閉じた目」「笑って閉じた目」。エンジンが、目が閉じきる直前に、開いた目のパーツと入れ替える（無ければ、今までどおり上まつげを変形する）
    for k_ in sorted(EYE_FRAMES):
        if EYE_FRAMES[k_]:
            spec.append(("目コマ" + k_ + tom, p, EYE_FRAMES[k_][mine], False))
    if EYE_CLOSED:
        spec.append(("閉じ目" + tom, p, EYE_CLOSED[mine], False))
    if EYE_SMILE:
        spec.append(("笑い目" + tom, p, EYE_SMILE[mine], False))
spec += [
    ("眉毛R", "頭/顔/眉毛", L["13_brow_L"], False),
    ("眉毛L", "頭/顔/眉毛", L["13_brow_R"], False),
    ("前髪2", "頭/前髪", HAIR_BASE, False),               # 髪の下地（頭と一緒に動く）
    ("前髪6", "頭/前髪", SIDE_R, False),                  # 画面左の横髪（前髪より大きく揺れる）
    ("前髪7", "頭/前髪", SIDE_L, False),                  # 画面右の横髪
    ("前髪1", "頭/前髪", (fr_rgb, fr_a), False),          # 前髪と頭頂。途中で切ると継ぎ目が出るので切らない
]
# 帽子（頭頂より上へはみ出してよい。頭と一緒に動き、ふちだけ少し揺れる）と、髪飾り（頭について動く。曲げない）
for env_, nm_, path_ in (("HAT", "帽子", "頭/帽子"), ("ORNAMENT", "髪飾り", "頭/ピン留め")):
    if os.environ.get(env_):
        r_, a_ = load(os.environ[env_])
        a_[a_ < 0.03] = 0
        spec.append((nm_, path_, (r_, a_), False))

# ---------- 前髪の影（前髪の形を少し下へずらして、肌に落ちる影にする）
Hf = chin - head_top
bang_a = fr_a if SIDE_R is not None else fr_a * (yy < head_top + 0.62 * Hf)
shad = cv2.warpAffine(bang_a, np.float32([[1, 0, 0], [0, 1, 0.022 * Hf]]), (Ww, Hh))
shad = cv2.GaussianBlur(shad, (0, 0), 0.004 * Hf)
shadow_rgb = np.empty((Hh, Ww, 3), np.float32)
shadow_rgb[:] = (188, 170, 232)                     # BGR。肌より少し暗いピンク
# char.json の bang_shadow: {"color": [R, G, B], "opacity": 0〜1}（書かなければ、ピンク・0.75 = 前と同じ）。
# 肌が黄みのあるクリーム色で、髪の影を顔に落とさない絵柄（セル塗り）では、ピンクの影が、目のまわりの薄紫のしみに見える。
# 基準画像に影が無ければ opacity 0、あれば、その影の色を color に書く
BS_ = CHAR.get("bang_shadow") or {}
if BS_.get("color"):
    shadow_rgb[:] = tuple(float(v_) for v_ in BS_["color"][::-1])
spec.insert([n_ for n_, *_ in spec].index("輪郭ベース") + 1, ("前髪1影", "頭/顔/輪郭/前髪影", (shadow_rgb, shad * 0.9), False, {"opacity": float(BS_.get("opacity", 0.75))}))
if EYE_MARKS is not None:
    # 目の下の印（char.json の eye_marks）: 肌のすぐ上・前髪の影の下。目のパーツ（白目・まつげ）より下なので、目に重なる所は、目に隠れる
    spec.insert([n_ for n_, *_ in spec].index("輪郭ベース") + 1, ("目の下の印", "頭/顔/印", EYE_MARKS, False))
# ---------- 表情差分（乗算で顔に重ねる。顔の形での切り抜きはエンジンがする）
def eye_c(nm):
    ys_, xs_ = np.where(L[nm][1] > 0.5)
    return float(xs_.mean()), float(ys_.mean())
blush = np.zeros((Hh, Ww), np.float32)
lines = np.zeros((Hh, Ww), np.uint8)
for nm in ("21_iris_L", "21_iris_R"):
    ex_, ey_ = eye_c(nm)
    ccx, ccy = ex_, ey_ + 0.135 * Hf
    blush = np.maximum(blush, np.exp(-(((xx - ccx) / (0.105 * Hf)) ** 2 + ((yy - ccy) / (0.045 * Hf)) ** 2)))
    for k_ in range(-2, 3):                          # 斜めの短い線
        x0_ = ccx + k_ * 0.028 * Hf
        cv2.line(lines, (int(x0_ + 0.012 * Hf), int(ccy - 0.022 * Hf)), (int(x0_ - 0.012 * Hf), int(ccy + 0.022 * Hf)), 255, max(2, int(0.0045 * Hf)), cv2.LINE_AA)
blush_rgb = np.empty((Hh, Ww, 3), np.float32); blush_rgb[:] = (170, 150, 255)
la = lines.astype(np.float32) / 255
blush_rgb = blush_rgb * (1 - la[..., None]) + np.array([140, 105, 240], np.float32) * la[..., None]
spec.append(("赤面", "表情差分", (blush_rgb, np.clip(blush * 0.85 + la * 0.6, 0, 1)), True, {"opacity": 0.7, "blend": "multiply"}))
headm = soft(L["10_head"][1] > 0.3, 2.0)
# パーツ分け済みの PSD（最初のモデル）と同じ作り: 額から目の下まではっきり掛かり、鼻の下で消える（顔の高さの 56%〜84% で薄くなる）
def shade_layer(name, bgr, y_full=0.56, y_end=0.84, opacity=0.6):
    t_ = (yy - head_top) / float(Hf)
    g_ = np.clip((y_end - t_) / (y_end - y_full), 0, 1)
    g_ = g_ * g_ * (3 - 2 * g_)
    c_ = np.empty((Hh, Ww, 3), np.float32); c_[:] = bgr
    spec.append((name, "表情差分", (c_, (g_ * headm).astype(np.float32)), True, {"opacity": opacity, "blend": "multiply"}))
sh_ = CHAR.get("shade", {})
shade_layer("青ざめ", sh_.get("pale", (170, 110, 90)))            # BGR。青みのある影
shade_layer("黒", sh_.get("dark", (35, 22, 28)))                  # 目のまわりまで落ちる暗い影
shade_layer("蔑む", sh_.get("scorn", (150, 105, 120)), 0.50, 0.80)  # 額から目にかかる影

# ---------- 涙・汗（そのものだけを透過で描かせた絵。肌の面と一緒に動く）
if TEARS_EYE:      # 片目の拡大の上に描かせた涙（左右の目の位置へ道具が置く）。全体の絵に位置を合わせて描かせた涙（20）は、ずれるので使わない
    tr_ = np.where((TEARS_EYE["L"][1] >= TEARS_EYE["R"][1])[..., None], TEARS_EYE["L"][0], TEARS_EYE["R"][0])
    ta_ = np.maximum(TEARS_EYE["L"][1], TEARS_EYE["R"][1])
    sh_ = CHAR.get("tears_shift")
    if sh_:
        Mt = np.float32([[1, 0, sh_[0]], [0, 1, sh_[1]]])
        tr_, ta_ = cv2.warpAffine(tr_, Mt, (Ww, Hh)), cv2.warpAffine(ta_, Mt, (Ww, Hh))
    spec.append(("涙", "表情差分", (tr_, ta_), True))
for env_, nm_ in (("TEARS", "涙"), ("SWEAT", "汗")):
    if env_ == "TEARS" and TEARS_EYE:
        continue
    if os.environ.get(env_):
        r_, a_ = load(os.environ[env_])
        a_[a_ < 0.03] = 0
        # しずく以外に残った小さなごみを落とす
        n_, lab_, st_, _ = cv2.connectedComponentsWithStats((a_ > 0.1).astype(np.uint8))
        a_ = a_ * (cv2.dilate(np.isin(lab_, [i for i in range(1, n_) if st_[i, cv2.CC_STAT_AREA] >= 300]).astype(np.uint8), ell(5)) > 0)
        # 描かれた位置が指示とずれたときの直し（char.json の tears_shift・sweat_shift。[x, y]、3 倍の絵での画素）
        sh_ = CHAR.get(env_.lower() + "_shift")
        if sh_:
            Mt = np.float32([[1, 0, sh_[0]], [0, 1, sh_[1]]])
            r_, a_ = cv2.warpAffine(r_, Mt, (Ww, Hh)), cv2.warpAffine(a_, Mt, (Ww, Hh))
        spec.append((nm_, "表情差分", (r_, a_), True))

# ---------- 瞳の差分（ハート・しいたけ・ぐるぐる・闇）。「瞳を 1 つ大きく描かせた絵」を、左右の瞳の位置と大きさへ合わせて置く。
# 瞳の外形とふちは、もとの瞳のものをそのまま使う（描かせた絵の縦横比が少し違っても、目の中での大きさと輪郭が変わらない）
def iris_variant(path, nm):
    v = imread_rgba(path)
    if v is None or v.ndim != 3 or v.shape[2] != 4:
        raise SystemExit("瞳の差分の絵が読めないか、透過ではありません: " + path)
    va = v[..., 3].astype(np.float32) / 255
    ys_, xs_ = np.where(va > 0.5)
    v = v[ys_.min():ys_.max() + 1, xs_.min():xs_.max() + 1].astype(np.float32)
    ch_, cw_ = v.shape[:2]
    irgb, ia = L[nm]
    ys_, xs_ = np.where(ia > 0.5)
    tx0, tx1, ty0, ty1 = xs_.min(), xs_.max() + 1, ys_.min(), ys_.max() + 1
    s_ = max((tx1 - tx0) / float(cw_), (ty1 - ty0) / float(ch_)) * 1.02     # 瞳をすっかり覆う大きさ
    nw, nh = int(round(cw_ * s_)), int(round(ch_ * s_))
    pm = np.dstack([v[..., :3] * (v[..., 3:] / 255), v[..., 3]])
    pm = cv2.resize(pm, (nw, nh), interpolation=cv2.INTER_AREA)
    px0, py0 = int(round((tx0 + tx1) / 2 - nw / 2)), int(round((ty0 + ty1) / 2 - nh / 2))
    full = np.zeros((Hh, Ww, 4), np.float32)
    sx0, sy0 = max(0, -px0), max(0, -py0)
    full[max(0, py0):py0 + nh, max(0, px0):px0 + nw] = pm[sy0:, sx0:][:Hh - max(0, py0), :Ww - max(0, px0)]
    fa = full[..., 3] / 255
    frgb = np.where(fa[..., None] > 1e-3, full[..., :3] / np.maximum(fa[..., None], 1e-3), 0)
    frgb = extend_fill(frgb, fa > 0.5, ia > 0.02)
    # ふちは元の瞳へなめらかに戻す
    d_ = cv2.distanceTransform((ia > 0.5).astype(np.uint8), cv2.DIST_L2, 5)
    rim = np.clip(1 - d_ / (0.07 * (tx1 - tx0)), 0, 1)[..., None]
    rim = rim * rim * (3 - 2 * rim)
    return frgb * (1 - rim) + irgb * rim, ia.copy()

for env_, nm_ in (("IRIS_HEART", "ハート"), ("IRIS_STAR", "しいたけ"), ("IRIS_SWIRL", "ぐるぐる"), ("IRIS_DARK", "闇")):
    if os.environ.get(env_):
        for tom, mine in (("R", "L"), ("L", "R")):
            spec.append((nm_ + tom, "表情差分", iris_variant(os.environ[env_], "21_iris_" + mine), True))

# ---------- 揺れ物など、追加で描かせて置いた絵（char.json の extras.layers。絵は pipeline.py place が <名前>_placed.png にしたもの）
#   {"name": レイヤー名, "job": 番号, "replace": 置き換えるレイヤー名, "path": パス（省略で、置き換えるレイヤーと同じ）}
#   同じ replace を持つものを、書いた順（下から上）に、置き換えるレイヤーの場所へ入れる。絵が 1 枚でも足りなければ、その組は置き換えない
EXTRAS = CHAR.get("extras") or {}
EXTRA_NAMES = set()
if os.environ.get("EXTRAS_DIR"):
    groups = {}
    for e_ in EXTRAS.get("layers", []):
        if e_.get("replace"):
            groups.setdefault(e_["replace"], []).append(e_)
    for rep_, es_ in groups.items():
        # extras.jobs に、まだその番号が無いとき（"dump": true で、見本のもとだけ先に書き出すとき）は、絵が無い物として扱う（止まらない）
        files_ = [os.path.join(os.environ["EXTRAS_DIR"], (EXTRAS.get("jobs", {}).get(e_["job"]) or {}).get("out", "_no_job_%s" % e_["job"]) + "_placed.png") for e_ in es_]
        names_ = [n_ for n_, *_ in spec]
        # "dump": 置き換える前のレイヤーを、3 倍の絵と同じ大きさで作業フォルダへ書き出す（_orig_<番号>_3x.png）。
        # 見本にするため。もとの絵には別のレイヤーの物（体の絵の首など）が入っていて、それを見本にすると、描かせた絵にも入ってしまう
        for e_ in es_:
            if e_.get("dump") and rep_ in names_ and spec[names_.index(rep_)][2] is not None and e_["name"] not in EXTRA_NAMES:
                cv2.imwrite(os.path.join(os.environ["EXTRAS_DIR"], "_orig_%s_3x.png" % e_["job"]), rgba(*spec[names_.index(rep_)][2]))
                print("extras: %s を _orig_%s_3x.png に書き出しました（見本のもと）" % (rep_, e_["job"]))
        if rep_ not in names_ or not all(os.path.isfile(f_) for f_ in files_):
            print("extras: %s は置き換えません（絵が足りないか、レイヤーがありません）" % rep_)
            continue
        i_ = names_.index(rep_)
        path_ = spec[i_][1]
        new_ = []
        for e_, f_ in zip(es_, files_):
            r_, a_ = load(f_)
            a_[a_ < 0.03] = 0
            if rep_ == "シャツ":
                r_, a_ = cut_neck_slivers(r_, a_, e_["name"])  # 体を描き直させた絵にも、首の線の切れ端が写って残る（char.json の neck_clean）
            new_.append((e_["name"], e_.get("path", path_), (r_, a_), False))
            EXTRA_NAMES.add(e_["name"])
        spec[i_:i_ + 1] = new_
        print("extras: %s -> %s" % (rep_, " ".join(n_ for n_, *_ in new_)))
    # "after": 置き換えずに、指定したレイヤーのすぐ上へ足す（アホ毛など、もとのレイヤーに入れずに別に描かせた物）
    #   {"name": レイヤー名, "job": 番号, "after": その上に重ねるレイヤー名, "path": パス（省略で、そのレイヤーと同じ）,
    #    "cut_from": [レイヤー名...]（その絵の形を、挙げたレイヤーから抜く。髪の下地に残ったアホ毛の写しなど。揺らすと、下に動かない写しが見えるため）}
    for e_ in EXTRAS.get("layers", []):
        if not e_.get("after"):
            continue
        f_ = os.path.join(os.environ["EXTRAS_DIR"], (EXTRAS.get("jobs", {}).get(e_["job"]) or {}).get("out", "_no_job_%s" % e_["job"]) + "_placed.png")
        names_ = [n_ for n_, *_ in spec]
        if e_["after"] not in names_ or not os.path.isfile(f_):
            print("extras: %s は足しません（絵が無いか、レイヤーがありません）" % e_["name"])
            continue
        i_ = names_.index(e_["after"])
        r_, a_ = load(f_)
        a_[a_ < 0.03] = 0
        for c_ in e_.get("cut_from", []):
            if c_ in names_ and spec[names_.index(c_)][2] is not None:
                j_ = names_.index(c_)
                cr_, ca_ = spec[j_][2]
                spec[j_] = spec[j_][:2] + ((cr_, ca_ * (1 - np.clip(soft(cv2.dilate((a_ > 0.3).astype(np.uint8), ell(9)), 1.5), 0, 1))),) + spec[j_][3:]
        # "behind": {"box": [x0, y0, x1, y1], "cut": [x0, y0, x1, y1]}（その絵の、不透明な所の箱の中の割合。書かなければ、分けない = 前と同じ）。
        # 絵のうち、box に入る所を、別のレイヤー「<名前>奥」にして、"after" のレイヤーの「すぐ下」へ入れる。もとのレイヤー（すぐ上）からは、cut に入る所を抜く。
        # 耳たぶを通る輪（ピアス）: 輪の奥の側の弧を耳の下へ、手前の側の弧を耳の上へ置くと、輪が、耳たぶを通って見える。輪の全部を耳の上に置くと、
        # 輪が、耳たぶの前に貼り付いて見える（chiwa）。
        # cut は、box の中で、"after" のレイヤー（耳）に隠れる所だけにする（省略すると box と同じ）。box を cut より広く取ると、その差の所は、
        # 奥と手前の両方に同じ絵が入る。見えている所で 2 枚をぴったり切り分けると、つなぎ目に、薄い筋が出た（2 枚を別々に拡大・縮小するため）
        if e_.get("behind"):
            ysb_, xsb_ = np.where(a_ > 0.5)
            if len(ysb_):
                bx0_, by0_, bw_, bh_ = int(xsb_.min()), int(ysb_.min()), int(xsb_.max() - xsb_.min() + 1), int(ysb_.max() - ysb_.min() + 1)
                bh_spec_ = e_["behind"] if isinstance(e_["behind"], dict) else {"box": e_["behind"]}

                def frac_mask_(f_):
                    m_ = np.zeros(a_.shape, bool)
                    m_[max(0, int(round(by0_ + float(f_[1]) * bh_))):int(round(by0_ + float(f_[3]) * bh_)), max(0, int(round(bx0_ + float(f_[0]) * bw_))):int(round(bx0_ + float(f_[2]) * bw_))] = True
                    return m_
                mb_ = frac_mask_(bh_spec_["box"])
                mc_ = frac_mask_(bh_spec_.get("cut", bh_spec_["box"])) & mb_
                spec.insert(i_, (e_["name"] + "奥", e_.get("path", spec[i_][1]), (r_, a_ * mb_), False))
                EXTRA_NAMES.add(e_["name"] + "奥")
                print("extras: %s の下に %s（%d 画素。手前から抜いた所 %d 画素）" % (e_["after"], e_["name"] + "奥", int((a_ * mb_ > 0.5).sum()), int((a_ * mc_ > 0.5).sum())))
                a_ = a_ * ~mc_
                i_ += 1
        spec.insert(i_ + 1, (e_["name"], e_.get("path", spec[i_][1]), (r_, a_), False))
        EXTRA_NAMES.add(e_["name"])
        print("extras: %s の上に %s" % (e_["after"], e_["name"]))

# えりの裏を、首の下に敷く（char.json の neck_clean。体の絵が決まったあとで作る）。
# char.json の neck_back: これだけを使う（neck_clean のほかの直しは、輪郭線が赤茶の絵柄用で、服が赤・肌色・クリーム色のキャラでは使えない。
# 首の後ろを回るバンド・えりがあるキャラは、首をかしげると、首と、バンドの切り口の間に、すき間が開いて、背景や後ろ髪がのぞく）
if (CHAR.get("neck_clean") or CHAR.get("neck_back")) and NECK_MASK is not None:
    names_ = [n_ for n_, *_ in spec]
    if "シャツ" in names_ and "首" in names_ and spec[names_.index("シャツ")][2] is not None:
        cb_ = collar_back(*spec[names_.index("シャツ")][2])
        if cb_ is not None:
            spec.insert(names_.index("首"), ("えり裏", "上半身", cb_, False))

# ---------- 毛束に分けた髪（tools/hairlocks.py の出力。環境変数 HAIR_LOCKS = hair_locks.json）
# 髪を「毛束 1 つ = レイヤー 1 枚」にしたもの。前髪・横髪・髪の下地・後ろ髪のレイヤーを、毛束のレイヤーに置き換える。
# 絵は、3 倍の絵の座標での「切り出した絵 + 左上の位置」で持つ（毛束が多いので、1 枚ずつ全体の大きさの絵にはしない）
class Sparse:
    def __init__(self, path, x, y):
        im = cv2.imread(path, cv2.IMREAD_UNCHANGED).astype(np.float32)
        self.rgb, self.a, self.x, self.y = im[..., :3], im[..., 3] / 255.0, int(x), int(y)

    def full_alpha(self):
        f = np.zeros((Hh, Ww), np.float32)
        h_, w_ = self.a.shape
        x0, y0, x1, y1 = max(self.x, 0), max(self.y, 0), min(self.x + w_, Ww), min(self.y + h_, Hh)
        f[y0:y1, x0:x1] = self.a[y0 - self.y:y1 - self.y, x0 - self.x:x1 - self.x]
        return f


def place_sparse(sp):
    """切り出した絵を、モデルの座標へ縮めて置く。返すのは（色, 不透明度, 左上 x, 左上 y）。y は余白 PADY を足した値"""
    pm = np.dstack([sp.rgb * sp.a[..., None], sp.a * 255]).astype(np.float32)
    fx0, fy0 = ox + S * sp.x, oy + PADY + S * sp.y
    ix0, iy0 = int(np.floor(fx0)), int(np.floor(fy0))
    w_, h_ = int(np.ceil(sp.a.shape[1] * S + 2)), int(np.ceil(sp.a.shape[0] * S + 2))
    M_ = np.float32([[S, 0, fx0 - ix0], [0, S, fy0 - iy0]])
    sm = cv2.warpAffine(cv2.resize(pm, None, fx=1, fy=1), M_, (w_, h_), flags=cv2.INTER_AREA if S < 0.6 else cv2.INTER_LINEAR)
    al = sm[..., 3] / 255
    return np.where(al[..., None] > 1e-4, sm[..., :3] / np.maximum(al[..., None], 1e-4), 0), al, ix0, iy0


LOCK_META = {}
if os.environ.get("HAIR_LOCKS") and os.path.isfile(os.environ["HAIR_LOCKS"]):
    man_ = json.load(open(os.environ["HAIR_LOCKS"], encoding="utf-8"))
    hd_ = os.path.dirname(os.environ["HAIR_LOCKS"])
    sp_ = lambda e_: Sparse(os.path.join(hd_, e_["file"]), e_["x"], e_["y"])
    names_ = [n_ for n_, *_ in spec]
    rigid_ = []
    # 房（tools/hairclumps.py が、毛束を前髪 5・横髪 4・後ろ髪 8 くらいにまとめたもの）があれば、毛束の代わりに房を入れる。
    # 房のモデルでは、前髪の下地は入れない（房のすき間からは、顔が見えるのが正しい）。HAIR_CLUMPS=0 で、毛束のまま
    CLUMP_ = bool(man_.get("clumps_front") or man_.get("clumps_back")) and os.environ.get("HAIR_CLUMPS", "1") != "0"
    if CLUMP_:
        man_ = dict(man_, front=man_.get("clumps_front", []), back=man_.get("clumps_back", []))
        man_.pop("front_base", None); man_.pop("back_under", None)
        if man_.get("clump_front_top"):
            man_["front_base"] = man_["clump_front_top"]          # 頭頂の下地（房の根元の下。頭に付けたまま）
        if man_.get("clump_back_under"):
            man_["back_under"] = man_["clump_back_under"]         # 後ろ髪の下地（内側の髪。房と同じように曲げる）
    if man_.get("back"):
        new_ = []
        if man_.get("back_under"):
            new_.append((man_["back_under"]["name"], "後ろ髪", sp_(man_["back_under"]), False))
        if man_.get("back_cap"):
            new_.append(("後頭部", "後ろ髪", sp_(man_["back_cap"]), False))
        new_ += [(e_["name"], "後ろ髪", sp_(e_), False) for e_ in man_["back"]]
        i_ = names_.index("後ろ髪2")
        spec[i_:i_ + 1] = new_
    if man_.get("front"):
        names_ = [n_ for n_, *_ in spec]
        i_ = names_.index("前髪2")
        fr_ = [sp_(e_) for e_ in man_["front"]]
        new_ = []
        if man_.get("front_base"):
            new_.append((man_["front_base"]["name"], "頭/前髪", sp_(man_["front_base"]), False))
        new_ += [(e_["name"], "頭/前髪", f_, False) for e_, f_ in zip(man_["front"], fr_)]
        spec[i_:i_ + 4] = new_                                   # 前髪2・前髪6・前髪7・前髪1 を置き換える
        # 前髪の影は、前髪の毛束（毛先が目より上の束）を全部重ねた形から作り直す
        ba_ = np.zeros((Hh, Ww), np.float32)
        for e_, f_ in zip(man_["front"], fr_):
            if e_["g"] == "bangs":
                ba_ = np.maximum(ba_, f_.full_alpha())
        shad = cv2.GaussianBlur(cv2.warpAffine(ba_, np.float32([[1, 0, 0], [0, 1, 0.022 * Hf]]), (Ww, Hh)), (0, 0), 0.004 * Hf)
        names_ = [n_ for n_, *_ in spec]
        j_ = names_.index("前髪1影")
        spec[j_] = spec[j_][:2] + ((shadow_rgb, shad * 0.9),) + spec[j_][3:]
    # extras.layers の "under": 追加の絵を、房に置き換えたあとのレイヤー（前房08 など）の「すぐ下」へ移す（書かなければ、"after" で入れた場所のまま = 前と同じ）。
    # "after": "前髪1" で足した絵は、前の髪の房の全部より上に来る。アホ毛のように、髪の中から生えている物は、根元の切り口が、髪の上に乗って見える。
    # 根元を覆う房（つむじの巻き毛など）の名前を書いて、その下へ入れる。房の名前は、model.json の hairClumps か、hair/locks/_clumps_front.png で見る
    for e_ in (CHAR.get("extras") or {}).get("layers", []):
        if e_.get("under"):
            names_ = [n_ for n_, *_ in spec]
            if e_["name"] in names_ and e_["under"] in names_:
                it_ = spec.pop(names_.index(e_["name"]))
                spec.insert([n_ for n_, *_ in spec].index(e_["under"]), it_)
                print("extras: %s を、%s のすぐ下へ移しました" % (e_["name"], e_["under"]))
            elif e_["name"] in names_:
                print("extras: %s の under（%s）は、モデルにありません（房の名前を確かめます）" % (e_["name"], e_["under"]))
    for e_ in man_.get("front", []) + man_.get("back", []) + ([man_["back_under"]] if CLUMP_ and man_.get("back_under") else []):
        LOCK_META[e_["name"]] = {"g": e_["g"], "d": e_.get("d", 0), "shared": bool(e_.get("shared")),
                                 "root": [round(ox + S * e_["root"][0], 1), round(oy + S * e_["root"][1], 1)],
                                 "tip": [round(ox + S * e_["tip"][0], 1), round(oy + S * e_["tip"][1], 1)]}
    # 下地（毛束に分ける前の髪の絵の全体）は、エンジンが、毛束と同じ「流れ」で動かす（hairBases）。流れの根元の高さと長さ（hairField）は、モデルの座標へ直す
    HAIR_BASES = {}
    if man_.get("front_base"):
        HAIR_BASES[man_["front_base"]["name"]] = "front"
    if man_.get("back_under"):
        HAIR_BASES[man_["back_under"]["name"]] = "back"
    HAIR_FIELD = {}
    if man_.get("field_front"):
        f_ = man_["field_front"]
        HAIR_FIELD["front"] = {"top": round(oy + S * f_["top"], 1), "bangsLen": round(S * f_["bangs_len"], 1), "sideLen": round(S * f_["side_len"], 1),
                               "sideX0": round(S * f_["side_x0"], 1), "sideX1": round(S * f_["side_x1"], 1)}
    if man_.get("field_back"):
        f_ = man_["field_back"]
        HAIR_FIELD["back"] = {"top": round(oy + S * f_["top"], 1), "len": round(S * f_["len"], 1)}
    print("hair %s: front %d back %d" % ("clumps" if CLUMP_ else "locks", len(man_.get("front", [])), len(man_.get("back", []))))
    # 頭頂の肌を、後頭部の髪の絵で塗る（char.json の head_scalp: true。書かなければ前と同じ）。
    # 上下の回転では、手前の物ほど大きく動くので、下を向くと、前の髪の上の端が頭の肌より下へずれて、頭頂の肌が三日月形にのぞく
    # （帽子の無い、下向きの上限が大きいキャラで、下 25°で見つかった）。前の髪にいつも完全に隠れている所だけを塗るので、正面の見た目は変わらない
    if CHAR.get("head_scalp") and man_.get("front_base") and man_.get("back_cap"):
        names_ = [n_ for n_, *_ in spec]
        if "輪郭ベース" in names_:
            j_ = names_.index("輪郭ベース")
            hr_, ha_ = spec[j_][2]
            base_a_ = sp_(man_["front_base"]).full_alpha()
            cov_ = base_a_.copy()
            for e_ in man_["front"]:
                cov_ = np.maximum(cov_, sp_(e_).full_alpha())
            # 塗るのは、前髪の下地の所（頭頂）と、こめかみの上（眉のまん中の高さより上で、頭の左右の端寄り。斜め下で、頭の端の肌がのぞいた）。
            # 額と、目のまわりは塗らない（前髪・横髪のすき間から見えるのは、肌が正しい。耳の上端までにすると、目尻のすぐ上まで塗った）
            hb_ = np.where((ha_ > 0.5).any(0))[0]
            cxh_, hw_ = (hb_.min() + hb_.max()) / 2.0, (hb_.max() - hb_.min()) / 2.0
            by_ = np.where((L["13_brow_L"][1] > 0.3).any(1))[0]
            ylim_ = (by_.min() + by_.max()) / 2.0 if len(by_) else 0
            side_ = (np.abs(np.arange(Ww, dtype=np.float32)[None, :] - cxh_) > 0.62 * hw_) & (np.arange(Hh)[:, None] < ylim_)
            m_ = ((base_a_ > 0.98) | side_) & (cov_ > 0.98) & (cv2.erode((ha_ > 0.99).astype(np.uint8), ell(13)) > 0)
            m_ = cv2.erode(m_.astype(np.uint8), ell(9)) > 0
            cap_ = sp_(man_["back_cap"])
            cr_ = np.zeros((Hh, Ww, 3), np.float32); ca_ = cap_.full_alpha()
            ch_, cw_ = cap_.a.shape
            x0_, y0_, x1_, y1_ = max(cap_.x, 0), max(cap_.y, 0), min(cap_.x + cw_, Ww), min(cap_.y + ch_, Hh)
            cr_[y0_:y1_, x0_:x1_] = cap_.rgb[y0_ - cap_.y:y1_ - cap_.y, x0_ - cap_.x:x1_ - cap_.x]
            fill_ = np.where(ca_[..., None] > 0.5, cr_, np.median(cr_[ca_ > 0.5], axis=0) if (ca_ > 0.5).any() else 0)
            k_ = cv2.GaussianBlur(m_.astype(np.float32), (0, 0), 4)[..., None]
            spec[j_] = spec[j_][:2] + ((hr_ * (1 - k_) + fill_ * k_, ha_),) + spec[j_][3:]
            print("head_scalp: 頭頂の肌を、後頭部の髪の色で塗った画素", int(m_.sum()))

layers, alpha_of = [], {}
PIN_PIECES = {}                          # ピンごとに分けた髪飾りの、付いている点（モデルの座標。pin_split）
comp = np.zeros((OH + PADY, OW, 3), np.float32)
ca = np.zeros((OH + PADY, OW), np.float32)
for i, (name, path, src, hidden, *ex) in enumerate(spec):
    fn = "L%03d.png" % i
    opt = ex[0] if ex else {}
    OP, BL = opt.get("opacity", 1.0), opt.get("blend", "normal")
    if src is None:                      # エンジンが名前で探すので、透明の小さな画像を置く
        cv2.imwrite(os.path.join(out, "parts", fn), np.zeros((4, 4, 4), np.uint8))
        layers.append(dict(id=i, name=name, path=path, src=fn, x=1498, y=1000, w=4, h=4, opacity=OP,
                           blend=BL, clip=False, hidden=hidden))
        alpha_of[name] = (np.zeros((4, 4), np.float32), 1498, 1000)
        continue
    if isinstance(src, Sparse):
        r_, a_, x0, y0 = place_sparse(src)
        ys_, xs_ = np.where(a_ > 0.004)
        if len(ys_):
            cx0, cy0, cx1, cy1 = xs_.min(), ys_.min(), xs_.max() + 1, ys_.max() + 1
            # モデルの絵の範囲（左右 0〜OW、上は余白まで、下は YMAX）からはみ出す分は切る
            gx0, gy0 = max(x0 + cx0, 0), max(y0 + cy0, 0)
            gx1, gy1 = min(x0 + cx1, OW), min(y0 + cy1, YMAX + PADY)
            if gx1 > gx0 and gy1 > gy0:
                r_, a_ = r_[gy0 - y0:gy1 - y0, gx0 - x0:gx1 - x0], a_[gy0 - y0:gy1 - y0, gx0 - x0:gx1 - x0]
                cv2.imwrite(os.path.join(out, "parts", fn), rgba(r_, a_))
                layers.append(dict(id=i, name=name, path=path, src=fn, x=int(gx0), y=int(gy0) - PADY, w=int(gx1 - gx0), h=int(gy1 - gy0),
                                   opacity=OP, blend=BL, clip=False, hidden=hidden))
                alpha_of[name] = (a_, int(gx0), int(gy0) - PADY)
                aa = a_ * OP
                comp[gy0:gy1, gx0:gx1] = comp[gy0:gy1, gx0:gx1] * (1 - aa[..., None]) + r_ * aa[..., None]
                ca[gy0:gy1, gx0:gx1] = ca[gy0:gy1, gx0:gx1] + aa * (1 - ca[gy0:gy1, gx0:gx1])
                continue
        cv2.imwrite(os.path.join(out, "parts", fn), np.zeros((4, 4, 4), np.uint8))
        layers.append(dict(id=i, name=name, path=path, src=fn, x=1498, y=1000, w=4, h=4, opacity=OP, blend=BL, clip=False, hidden=hidden))
        alpha_of[name] = (np.zeros((4, 4), np.float32), 1498, 1000)
        continue
    rgb, a = place(*src)
    if name == "髪飾り" and CHAR.get("pin_split"):
        # 髪飾りを、ピンごとの層に分ける（char.json の pin_split: true。書かなければ前と同じ 1 枚）。エンジンが、1 本ずつ、
        # 留めている房に付いた固い板として動かす（model.json の rigidPins）。1 枚のままだと、左右のピンが 1 つの基準点で動き、髪とずれた
        m_ = cv2.dilate((a > 0.25).astype(np.uint8), ell(7))
        n_, lab_, st_, _ = cv2.connectedComponentsWithStats(m_, connectivity=8)
        k_ = 0
        for j_ in sorted(range(1, n_), key=lambda j: (st_[j, cv2.CC_STAT_LEFT], st_[j, cv2.CC_STAT_TOP])):
            if st_[j_, cv2.CC_STAT_AREA] < 200:
                continue
            ap_ = a * (lab_ == j_)
            ys_, xs_ = np.where(ap_ > 0.004)
            x0, y0 = max(0, xs_.min() - 2), max(0, ys_.min() - 2)
            x1, y1 = min(OW, xs_.max() + 3), min(YMAX + PADY, ys_.max() + 3)
            k_ += 1
            nm_, fn_ = "髪飾り%d" % k_, "L%03d_%d.png" % (i, k_)
            cv2.imwrite(os.path.join(out, "parts", fn_), rgba(rgb[y0:y1, x0:x1], ap_[y0:y1, x0:x1]))
            layers.append(dict(id=10000 + i * 20 + k_, name=nm_, path=path, src=fn_, x=int(x0), y=int(y0) - PADY, w=int(x1 - x0), h=int(y1 - y0),
                               opacity=OP, blend=BL, clip=False, hidden=hidden))
            alpha_of[nm_] = (ap_[y0:y1, x0:x1], int(x0), int(y0) - PADY)
            PIN_PIECES[nm_] = [round((x0 + x1) / 2.0, 1), round((y0 + y1) / 2.0 - PADY, 1)]   # 付いている点 = ピンのまん中
            if not hidden:
                comp = comp * (1 - ap_[..., None]) + rgb * ap_[..., None]
                ca = ca + ap_ * (1 - ca)
        print("pin_split: 髪飾りを %d 本に分けた" % k_)
        continue
    ys_, xs_ = np.where(a > 0.004)
    if not len(ys_):
        cv2.imwrite(os.path.join(out, "parts", fn), np.zeros((4, 4, 4), np.uint8))
        layers.append(dict(id=i, name=name, path=path, src=fn, x=1498, y=1000, w=4, h=4, opacity=OP,
                           blend=BL, clip=False, hidden=hidden))
        alpha_of[name] = (np.zeros((4, 4), np.float32), 1498, 1000)
        continue
    x0, y0 = max(0, xs_.min() - 2), max(0, ys_.min() - 2)
    x1, y1 = min(OW, xs_.max() + 3), min(YMAX + PADY, ys_.max() + 3)
    cv2.imwrite(os.path.join(out, "parts", fn), rgba(rgb[y0:y1, x0:x1], a[y0:y1, x0:x1]))
    layers.append(dict(id=i, name=name, path=path, src=fn, x=int(x0), y=int(y0) - PADY, w=int(x1 - x0), h=int(y1 - y0),
                       opacity=OP, blend=BL, clip=False, hidden=hidden))
    alpha_of[name] = (a[y0:y1, x0:x1], int(x0), int(y0) - PADY)
    if not hidden and BL == "normal":
        aa = a * OP
        if name.startswith("瞳ベース"):
            aa = a * place(*L["20_eye_white_" + ("L" if name.endswith("R") else "R")])[1]
        comp = comp * (1 - aa[..., None]) + rgb * aa[..., None]
        ca = ca + aa * (1 - ca)
cv2.imwrite(os.path.join(out, "_composite.png"), rgba(comp, ca))


# ---------- 曲線
def smooth(v, sig):
    v = np.asarray(v, np.float32)
    r = max(1, int(sig * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sig) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(v, r, mode="edge"), k, mode="valid")


def fix(v):
    bad = np.isnan(v)
    v[bad] = np.interp(np.where(bad)[0], np.where(~bad)[0], v[~bad])
    return v


def lid_curves(name):
    a, px, py = alpha_of[name]
    cols = np.where((a > 0.5).any(0))[0]
    xa, xb = cols.min(), cols.max()
    U, Lo = [], []
    for c in range(xa, xb + 1):
        r = np.where(a[:, c] > 0.5)[0]
        U.append(r.min() if len(r) else np.nan)
        Lo.append(r.max() + 1 if len(r) else np.nan)
    U, Lo = fix(np.array(U, np.float32)), fix(np.array(Lo, np.float32))
    return {"xa": int(px + xa), "xb": int(px + xb), "U": [round(float(t), 1) for t in smooth(U, 3) + py],
            "L": [round(float(t), 1) for t in smooth(Lo, 3) + py]}


def center_line(name):
    a, px, py = alpha_of[name]
    cols = np.where((a > 0.3).any(0))[0]
    xa, xb = cols.min(), cols.max()
    yv = np.arange(a.shape[0], dtype=np.float32)
    ys2 = []
    for c in range(xa, xb + 1):
        w = a[:, c]
        ws = np.where(w > 0.35, w, 0)          # 線のはっきりした画素だけで重心を取る（線の下の淡い色に引っ張られて、曲線が尖るのを防ぐ）
        if ws.sum() > 0.3:
            w = ws
        ys2.append((w * yv).sum() / max(w.sum(), 1e-6) if w.sum() > 0.05 else np.nan)
    ys2 = fix(np.array(ys2, np.float32))
    return {"xa": int(px + xa), "xb": int(px + xb), "Y": [round(float(t), 1) for t in smooth(ys2, CHAR.get('mouth_smooth', 2)) + py]}


def bottom_edge(name):
    a, px, py = alpha_of[name]
    cols = np.where((a > 0.5).any(0))[0]
    xa, xb = cols.min(), cols.max()
    ys2 = []
    for c in range(xa, xb + 1):
        r = np.where(a[:, c] > 0.5)[0]
        ys2.append(r.max() + 1 if len(r) else np.nan)
    ys2 = fix(np.array(ys2, np.float32))
    return {"xa": int(px + xa), "xb": int(px + xb), "Y": [round(float(t), 1) for t in smooth(ys2, 5) + py]}


def row_halfwidth(name):
    a, px, py = alpha_of[name]
    rows = np.where((a > 0.5).any(1))[0]
    ya, yb = rows.min(), rows.max()
    hw, cx = [], []
    for r in range(ya, yb + 1):
        c = np.where(a[r] > 0.5)[0]
        hw.append((c.max() - c.min() + 1) / 2)
        cx.append((c.max() + c.min() + 1) / 2 + px)
    return {"y0": int(py + ya), "R": [round(float(t), 1) for t in smooth(hw, 6)], "cx": round(float(np.median(cx)), 1)}


def centroid(name):
    a, px, py = alpha_of[name]
    ys2, xs2 = np.where(a > 0.5)
    return [round(float(px + xs2.mean()), 1), round(float(py + ys2.mean()), 1)]


curves = {
    "eyeR": dict(lid_curves("白目R"), iris=centroid("瞳ベースR"), lash=bottom_edge("アイライン線R")),
    "eyeL": dict(lid_curves("白目L"), iris=centroid("瞳ベースL"), lash=bottom_edge("アイライン線L")),
    "mouth": center_line("下唇線"),
    "face": row_halfwidth("輪郭ベース"),
    "browR": centroid("眉毛R"),
    "browL": centroid("眉毛L"),
}
# 調整の初期値（char.json の tune・params で置き換える。無ければ、最初のモデルで動かしながら決めた値）
TUNE = CHAR.get("tune", {"yawMax": 10, "upMax": 5, "downMax": 5, "rollMax": 18, "depth": 1.0, "sway": 2.5})
PARAMS_DEF = CHAR.get("params", {"mouthForm": -0.1, "mouthWidth": 0.85})     # 口の形・口の幅の初期値
# 口の色と線。設定に無いときは、新しい描き方（style 2）と、kurage02 で決めた色で始める
MOUTH_VEC = CHAR.get("mouthVector", {"style": 2, "line": "#9a3a40", "lineWidth": 3.5, "inside": ["#c94f5e", "#d45c68"], "tongue": "#ff8a92", "tongueLight": "#ff9aa0", "teeth": "#ffffff", "teethMax": 16})
MODEL = {"view": CHAR["view"]} if CHAR.get("view") else {}
MODEL["fit"] = {"s": round(float(S), 6), "ox": ox, "oy": oy}      # 3 倍の絵の座標 → モデルの座標（x' = ox + s・x）。基準画像と同じ縮尺で並べる道具（fidscale.py）が使う
MODEL.update({"size": [OW, 6000], "yMax": YMAX, "tune": TUNE, "params": PARAMS_DEF, "neck": {"complete": bool(os.environ.get("NECKDOWN") or os.environ.get("NECK_ONLY"))}, "mouthVector": MOUTH_VEC, "layers": layers, "curves": curves})
# 揺れ物の動かし方（エンジンの physics）。レイヤーがそろっているものだけ渡す。physics_tune は、画面の「今の調整値を書き出す」で出した値
PHYS = []
LAYER_NAMES_ = {l_["name"] for l_ in layers}
LAYER_BY_ = {l_["name"]: l_ for l_ in layers}
FRONT_CLUMPS_ = [n_ for n_, m_ in LOCK_META.items() if m_.get("g") != "back"] if LOCK_META and CLUMP_ else []


def cover_clump_(ax, ay):
    """その点を覆う、いちばん上（あとに描く）の前の髪の房。無ければ None（エンジンは、頭の髪の面で動かす）"""
    best = None
    for l_ in layers:
        if l_["name"] in FRONT_CLUMPS_ and l_["name"] in alpha_of:
            a_, x0_, y0_ = alpha_of[l_["name"]]
            ix, iy = int(round(ax - x0_)), int(round(ay - y0_))
            if 0 <= iy < a_.shape[0] and 0 <= ix < a_.shape[1] and a_[max(0, iy - 3):iy + 4, max(0, ix - 3):ix + 4].max() > 0.5:
                best = l_["name"]
    return best


for p_ in EXTRAS.get("physics", []):
    # "base": true の揺れ物は、追加で描かせたレイヤーでなくても（結んだ髪 後ろ髪1R・1L など、元からあるレイヤーでも）、モデルにあれば渡す。書かなければ前と同じ
    if not all(n_ in EXTRA_NAMES or (p_.get("base") and n_ in LAYER_NAMES_) for n_ in p_["layers"]):
        # 入れない揺れ物を、黙って落とさない
        miss_ = [n_ for n_ in p_["layers"] if n_ not in EXTRA_NAMES and n_ not in LAYER_NAMES_]
        if miss_:
            print("extras: 揺れ物 %s は入れません（レイヤー %s が、モデルにありません。extras.layers の絵が、まだ置かれていないか、名前が違います）" % (p_.get("id"), "・".join(miss_)))
        else:
            print("extras: 揺れ物 %s は入れません（レイヤー %s は、extras.layers で足した絵ではなく、元からあるレイヤーです。揺らすなら、この揺れ物に \"base\": true を付けます）"
                  % (p_.get("id"), "・".join(n_ for n_ in p_["layers"] if n_ not in EXTRA_NAMES)))
    if all(n_ in EXTRA_NAMES or (p_.get("base") and n_ in LAYER_NAMES_) for n_ in p_["layers"]):
        e_ = dict(p_, **(CHAR.get("physics_tune", {}).get(p_["id"], {})))
        if isinstance(e_.get("frame"), dict):
            # 固い板（エンジンの makeFrame）: 付いている点を、支点（最初のレイヤーの箱の中の割合）から出し、"follow": "auto" なら、その点を覆う房を選ぶ
            fr_, l0_, pv_ = dict(e_["frame"]), LAYER_BY_[e_["layers"][0]], e_.get("pivot", [0.5, 0])
            if fr_.get("pin"):
                # "frame": {"pin": <レイヤーの名前>}: extras.pins に書いた飾り（花など）と、同じ板に乗る（付いている点・房は、その飾りの物を使う）
                print("frame: %s は、飾り %s の板に乗る" % (e_["id"], fr_["pin"]))
            else:
                if "anchor" not in fr_:
                    fr_["anchor"] = [round(l0_["x"] + pv_[0] * l0_["w"], 1), round(l0_["y"] + pv_[1] * l0_["h"], 1)]
                if fr_.get("follow") == "auto":
                    fr_["follow"] = cover_clump_(*fr_["anchor"])
                print("frame: %s 付いている点 %s 房 %s" % (e_["id"], fr_["anchor"], fr_.get("follow")))
            e_["frame"] = fr_
        PHYS.append(e_)
if PHYS:
    MODEL["physics"] = PHYS
if PIN_PIECES:
    MODEL["rigidPins"] = {n_: {"anchor": c_, "follow": cover_clump_(*c_)} for n_, c_ in PIN_PIECES.items()}
    print("rigidPins:", {n_: v_["follow"] for n_, v_ in MODEL["rigidPins"].items()})
# char.json の extras.pins: {"<レイヤーの名前>": {"follow": "auto", "anchor": [0.5, 0.5]}}（書かなければ前と同じ）
#   追加で描かせた髪飾り（花など、揺らさない本体）を、留めている房に付いた固い板にする（エンジンの rigidPins。pin_split と同じ動き）。
#   anchor は、付いている点（そのレイヤーの箱の中の割合。書かなければ、まん中）。follow は、房の名前か "auto"（その点を覆う、いちばん上の前の髪の房）。
#   同じ飾りに付いた揺れ物（リボン・鎖）は、extras.physics に "frame": {"pin": "<レイヤーの名前>"} と書いて、同じ板に乗せる。
#   前は、髪飾りの全部を、エンジンの決まった 1 点で動かしていて、横を向くと、留めている髪より約 40 画素 遅れて動いた（付け根が滑る）
for n_, sp_ in (EXTRAS.get("pins") or {}).items():
    if n_ not in LAYER_BY_:
        print("extras.pins: %s は入れません（その名前のレイヤーが、モデルにありません）" % n_)
        continue
    l_, pv_ = LAYER_BY_[n_], sp_.get("anchor", [0.5, 0.5])
    a_ = [round(l_["x"] + pv_[0] * l_["w"], 1), round(l_["y"] + pv_[1] * l_["h"], 1)]
    fo_ = sp_.get("follow", "auto")
    MODEL.setdefault("rigidPins", {})[n_] = {"anchor": a_, "follow": cover_clump_(*a_) if fo_ == "auto" else fo_}
    print("extras.pins: %s 付いている点 %s 房 %s" % (n_, a_, MODEL["rigidPins"][n_]["follow"]))
if CHAR.get("talkDemo"):
    MODEL["talkDemo"] = CHAR["talkDemo"]            # 「口パクデモ」のせりふ（ひらがな）
if CHAR.get("mouthShapes"):
    MODEL["mouthShapes"] = CHAR["mouthShapes"]      # 母音ごとの口の形（画面の「母音の口の形」で決めて書き出した値）
if CHAR.get("eyeTune"):
    MODEL["eyeTune"] = CHAR["eyeTune"]              # 瞳の動き（ぷるん・うるみ・視線のはずみ。画面の「瞳の動き」で決めて書き出した値）
if LOCK_META and CLUMP_:
    MODEL["hairClumps"] = LOCK_META                 # 房ごとの、揺れ方の種類・根元・毛先（エンジンが、この軸に沿って、長さを変えずに曲げる）
elif LOCK_META:
    MODEL["hairLocks"] = LOCK_META                  # 毛束ごとの、揺れ方の種類・根元・毛先
    MODEL["hairField"] = HAIR_FIELD                 # 髪の全体の「流れ」の、根元の高さと長さ
    MODEL["hairBases"] = HAIR_BASES                 # 下地のレイヤー（流れだけで動かす）
if LOCK_META and CLUMP_:
    CHAR["hair_rigid"] = list(CHAR.get("hair_rigid", [])) + ["前髪下地"]
if CHAR.get("hair_rigid"):
    MODEL["hairRigid"] = CHAR["hair_rigid"]        # 頭に付けたまま動かす髪のレイヤー名（編み込み・お団子など。揺らすと、ぶらぶらして見える）
if CHAR.get("hat"):
    MODEL["hat"] = CHAR["hat"]          # 帽子のふちの揺れ（{"sway": 前髪の揺れに対する倍率}）
if KEY_EYE and KEY_EYE_IMG:
    kb_ = KEY_EYE["box"]; kcw_, kch_ = KEY_EYE["canvas"]
    sxk_, syk_ = (kb_[2] - kb_[0]) / float(kcw_), (kb_[3] - kb_[1]) / float(kch_)
    KE_ = {}
    for tom in "RL":                                   # R = 画面左（見本のまま）、L = 画面右（左右を返して置いた）
        c_ = curves["eye" + tom]
        xs_ = np.arange(c_["xa"], c_["xb"] + 1)
        KE_[tom] = {}
        for nm_, k_ in KEY_EYE["keys"].items():
            kx_ = np.arange(k_["xa"], k_["xb"] + 1, dtype=np.float32)
            if tom == "R":
                wx_, wdy_ = cxL_ + (kb_[0] + (kx_ + 0.5) * sxk_ - cxL_) * KSX_, 0.0
            else:
                wx_, wdy_ = cxR_ + (KEY_EYE_POS[0] + (kb_[2] - kb_[0]) - (kx_ + 0.5) * sxk_ - cxR_) * KSX_, float(KEY_EYE_POS[1])
            mx_ = ox + S * wx_
            od_ = np.argsort(mx_)
            conv_ = lambda arr: [round(float(t), 1) for t in np.interp(xs_, mx_[od_], (oy + S * (cyL_ + (kb_[1] + np.asarray(arr, np.float32) * syk_ - cyL_) * KSY_ + KDY_ + wdy_))[od_])]
            KE_[tom][nm_] = {"T": conv_(k_["T"]), "B": conv_(k_["B"]), "L": conv_(k_["L"]), "closed": bool(k_.get("closed"))}
            if CHAR.get("key_eye_slope"):
                # 目の開き（L − B）が、目尻・目頭の端から増える速さに上限を付ける（char.json の key_eye_slope = 1 列あたりのモデルの画素。書かなければ前と同じ）。
                # 白目の端が縦にまっすぐ切れて取れたキー（にらみの目: 目尻の影の所で、開きが 1 列で 65 画素とんだ例がある）で、白目が目尻の外へ四角くはみ出すのを、くさび形に閉じる
                ms_ = float(CHAR["key_eye_slope"])
                Bv_ = np.asarray(KE_[tom][nm_]["B"], np.float32); o_ = np.maximum(np.asarray(KE_[tom][nm_]["L"], np.float32) - Bv_, 0)
                for rng_ in (range(len(o_)), range(len(o_) - 1, -1, -1)):
                    prev_ = 0.0                                      # 端の外は、開き 0（目尻・目頭で、白目を閉じる）
                    for i_ in rng_:
                        if o_[i_] > prev_ + ms_:
                            o_[i_] = prev_ + ms_
                        prev_ = o_[i_]
                KE_[tom][nm_]["L"] = [round(float(b_ + v_), 1) for b_, v_ in zip(Bv_, o_)]
    MODEL["keyEye"] = KE_
    if (KEY_EYE.get("crease") or {}).get("key") in KEY_EYE["keys"] and "crease" in KEY_EYE_IMG:
        MODEL["keyEyeCrease"] = KEY_EYE["crease"]["key"]       # 二重の線（目キー_crease）を取ったコマの名前。エンジンは、そのコマの線を基準に動かす
    if CHAR.get("key_eye_rest") is not None:
        # ふだんの目の開き（開きの値 1）を、シートの「開いた目」のコマの何割にするか。シートの開いた目が、基準画像より開いて描かれたときに、1 より小さくする
        MODEL["keyEyeRest"] = float(CHAR["key_eye_rest"])
if KEY_MOUTH and KEY_MOUTH_IMG:
    mb2_ = KEY_MOUTH["box"]; kcw_, kch_ = KEY_MOUTH["canvas"]
    syk_ = (mb2_[3] - mb2_[1]) / float(kch_)
    kmb_ = {nm_: key_mouth_box(nm_) for nm_ in KEY_MOUTH["keys"]}            # キーごとの、左の端と幅（key_mouth_scale）
    MODEL["keyMouth"] = {"keys": {nm_: {"xa": round(ox + S * (kmb_[nm_][0] + k_["xa"] * kmb_[nm_][1] / float(kcw_)), 1),
                                        "xb": round(ox + S * (kmb_[nm_][0] + (k_["xb"] + 1) * kmb_[nm_][1] / float(kcw_)), 1),
                                        "U": [round(float(oy + S * (mb2_[1] + v_ * syk_)), 1) for v_ in k_["U"]],
                                        "Lo": [round(float(oy + S * (mb2_[1] + v_ * syk_)), 1) for v_ in k_["Lo"]], "open": bool(k_["open"])}
                                  for nm_, k_ in KEY_MOUTH["keys"].items()}}
# eyeLineClip: true で、下まつげ・目尻の線・二重の線を、顔の輪郭の内側だけに描く（奥の目が輪郭をまたぐキャラ。書かなければ前と同じ）
# diffAttach: {"涙": "eye", "汗": "eye"} のように、表情の差分を、目と同じ動きにする（目のすぐ下に描いた涙・汗の粒。書かなければ、肌の面）
# hairWrap: 後ろの房を、形を保ったまま、頭のまわりを回る塊として動かす強さ（0〜1。エンジンの HAIR_WRAP。頭の横に大きく張り出した房があるキャラ）
for k_ in ("browAmp", "browTint", "lashOver", "lidShadow", "expr", "pinAttach", "mouthKeySharp", "keyMouthShapes", "noseAxis", "hairWrap", "diffAttach", "eyeLineClip", "hatDome"):
    if CHAR.get(k_) is not None:
        MODEL[k_] = CHAR[k_]                        # 眉の動きの大きさ、キャラごとの表情の足し・上書き。pinAttach: 髪飾りの動き（"skin" = 頭の面に沿う）
if EYE_MARKS is not None and "目の下の印" in LAYER_NAMES_:
    MODEL["eyeAttach"] = ["目の下の印"]             # エンジンが、このレイヤーを、目と同じ動きにする（顔の輪郭の内側だけに描く）
json.dump(MODEL,
          open(os.path.join(out, "model.json"), "w", encoding="utf-8"), ensure_ascii=False)
f = curves["face"]
print("head ratio (height / half width) %.3f" % ((chin - head_top) * S / max(f["R"])))
print("scale %.4f offset %d,%d  head_top %d chin %d cx %.1f" % (S, ox, oy, head_top, chin, cxm))
print("face y0", f["y0"], "rows", len(f["R"]), "Rmax", max(f["R"]), "cx", f["cx"])
print("iris", curves["eyeR"]["iris"], curves["eyeL"]["iris"], "brow", curves["browR"], curves["browL"],
      "mouth y", round(float(np.mean(curves["mouth"]["Y"])), 1), "x", curves["mouth"]["xa"], curves["mouth"]["xb"])
print("hair px", int(hm.sum()), "mouth open px", int(mo.sum()), "tongue px", int(tongue.sum()), "dy", dy)
for l in layers:
    print(l["name"], l["path"], l["x"], l["y"], l["w"], l["h"])
