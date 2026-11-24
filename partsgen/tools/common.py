import os, sys, json, numpy as np, cv2

for _f in (sys.stdout, sys.stderr):          # 出力は UTF-8（OS の文字コードのままだと、日本語の Windows 以外で、日本語の表示で止まる）
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# キャラごとの値（環境変数 CHARCFG の設定ファイル = partsgen/chars/<キャラ名>/char.json。pipeline.py が渡す）。無ければ、下の既定値で動く
CHAR = json.load(open(os.environ['CHARCFG'], encoding='utf-8')) if os.environ.get('CHARCFG') else {}


def ell(n):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (n, n))


def soft(m, s=1.0):
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), s)


def over(dst, rgb, a):
    return dst * (1 - a[..., None]) + rgb * a[..., None]


def rgba(rgb, a):
    return np.dstack([np.clip(rgb, 0, 255), np.clip(a, 0, 1) * 255]).astype(np.uint8)


def onbg(rgb, a, bg=(170, 200, 170)):
    b = np.empty(rgb.shape, np.float32)
    b[:] = bg
    return over(b, rgb, a)


def label(img, t):
    img = np.clip(img, 0, 255).astype(np.uint8).copy()
    cv2.putText(img, t, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
    cv2.putText(img, t, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
    return img


def hsv_of(bgr8):
    hsv = cv2.cvtColor(bgr8, cv2.COLOR_BGR2HSV).astype(np.float32)
    return hsv[..., 0] * 2, hsv[..., 1] / 255, hsv[..., 2] / 255


def skinlike_mask(bgr):
    B, G, R = bgr[..., 0], bgr[..., 1], bgr[..., 2]
    return (R > 238) & (G > 170) & (G < 240) & (B > 180) & (B < 243) & (R - G > CHAR.get('skin_rg_min', 14))


def skin_estimate(roi8, feat, k=4, rad=9):
    """feat(uint8 0/255) の所を周りの肌から埋めた画像を返す"""
    h, w = roi8.shape[:2]
    small = cv2.resize(roi8, (w // k, h // k), interpolation=cv2.INTER_AREA)
    ms = cv2.dilate(cv2.resize(feat, (w // k, h // k), interpolation=cv2.INTER_NEAREST), ell(3))
    sk = cv2.GaussianBlur(cv2.inpaint(small, ms, rad, cv2.INPAINT_TELEA), (0, 0), 2.5)
    skin = cv2.resize(sk, (w, h), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    a = cv2.GaussianBlur(feat, (0, 0), 4).astype(np.float32)[..., None] / 255
    return roi8.astype(np.float32) * (1 - a) + skin * a


def unmix(p, U, coremask, band=6, minmag=6):
    """p を「U の上に乗った層」として分ける。重ね直すと p に戻る色と不透明度を返す"""
    diff = p - U
    core = cv2.erode(coremask.astype(np.uint8), ell(3))
    if core.sum() == 0:
        core = coremask.astype(np.uint8)
    dist, lab = cv2.distanceTransformWithLabels(1 - core, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.where(core > 0)
    lut = np.zeros((lab.max() + 1, 2), int)
    lut[lab[ys, xs]] = np.c_[ys, xs]
    F = p[lut[lab][..., 0], lut[lab][..., 1]]
    num = (diff * (F - U)).sum(-1)
    den = ((F - U) ** 2).sum(-1) + 1e-3
    ap = np.clip(num / den, 0, 1)
    ap[dist > band] = 0
    ap[den < 400] = 0
    pos = np.where(diff > 0, diff / np.maximum(255 - U, 1), -diff / np.maximum(U, 1))
    ag = pos.max(-1)
    a = np.clip(np.maximum(ap, ag), 0, 1)
    a[np.abs(diff).max(-1) < minmag] = 0
    a[core > 0] = 1
    Fp = np.clip(U + diff / np.maximum(a, 1e-3)[..., None], 0, 255)
    Fp = np.where((a > 0)[..., None], Fp, F)
    return Fp, a


def fit_circle(pts):
    A = np.c_[pts[:, 0], pts[:, 1], np.ones(len(pts))]
    co = np.linalg.lstsq(A, -(pts[:, 0] ** 2 + pts[:, 1] ** 2), rcond=None)[0]
    cx = -co[0] / 2
    cy = -co[1] / 2
    return cx, cy, np.sqrt(cx * cx + cy * cy - co[2])
