# -*- coding: utf-8 -*-
"""hairlocks.py <設定.json>

「元の位置のまま描かせた毛束の絵」（1 枚に、となり合わない毛束が何本か）から、毛束を 1 つずつ切り出して、
モデルに入れられる形（3 倍の絵の座標での、毛束ごとの絵と置き場所）にする。

  1. 描かせた絵を Real-ESRGAN で 2 倍にする（ふちと線をはっきりさせる）
  2. 絵ごとのずれ・大きさの違いを、デザイン（毛束に分ける前の髪の絵）に合わせて直す
  3. つながった塊 = 毛束 1 つとして切り出す。同じ毛束を 2 回描いたものは、片方を捨てる
  4. 重ね順を決める（2 つの毛束が重なる所で、デザインに近い色をしている方が上）
  5. 毛束ごとに、根元・毛先・揺れ方の種類・重なりの中での手前さを求める
  6. 色を、元の髪の色に合わせる（明るさ・色合いの平均と幅を合わせる）
  7. 前の髪の下地（頭頂をおおう面。束のすき間から頭の肌が見えないように）を作る

設定:
{
  "out": 出力フォルダ,
  "tone_ref": 色を合わせる先の絵（元の髪。省略で色は変えない）,
  "tone_mask": tone_ref のうち、髪のある所を示す絵（省略で tone_ref の全体。tone_ref を 00_base にするときに、髪だけの絵を書く）,
  "parts": {
    "front": {"design": デザインの絵, "box": [x0,y0,x1,y1]（デザインの絵が、3 倍の絵のどの範囲か）, "srcs": [描かせた絵...],
              "whorl": [x,y]（つむじ。デザインの絵の座標。省略で、外形のてっぺん）, "base": true},
    "back":  {"design": ..., "box": ..., "srcs": [...], "cap": 後頭部の絵}
  },
  "bangs_tip_y": 前髪と横髪を分ける高さ（3 倍の絵の y。毛先がこれより上なら前髪）,
  "center_x": 顔の中心（3 倍の絵の x）, "head_r": 頭の半幅（3 倍の絵）
}
出力: <out>/hair_locks.json、<out>/<部分>_NN.png、<out>/_check_<部分>.png（左: デザイン、中: 重ねた絵、右: 差）、<out>/_sheet_<部分>.png（束の一覧）
"""
import sys, os, json, subprocess, shutil
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

for _f in (sys.stdout, sys.stderr):          # 出力は UTF-8（OS の文字コードのままだと、日本語の Windows 以外で、日本語の表示で止まる）
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
LUM = np.array([0.299, 0.587, 0.114], np.float32)


def rd(p):
    return np.asarray(Image.open(p).convert('RGBA')).astype(np.float32)


def lines(img):
    al = img[..., 3] > 128
    if not al.any():
        return al.astype(np.float32)
    lum = img[..., :3] @ LUM
    return (al & (lum < np.median(lum[al]) * 0.62)).astype(np.float32)


def on(img, bg):
    a = img[..., 3:4] / 255
    return (img[..., :3] * a + np.array(bg, np.float32) * (1 - a)).astype(np.uint8)


def warp_rgba(img, M, size, flags=cv2.INTER_LINEAR):
    """不透明度を掛けた色で変形する（透明な画素の色が、ふちににじまないように）"""
    pm = img.copy(); pm[..., :3] *= pm[..., 3:4] / 255
    o = cv2.warpAffine(pm, M, size, flags=flags)
    a = np.maximum(o[..., 3:4], 1e-3) / 255
    o[..., :3] = np.clip(o[..., :3] / a, 0, 255)
    return o


def align(S, D, name):
    """描かせた絵は、全体が数画素ずれたり、わずかに大きさが違ったりする。デザインの外形と輪郭線にいちばん合う、ずれと倍率を探す（半分の大きさで探す）"""
    H, W = D.shape[:2]
    h, w = H // 2, W // 2
    Da = cv2.resize((D[..., 3] > 128).astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)
    Dl = cv2.GaussianBlur(cv2.resize(lines(D), (w, h), interpolation=cv2.INTER_AREA), (0, 0), 1.3); Dl /= max(Dl.max(), 1e-6)
    Sa = cv2.resize((S[..., 3] > 128).astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)
    Sl = cv2.resize(lines(S), (w, h), interpolation=cv2.INTER_AREA)
    Dc = cv2.resize(D[..., :3], (w, h), interpolation=cv2.INTER_AREA)
    Sc = cv2.resize(S[..., :3], (w, h), interpolation=cv2.INTER_AREA)

    def score(sc, dx, dy):
        M = np.array([[sc, 0, (1 - sc) * w / 2 + dx], [0, sc, (1 - sc) * h / 2 + dy]], np.float32)
        a2 = cv2.warpAffine(Sa, M, (w, h)); l2 = cv2.warpAffine(Sl, M, (w, h)); c2 = cv2.warpAffine(Sc, M, (w, h))
        # 描かせた束のうち、見えている所は、デザインの同じ場所と同じ色（ハイライト・影・輪郭線）のはず。色が合う画素の割合を主に見る
        same = (a2 > 0.5) & (Da > 0.5) & (np.abs(c2 - Dc).max(-1) < 28)
        return (2.0 * same.sum() / max(a2.sum(), 1) + (a2 * Da).sum() / max(a2.sum(), 1) + 0.5 * (l2 * Dl).sum() / max(l2.sum(), 1)
                - 0.002 * (abs(dx) + abs(dy)) - 0.5 * abs(sc - 1))          # 大きなずれ・倍率の違いは、少しだけ不利にする

    best = max(((score(sc, dx, dy), sc, dx, dy) for sc in np.arange(0.94, 1.0301, 0.015) for dx in range(-18, 19, 3) for dy in range(-18, 19, 3)))
    _, sc, dx, dy = best
    if abs(dx) >= 18 or abs(dy) >= 18 or sc < 0.941 or sc > 1.029:
        # 探す範囲の端に当たった = 絵が、もっと大きくずれている（kurage02: 房の絵が、下へ 70 画素ほどずれて描かれた。範囲の端で止まって、前髪が長くなった）。
        # 範囲を広げて、探し直す（粗く探してから、そのまわりを詰める。全部を細かく探すと、1 枚に数分かかる）
        best = max(((score(s2, x2, y2), s2, x2, y2) for s2 in np.arange(0.85, 1.0601, 0.03) for x2 in range(-45, 46, 5) for y2 in range(-45, 46, 5)))
        _, sc, dx, dy = best
        best = max(((score(s2, x2, y2), s2, x2, y2) for s2 in (sc - 0.015, sc, sc + 0.015) for x2 in range(dx - 4, dx + 5, 2) for y2 in range(dy - 4, dy + 5, 2)))
        _, sc, dx, dy = best
        print('  align %-14s 探す範囲を広げた' % name)
    best = max(((score(s2, dx + ex, dy + ey), s2, dx + ex, dy + ey) for s2 in (sc - 0.0075, sc, sc + 0.0075) for ex in (-2, -1, 0, 1, 2) for ey in (-2, -1, 0, 1, 2)))
    v, sc, dx, dy = best
    print('  align %-14s scale %.3f shift %+d,%+d (score %.3f)' % (name, sc, dx * 2, dy * 2, v))
    return float(sc), float(dx * 2), float(dy * 2)       # デザインの絵の画素で


def apply_affine(l, A, W, H, k3, box):
    """束 l（デザインの絵の画素で置いた絵 img・範囲 m・切り出し用の mask・2 倍の絵 → 3 倍の絵の変換 M2）に、デザインの絵の画素での変換 A（2×3）を掛ける"""
    A = np.asarray(A, np.float32)
    l['img'] = warp_rgba(l['img'], A, (W, H)); l['m'] = l['img'][..., 3] > 128
    l['mask'] = cv2.warpAffine(l['mask'].astype(np.float32), A, (W, H)) > 0.5
    # 3 倍の絵の画素では: p3 = box0 + k3・p。A を、3 倍の絵の座標の変換に直して、M2 の後ろに掛ける
    b0 = np.array([box[0], box[1]], np.float32)
    Lm, t = A[:, :2], A[:, 2]
    t3 = k3 * t + b0 - Lm @ b0
    M2 = l['M2']
    l['M2'] = np.hstack([Lm @ M2[:, :2], (Lm @ M2[:, 2] + t3)[:, None]]).astype(np.float32)
    if l['m'].any():
        l['cx'] = float(np.where(l['m'])[1].mean())


def split_by_parts(comp, PM, anchor, W, name=''):
    """つながって描かれた塊 comp が、房の目印（PM: 多角形の範囲）を 2 つ以上おおっているとき、目印ごとに分ける。
    1 枚の絵に、となり合わない房を何本か描かせるが、下のほうの房の根元が、上の房まで伸びて、1 つにつながることがある
    （kurage02: 左下の房の根元が、前髪の左の房の毛筋につながり、前髪の一部が、長い横の房と一緒に揺れるパーツになった）。
    つむじから遠い目印から順に、その目印のまわり（幅の 1 割以内）を取り、いちばん近い目印には、まわり（幅の 5%）と、つむじ側の根元を残す。
    どの目印からも遠い所（房と房をつないでいた、根元の描き足し）は、捨てる（ほかの房の下に隠れる所）"""
    if not PM:
        return [comp]
    # 目印の 6 割以上をおおっていたら、その房が入っている（となりの房の範囲へ、広めに描き足したぶんは、2〜4 割までしか おおわない）
    hits = [k for k, pm in enumerate(PM) if (comp & pm).sum() >= 0.6 * max(pm.sum(), 1)]
    if len(hits) < 2:
        return [comp]
    yy, xx = np.mgrid[0:comp.shape[0], 0:comp.shape[1]]
    dw = np.hypot(xx - anchor[0], yy - anchor[1])
    near = {k: float(dw[PM[k]].min()) for k in hits}
    order = sorted(hits, key=lambda k: -near[k])                 # つむじから遠い順
    rest = comp.copy(); out = []
    for j, k in enumerate(order):
        last = j == len(order) - 1
        r = int((0.05 if last else 0.10) * W) | 1
        reg = cv2.dilate(PM[k].astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
        if last:
            reg |= dw < near[k]                                  # つむじ側の根元
        pcs = rest & reg
        rest &= ~pcs
        if pcs.sum() >= 400:
            # 目印のまわりに入った、ほかの房の切れ端を落とす（目印に重なる塊だけ残す）
            n, lab, st, _ = cv2.connectedComponentsWithStats(pcs.astype(np.uint8), connectivity=8)
            keep = np.zeros_like(pcs)
            for i in range(1, n):
                if (PM[k] & (lab == i)).any():
                    keep |= lab == i
            if keep.sum() >= 400:
                out.append(keep)
    print('  %s: つながって描かれた塊を、目印で %d つに分けた（捨てた根元の描き足し %d 画素）' % (name, len(out), int(rest.sum())))
    return out or [comp]


def upscale2(srcs, tmp):
    """Real-ESRGAN で 2 倍に。もう作ってあれば使う"""
    os.makedirs(tmp, exist_ok=True)
    need = []
    for s in srcs:
        d = os.path.join(tmp, os.path.splitext(os.path.basename(s))[0] + '_2x.png')
        if not os.path.isfile(d) or os.path.getmtime(d) < os.path.getmtime(s):
            need.append(s)
    if need:
        r = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'upscale.py')] + need + ['--scale', '2', '--out', tmp, '--force'])
        if r.returncode:
            sys.exit('拡大に失敗しました')
    return {s: os.path.join(tmp, os.path.splitext(os.path.basename(s))[0] + '_2x.png') for s in srcs}


def tone_stats(img):
    """髪のメインの色（色みのある画素）だけで、Lab の平均と幅を出す。白に近いハイライトと、毛先の別の色（青緑など）は、数えない
    （数えると、後ろ髪だけ毛先の色が多いとき、全体が青白くずれた）"""
    m = img[..., 3] > 200
    lab = cv2.cvtColor(np.clip(img[..., :3], 0, 255).astype(np.uint8)[None, m], cv2.COLOR_RGB2LAB).astype(np.float32)[0]
    ch = np.hypot(lab[:, 1] - 128, lab[:, 2] - 128)
    ang = np.arctan2(lab[:, 2] - 128, lab[:, 1] - 128)
    a0 = np.arctan2(np.median(lab[:, 2]) - 128, np.median(lab[:, 1]) - 128)            # メインの色の向き
    da = np.abs((ang - a0 + np.pi) % (2 * np.pi) - np.pi)
    main = (ch > 0.5 * np.median(ch)) & (da < 0.6)
    if main.sum() > 1000:
        lab = lab[main]
    return lab.mean(0), lab.std(0)


def tone_apply(img, src, dst):
    """色を合わせる: Lab の平均と幅を、元の髪に合わせる（幅の倍率は 0.8〜1.25 に抑える）"""
    (m0, s0), (m1, s1) = src, dst
    k = np.clip(s1 / np.maximum(s0, 1e-3), 0.8, 1.25)
    lab = cv2.cvtColor(np.clip(img[..., :3], 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    # 色み（a・b）のずらしは、色みの強い画素ほど大きく掛ける。白に近いハイライトは、ほとんど動かさない（一律にずらしたら、ハイライトがベージュになった）
    ch0 = max(float(np.hypot(m0[1] - 128, m0[2] - 128)), 1.0)
    w = np.clip(np.hypot(lab[..., 1] - 128, lab[..., 2] - 128) / ch0, 0, 1)[..., None]
    new = (lab - m0) * k + m1
    new[..., 1:] = lab[..., 1:] + (new[..., 1:] - lab[..., 1:]) * w
    lab = np.clip(new, 0, 255).astype(np.uint8)
    out = img.copy(); out[..., :3] = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB).astype(np.float32)
    return out


def main():
    cfg = json.load(open(sys.argv[1], encoding='utf-8'))
    base_dir = os.path.dirname(os.path.abspath(sys.argv[1]))
    P = lambda p: p if os.path.isabs(p) else os.path.join(base_dir, p)
    out = P(cfg['out'])
    for f in os.listdir(out) if os.path.isdir(out) else []:
        if f.endswith('.png') and not f.startswith('_'):
            os.remove(os.path.join(out, f))
    os.makedirs(out, exist_ok=True)
    CX, HR, BY = cfg['center_x'], cfg['head_r'], cfg['bangs_tip_y']
    result = {}
    allimg = {}
    for part, pc in cfg['parts'].items():
        print('[%s]' % part)
        D = rd(P(pc['design']))
        H, W = D.shape[:2]
        box = pc['box']; k3 = (box[2] - box[0]) / W            # デザインの画素 → 3 倍の絵の画素
        Dm = D[..., 3] > 128
        srcs = [P(s) for s in pc['srcs']] + ([P(pc['cap'])] if pc.get('cap') else [])
        up = upscale2(srcs, os.path.join(out, '_2x'))
        cache_p = os.path.join(out, '_align_%s.json' % part)
        cache = json.load(open(cache_p)) if os.path.isfile(cache_p) else {}
        locks = []
        cap = None
        # 房の目印（parts_full のときだけ渡される。絵ごとの、その絵に描かせた房の、デザインの絵の座標の多角形）:
        # つながって描かれた房を分ける・房ごとに位置を合わせる のに使う
        SRC_POLYS = pc.get('src_polys') or {}
        anchor_w = np.array(pc['whorl'], np.float32) if pc.get('whorl') else np.array([W / 2.0, 0.0], np.float32)
        for s in srcs:
            PM = []
            for poly in SRC_POLYS.get(os.path.basename(s), []):
                pm_ = np.zeros((H, W), np.uint8); cv2.fillPoly(pm_, [np.array(poly, np.int32)], 1); PM.append(pm_ > 0)
            S1 = np.asarray(Image.open(s).convert('RGBA').resize((W, H), Image.LANCZOS)).astype(np.float32)
            key = os.path.basename(s) + ':%d' % os.path.getmtime(s)
            if key not in cache:
                cache[key] = align(S1, D, os.path.basename(s))
                json.dump(cache, open(cache_p, 'w'))
            sc, dx, dy = cache[key]
            M = np.array([[sc, 0, (1 - sc) * W / 2 + dx], [0, sc, (1 - sc) * H / 2 + dy]], np.float32)
            A1 = warp_rgba(S1, M, (W, H))
            S2 = rd(up[s]); f2 = S2.shape[1] / W                                    # 2 倍の絵 → デザインの画素は 1/f2
            # 2 倍の絵の画素 → 3 倍の絵の画素（置き場所の左上を引く前）
            M2 = np.array([[sc * k3 / f2, 0, ((1 - sc) * W / 2 + dx) * k3 + box[0]], [0, sc * k3 / f2, ((1 - sc) * H / 2 + dy) * k3 + box[1]]], np.float32)
            n, lab, st, cen = cv2.connectedComponentsWithStats((A1[..., 3] > 128).astype(np.uint8), connectivity=8)
            comps = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 400]
            if pc.get('cap') and s == P(pc['cap']):
                comps = [max(comps, key=lambda i: st[i, cv2.CC_STAT_AREA])]
            is_cap_src = bool(pc.get('cap') and s == P(pc['cap']))
            for i in comps:
                comp = lab == i
                pieces = [comp] if is_cap_src else split_by_parts(comp, PM, anchor_w, W, os.path.basename(s))
                for pcs in pieces:
                    m = cv2.dilate(pcs.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
                    m &= ~((lab > 0) & ~pcs)
                    img = A1.copy(); img[..., 3] *= m
                    e = {'img': img, 'm': img[..., 3] > 128, 'mask': m, 'src': s, 'M2': M2, 'S2': S2, 'cx': float(np.where(pcs)[1].mean())}
                    if is_cap_src:
                        cap = e
                    else:
                        locks.append(e)
        if SRC_POLYS:
            # 房ごとの位置合わせ（parts_full のとき）: 絵の全体のずれを直したあと、房 1 つずつ、そのまわりだけで、デザインといちばん合う ずれと倍率を探す。
            # 1 枚の絵の中でも、房ごとに、描かれた位置が 20〜30 画素ちがう（kurage02: 前髪の左の房だけ短く描かれ、まん中の房が 1 つだけ長く見えた）
            for li, l in enumerate(locks):
                my, mx = np.where(l['m'])
                if len(mx) < 400:
                    continue
                pad = 60
                bx0, bx1 = max(int(mx.min()) - pad, 0), min(int(mx.max()) + pad + 1, W)
                by0, by1 = max(int(my.min()) - pad, 0), min(int(my.max()) + pad + 1, H)
                bx1 -= (bx1 - bx0) % 2; by1 -= (by1 - by0) % 2
                sc_, dx_, dy_ = align(l['img'][by0:by1, bx0:bx1], D[by0:by1, bx0:bx1], '房 x %d' % mx.mean())
                if abs(sc_ - 1) < 1e-6 and dx_ == 0 and dy_ == 0:
                    continue
                ccx, ccy = bx0 + (bx1 - bx0) / 2.0, by0 + (by1 - by0) / 2.0
                apply_affine(l, np.array([[sc_, 0, (1 - sc_) * ccx + dx_], [0, sc_, (1 - sc_) * ccy + dy_]], np.float32), W, H, k3, box)
        if pc.get('fit_tip'):
            # 毛先を、デザインの外形に合わせる（char.json の hair.<部分>.fit_tip: true）。房を 1 つずつ描かせると、房ごとに、長さが違って描かれる
            # （kurage02: 前髪のまん中の房だけ、15% 長く描かれて、目にかかった。絵の全体のずれ・倍率を直すだけでは、合わない）。
            # 房が、根元 → 毛先の向きに、デザインの外形の外へ出ているぶんを、根元を支点に、その向きにだけ縮める（幅は変えない。伸ばすことはしない）
            anchor0 = np.array(pc['whorl'], np.float32) if pc.get('whorl') else np.array([W / 2.0, 0.0], np.float32)
            if not pc.get('whorl') and cap is not None:
                cy_, cx_ = np.where(cap['m']); anchor0 = np.array([cx_.mean(), cy_.mean()], np.float32)
            for l in locks:
                my, mx = np.where(l['m'])
                if len(mx) < 400:
                    continue
                d2 = (mx - anchor0[0]) ** 2 + (my - anchor0[1]) ** 2
                j = int(d2.argmin()); root = np.array([mx[j], my[j]], np.float32)
                j2 = int(((mx - root[0]) ** 2 + (my - root[1]) ** 2).argmax()); tip = np.array([mx[j2], my[j2]], np.float32)
                ln = float(np.hypot(*(tip - root)))
                if ln < 40:
                    continue
                u = (tip - root) / ln
                t = (mx - root[0]) * u[0] + (my - root[1]) * u[1]
                inside = Dm[my, mx]
                if inside.sum() < 100:
                    continue
                t_in, t_all = float(t[inside].max()), float(t.max())
                k = (t_in + 3.0) / max(t_all, 1.0)
                if k >= 0.992 or (t > t_in + 3).sum() < 0.004 * len(t):     # 外へ出ているのが、毛先の細い先だけなら、そのまま
                    continue
                k = max(k, float(pc.get('fit_tip_min', 0.8)))
                Lm = np.eye(2, dtype=np.float32) + (k - 1) * np.outer(u, u).astype(np.float32)
                apply_affine(l, np.hstack([Lm, (root - Lm @ root)[:, None]]).astype(np.float32), W, H, k3, box)   # デザインの絵の画素での変換
                print('  fit_tip: x %.0f の房を、毛先の向きに %.3f 倍（毛先が、デザインの外へ %.0f 画素出ていた）' % (root[0] + 0.5 * ln * u[0], k, t_all - t_in))
        keep = []
        for a in sorted(locks, key=lambda l: -l['m'].sum()):
            # dedupe_contain（大きな房を、見て決めて描かせたとき）: 別の絵で描かれた、より大きい束の中に、ほとんど（7 割）入っている束も、同じ房の描き直しとして捨てる
            # （同じ房が、2 枚の絵に、少し違う太さで描かれた。重なりの割合だけでは見分けられず、重ねると二重に見えた）
            dc = float(pc.get('dedupe_contain', 0))
            if all((a['m'] & b['m']).sum() / max((a['m'] | b['m']).sum(), 1) < 0.6
                   and not (dc and a['src'] != b['src'] and (a['m'] & b['m']).sum() / max(a['m'].sum(), 1) > dc) for b in keep):
                keep.append(a)
        print('  %d locks -> %d after removing duplicates' % (len(locks), len(keep)))
        locks = sorted(keep, key=lambda l: l['cx'])
        N = len(locks)
        above = np.zeros((N, N))
        for a in range(N):
            for b in range(a + 1, N):
                ov = locks[a]['m'] & locks[b]['m'] & Dm
                if ov.sum() < 60:
                    continue
                ea = np.abs(locks[a]['img'][..., :3][ov] - D[..., :3][ov]).mean()
                eb = np.abs(locks[b]['img'][..., :3][ov] - D[..., :3][ov]).mean()
                above[(a, b) if ea < eb else (b, a)] = 1
        left = set(range(N)); order = []
        while left:
            c = [i for i in left if not any(above[i, j] for j in left)]
            i = min(c, key=lambda i: above[i].sum()) if c else min(left, key=lambda i: sum(above[i, j] for j in left))
            order.append(i); left.discard(i)
        # つむじ（前の髪）／後頭部のまん中（後ろ髪）: 根元は、束のうちここにいちばん近い点
        ys, xs = np.where(Dm)
        if pc.get('whorl'):
            anchor = np.array(pc['whorl'], np.float32)
        elif cap is not None:
            cy, cx_ = np.where(cap['m']); anchor = np.array([cx_.mean(), cy.mean()], np.float32)
        else:
            top = ys.min(); anchor = np.array([xs[ys < top + 12].mean(), top + 0.04 * (ys.max() - top)], np.float32)
        clip_m = cv2.dilate(Dm.astype(np.float32), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
        clip_y = ys.min() + 0.13 * (ys.max() - ys.min())          # 頭のてっぺんのあたりだけ
        items = []; dropped = 0
        for z, i in enumerate(([cap] if cap is not None else []) + [locks[i] for i in order]):
            l = i
            my, mx = np.where(l['m'])
            # 3 倍の絵での範囲
            x0 = int(np.floor(box[0] + mx.min() * k3)) - 6; y0 = int(np.floor(box[1] + my.min() * k3)) - 6
            x1 = int(np.ceil(box[0] + (mx.max() + 1) * k3)) + 6; y1 = int(np.ceil(box[1] + (my.max() + 1) * k3)) + 6
            M = l['M2'].copy(); M[0, 2] -= x0; M[1, 2] -= y0
            big = warp_rgba(l['S2'], M, (x1 - x0, y1 - y0), cv2.INTER_AREA if M[0, 0] < 0.6 else cv2.INTER_LINEAR)
            Mm = np.array([[k3, 0, box[0] - x0], [0, k3, box[1] - y0]], np.float32)
            mk = cv2.warpAffine(l['mask'].astype(np.float32), Mm, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR)
            big[..., 3] *= np.clip(mk * 2.0, 0, 1)
            # 切れ端（小さな点）を落とす
            n, lab, st, _ = cv2.connectedComponentsWithStats((big[..., 3] > 40).astype(np.uint8), connectivity=8)
            if n > 2:
                main_ = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
                big[..., 3] *= cv2.dilate((lab == main_).astype(np.uint8), np.ones((3, 3), np.uint8))
            is_cap = l is cap
            if not is_cap:
                # 頭のてっぺんのあたりでは、デザインの外形（少し広げたもの）の外を消す。毛先の側は、外形からはみ出してよい
                cm = cv2.warpAffine(clip_m, Mm, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR)
                yy_ = (np.arange(y1 - y0, dtype=np.float32)[:, None] + y0 - box[1]) / k3
                upper = yy_ < clip_y
                big[..., 3] *= np.where(upper, np.clip(cm * 2, 0, 1), 1.0)
            d2 = (mx - anchor[0]) ** 2 + (my - anchor[1]) ** 2
            j = int(d2.argmin()); root = np.array([mx[j], my[j]], np.float32)
            j2 = int(((mx - root[0]) ** 2 + (my - root[1]) ** 2).argmax()); tip = np.array([mx[j2], my[j2]], np.float32)
            r3 = [float(box[0] + root[0] * k3), float(box[1] + root[1] * k3)]; t3 = [float(box[0] + tip[0] * k3), float(box[1] + tip[1] * k3)]
            if part == 'back':
                g = 'back'
            else:
                g = 'bangs' if t3[1] < BY else 'side'
            if not is_cap:
                # 短い切れ端は外す: 長さが髪の高さの 2 割より短く、根元が、つむじ（前の髪）から遠い・後頭部（後ろ髪）に重なっていないもの。
                # 毛先だけが別の塊として描かれたもので、動かすと宙に浮いて見える。同じ絵は下地に入っているので、外しても穴は開かない
                Hh_ = ys.max() - ys.min(); ln_ = float(np.hypot(*(tip - root)))
                if cap is not None:
                    attached = bool((l['m'] & cv2.dilate(cap['m'].astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)).sum() > 20)
                else:
                    attached = float(np.hypot(*(root - anchor))) < 0.22 * Hh_
                if not attached and ln_ < float(cfg.get('min_len', 0.2)) * Hh_:
                    dropped += 1
                    continue
            items.append({'img': big, 'x': x0, 'y': y0, 'root': r3, 'tip': t3, 'g': g, 'cap': is_cap, 'thumb': l['img']})
        print('  dropped %d short loose pieces' % dropped)
        nl = sum(1 for it in items if not it['cap'])
        zi = 0
        for it in items:
            if not it['cap']:
                it['d'] = round(zi / max(nl - 1, 1), 3); zi += 1
        allimg[part] = items
        result[part] = {'box': box, 'design': D, 'k3': k3, 'W': W, 'H': H}

    # ---- 色を元の髪に合わせる（全部の束に同じ変換を掛ける）
    if cfg.get('tone_ref'):
        ref = rd(P(cfg['tone_ref']))
        if cfg.get('tone_mask'):
            # 色を合わせる先を、「基準の絵（00_base）のうち、髪のある所だけ」にする（tone_mask = 髪だけの絵。同じキャンバス）。
            # 髪だけを描き直した絵（03b）は、描き直しで色がずれる（黒い髪が、赤みのある明るい色になった）。基準の絵の髪の色へ戻す
            mk = rd(P(cfg['tone_mask']))
            if mk.shape[:2] == ref.shape[:2]:
                m_ = cv2.erode((mk[..., 3] > 200).astype(np.uint8), np.ones((9, 9), np.uint8))
                ref = ref.copy(); ref[..., 3] = ref[..., 3] * m_
            else:
                print('tone_mask: 大きさが tone_ref と違うので使いません', mk.shape[:2], ref.shape[:2])
        cat = np.concatenate([it['img'].reshape(-1, 4) for it in allimg.get('front', []) or sum(allimg.values(), [])])[None]
        src = tone_stats(cat); dst = tone_stats(ref)
        src_t, dst_t = src, dst
        print('tone: L %.0f -> %.0f, a %.0f -> %.0f, b %.0f -> %.0f' % (src[0][0], dst[0][0], src[0][1], dst[0][1], src[0][2], dst[0][2]))
        # 部分ごとに、その部分の絵の色から合わせる（前と後ろで、描かれた色が違うことがある）。後ろ髪は、少し暗くする（奥にある髪）
        tone_of = {}
        for part_, items in allimg.items():
            if not items:
                continue
            sp_ = tone_stats(np.concatenate([it['img'].reshape(-1, 4) for it in items])[None])
            dp_ = (dst[0] * np.array([float(cfg['parts'][part_].get('tone_dark', 0.94 if part_ == 'back' else 1.0)), 1, 1], np.float32), dst[1])
            tone_of[part_] = (sp_, dp_)
            for it in items:
                it['img'] = tone_apply(it['img'], sp_, dp_)
        json.dump({'src': [src[0].tolist(), src[1].tolist()], 'dst': [dst[0].tolist(), dst[1].tolist()]}, open(os.path.join(out, '_tone.json'), 'w'))

    man = {}
    f = ImageFont.truetype('arialbd.ttf', 18)
    for part, items in allimg.items():
        R = result[part]; box = R['box']
        bw, bh = box[2] - box[0], box[3] - box[1]
        asm = np.zeros((bh, bw, 4), np.float32)
        ents = []
        zi = 0
        for it in items:
            if it['cap']:
                name, fn = '後頭部', '%s_cap.png' % part
            else:
                name, fn = ('前束%02d' if part == 'front' else '後束%02d') % zi, '%s_%02d.png' % (part, zi); zi += 1
            Image.fromarray(np.clip(it['img'], 0, 255).astype(np.uint8)).save(os.path.join(out, fn))
            e = {'name': name, 'file': fn, 'x': it['x'], 'y': it['y']}
            if not it['cap']:
                e.update({'g': it['g'], 'root': it['root'], 'tip': it['tip'], 'd': it['d']})
            ents.append(e)
            h, w = it['img'].shape[:2]
            x, y = it['x'] - box[0], it['y'] - box[1]
            xa, ya, xb, yb = max(x, 0), max(y, 0), min(x + w, bw), min(y + h, bh)
            sub = it['img'][ya - y:yb - y, xa - x:xb - x]; a = sub[..., 3:4] / 255
            reg = asm[ya:yb, xa:xb]
            reg[..., :3] = reg[..., :3] * (1 - a) + sub[..., :3] * a
            reg[..., 3:4] = np.maximum(reg[..., 3:4], sub[..., 3:4])
        Image.fromarray(asm.astype(np.uint8)).save(os.path.join(out, '_locks_%s.png' % part))      # 束だけを重ねた絵（下地なし。gaps が、束の足りない所を探すのに使う）
        locks_m = asm[..., 3] > 128
        if part == 'front' and cfg['parts'][part].get('base') == 'flat':          # 古い作り（影色の面）。今は使わない
            # 前の髪の下地: 束を全部重ねた形の、上のほう（髪の生え際より上）を、影の色で塗りつぶした面。頭と一緒に動かす（揺らさない）。
            # 束どうしが揺れて離れたとき、頭の肌ではなく髪の色が見えるようにする
            am = (asm[..., 3] > 128).astype(np.uint8)
            am = cv2.morphologyEx(am, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)))
            ys, xs = np.where(am > 0)
            top, cut = ys.min(), ys.min() + cfg['parts'][part].get('base_cut', 0.42) * (BY - box[1] - ys.min())
            yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float32)
            arc = cut - 0.10 * (cut - top) * ((xx - (CX - box[0])) / HR) ** 2                # 生え際は、まん中が低く、左右が少し高い弧
            reg_ = (am > 0) & (yy < arc)
            # 前髪の裏: 前髪の束を全部重ねた形を、つむじを中心に縮めたもの（毛先のぎざぎざを残した、短い前髪の形）。
            # 束のすき間から額の肌色が細い筋になって見えるのを防ぐ。まっすぐな切り口にしないので、束が離れたときも、奥の髪に見える
            under = float(cfg['parts'][part].get('base_under', 0.72))
            if under > 0:
                bm = np.zeros((bh, bw), np.uint8)
                for it in items:
                    if not it['cap'] and it['g'] == 'bangs':
                        h_, w_ = it['img'].shape[:2]; x_, y_ = it['x'] - box[0], it['y'] - box[1]
                        xa_, ya_, xb_, yb_ = max(x_, 0), max(y_, 0), min(x_ + w_, bw), min(y_ + h_, bh)
                        bm[ya_:yb_, xa_:xb_] |= (it['img'][ya_ - y_:yb_ - y_, xa_ - x_:xb_ - x_, 3] > 128).astype(np.uint8)
                wh = cfg['parts'][part].get('whorl')
                wx_, wy_ = (wh[0] * R['k3'], wh[1] * R['k3']) if wh else (CX - box[0], float(top))
                Ms = np.array([[under, 0, wx_ * (1 - under)], [0, under, wy_ * (1 - under)]], np.float32)
                reg_ |= cv2.warpAffine(bm, Ms, (bw, bh), flags=cv2.INTER_LINEAR) > 0
            keepm = cv2.GaussianBlur(reg_.astype(np.float32), (0, 0), 3)
            keepm = np.clip((keepm - 0.5) * 6 + 0.5, 0, 1)                                    # ふちは 1〜2 画素だけなめらかに
            keepm = cv2.erode(keepm, np.ones((9, 9), np.uint8))                               # 束のふちからはみ出さないように、少し内側へ
            keepm *= cv2.erode(am, np.ones((7, 7), np.uint8)).astype(np.float32)             # 束を重ねた形（すき間をふさいだもの）の内側だけ
            op = asm[..., 3] > 200
            lum = asm[..., :3] @ LUM
            col = np.median(asm[..., :3][op & (lum > np.percentile(lum[op], 15)) & (lum < np.percentile(lum[op], 45))], axis=0)   # 影の色のあたり
            base = np.zeros((bh, bw, 4), np.float32); base[..., :3] = col; base[..., 3] = keepm * 255
            ys, xs = np.where(base[..., 3] > 2)
            x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
            Image.fromarray(base[y0:y1, x0:x1].astype(np.uint8)).save(os.path.join(out, 'front_base.png'))
            man['front_base'] = {'name': '前髪下地', 'file': 'front_base.png', 'x': int(box[0] + x0), 'y': int(box[1] + y0)}
            a = base[..., 3:4] / 255 * (1 - asm[..., 3:4] / 255)
            asm[..., :3] = asm[..., :3] * (1 - a) + base[..., :3] * a
            asm[..., 3:4] = np.maximum(asm[..., 3:4], base[..., 3:4])
        if cfg['parts'][part].get('under') or cfg['parts'][part].get('base') is True:
            # 下地: デザイン（毛束に分ける前の髪の絵の全体）を、色だけ合わせて、そのまま敷く。エンジンが、毛束と同じ「流れ」で動かす。
            # 束のすき間からは、いつも同じ髪の絵が見える。束が、宙に浮いて見えることもない。
            # （前は、前の髪には影色の面、後ろ髪には暗くして毛先を落としたデザインを、揺らさずに敷いていた。束が動くと、すき間と、浮いた切れ端が見えた）
            Du = cv2.resize(R['design'], (bw, bh), interpolation=cv2.INTER_LINEAR)
            if cfg.get('tone_ref'):
                Du = tone_apply(Du, *tone_of.get(part, (src_t, dst_t)))
            # 線を消して、少し暗くする（奥の髪に見える）。線を残すと、束が少しずれたとき、同じ線が二重に見えて、ぐしゃぐしゃになる
            k_ = int(cfg['parts'][part].get('under_noline', 15))
            if k_ > 1:
                rgb8 = np.clip(Du[..., :3], 0, 255).astype(np.uint8)
                om = (Du[..., 3] > 128).astype(np.uint8)
                # 髪の外（透明）の色は、いちばん明るい側にしておく（外形のふちが暗く落ちないように）
                rgb8[om == 0] = np.median(rgb8[om > 0], axis=0).astype(np.uint8)
                rgb8 = cv2.morphologyEx(rgb8, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_, k_)))   # 暗くて細いもの（輪郭線）を、まわりの色で埋める
                rgb8 = cv2.GaussianBlur(rgb8, (0, 0), 2.5)
                Du[..., :3] = rgb8
            dk = float(cfg['parts'][part].get('under_dark', 0.93))
            Du[..., :3] *= dk
            Du[..., 3] = np.where(Du[..., 3] > 128, 255, Du[..., 3])
            ys, xs = np.where(Du[..., 3] > 2)
            x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
            key, nm = ('front_base', '前髪下地') if part == 'front' else (part + '_under', '後ろ髪下地')
            Image.fromarray(np.clip(Du[y0:y1, x0:x1], 0, 255).astype(np.uint8)).save(os.path.join(out, key + '.png'))
            man[key] = {'name': nm, 'file': key + '.png', 'x': int(box[0] + x0), 'y': int(box[1] + y0)}
            a = Du[..., 3:4] / 255 * (1 - asm[..., 3:4] / 255)
            asm[..., :3] = asm[..., :3] * (1 - a) + Du[..., :3] * a
            asm[..., 3:4] = np.maximum(asm[..., 3:4], Du[..., 3:4])
        # 流れの、根元の高さと長さ（3 倍の絵の座標）。エンジンが、髪の全体を 1 つのしなりで動かすのに使う
        tips = [e for e in ents if e['name'] != '後頭部']
        Dm_ = cv2.resize(R['design'], (bw, bh), interpolation=cv2.INTER_LINEAR)[..., 3] > 128
        dy_, dx_ = np.where(Dm_)
        if part == 'front':
            wh = cfg['parts'][part].get('whorl')
            top = box[1] + (wh[1] * R['k3'] if wh else dy_.min())
            side = [e for e in tips if e['g'] == 'side']
            man['field_front'] = {'top': float(top), 'bangs_len': float(BY - top), 'side_len': float(box[1] + dy_.max() - top),
                                  'side_x0': float(0.72 * HR), 'side_x1': float(1.0 * HR)}
        else:
            top = min([e['y'] for e in ents if e['name'] == '後頭部'] + [box[1] + dy_.min()])
            man['field_back'] = {'top': float(top + 0.30 * (box[1] + dy_.max() - top)), 'len': float(0.70 * (box[1] + dy_.max() - top))}
        man[part] = [e for e in ents if e['name'] != '後頭部']
        if any(e['name'] == '後頭部' for e in ents):
            man[part + '_cap'] = [e for e in ents if e['name'] == '後頭部'][0]
        Image.fromarray(asm.astype(np.uint8)).save(os.path.join(out, '_asm_%s.png' % part))
        D = cv2.resize(R['design'], (bw, bh), interpolation=cv2.INTER_LINEAR)
        Am, Dm = asm[..., 3] > 128, D[..., 3] > 128
        df = on(asm, (245, 245, 245)).astype(np.float32) * 0.45 + 255 * 0.55
        df[Am & ~Dm] = (255, 60, 60); df[Dm & ~Am] = (60, 90, 255)
        chk = np.hstack([on(D, (60, 160, 90)), on(asm, (60, 160, 90)), df.astype(np.uint8)])
        Image.fromarray(chk).resize((chk.shape[1] // 2, chk.shape[0] // 2), Image.LANCZOS).save(os.path.join(out, '_check_%s.png' % part))
        print('[%s] %d locks  束の無い所 %.1f%%（下地で埋まる）、デザインの外へ出た所 %.1f%%' % (part, len(man[part]), 100.0 * (Dm & ~locks_m).sum() / Dm.sum(), 100.0 * (Am & ~Dm).sum() / Dm.sum()))
        # 一覧: 束を 1 つずつ（単体で、ふちと塗り足しを見る）
        cols, cw = 10, 190; its = [it for it in items if not it['cap']]
        rows = (len(its) + cols - 1) // cols
        sh = Image.new('RGB', (cols * cw, rows * cw), (60, 160, 90)); d = ImageDraw.Draw(sh)
        for z, it in enumerate(its):
            im = it['img']; s = (cw - 8) / max(im.shape[:2])
            t = Image.fromarray(on(im, (60, 160, 90))).resize((max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))), Image.LANCZOS)
            sh.paste(t, ((z % cols) * cw + 4, (z // cols) * cw + 4)); d.text(((z % cols) * cw + 4, (z // cols) * cw + 2), '%d %s' % (z, it['g'][:2]), fill=(255, 255, 0), font=f)
        sh.save(os.path.join(out, '_sheet_%s.png' % part))
    json.dump(man, open(os.path.join(out, 'hair_locks.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('->', os.path.join(out, 'hair_locks.json'))


if __name__ == '__main__':
    main()
