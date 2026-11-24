# -*- coding: utf-8 -*-
"""毛束を「房」にまとめる（hairlocks.py の出力 hair_locks.json を読んで、房の絵と一覧を足す）。

  hairclumps.py <hairlocks.json>

考え方（Live2D の髪の作り方と同じ）:
  髪は、細い毛束 1 本ずつではなく、「房」（前髪 5・横髪 4・後ろ髪 7〜9 くらい）で動く。房は、長さを変えずに、根元からしなる 1 つの物。
  房の中の毛束どうしは、ずれない（ずれると、すき間と線の交差が出て、ぐしゃぐしゃに見える）。
  房どうしは、別々に動いて、重なり方が変わる。房のすき間からは、下にある物（顔・後ろの房・後頭部）が見える。

やること:
  1. 毛束を、毛先の位置で、房に分ける（前の髪: 前髪 5 + 横髪の内側・外側 × 左右。後ろ髪: 頭のまわりの角度で 8）
  2. 房ごとに、毛束を重ね順のまま 1 枚に重ねる。毛束のすき間（細いすき間・囲まれた穴）は、下地（線を消した髪の絵）の色で埋める
  3. 房の根元・毛先・長さを出す（エンジンが、この軸に沿って、長さを変えずに曲げる）
出力: locks/clump_<部分>_NN.png、hair_locks.json の clumps_front・clumps_back、確認用の _clumps_<部分>.png（房ごとに色を変えた絵）
"""
import sys, os, json
import numpy as np, cv2
from PIL import Image

for _f in (sys.stdout, sys.stderr):          # 出力は UTF-8（OS の文字コードのままだと、日本語の Windows 以外で、日本語の表示で止まる）
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

cfg_p = sys.argv[1]
cfg = json.load(open(cfg_p, encoding='utf-8'))
out = os.path.join(os.path.dirname(cfg_p), cfg.get('out', 'locks'))
man_p = os.path.join(out, 'hair_locks.json')
man = json.load(open(man_p, encoding='utf-8'))
HX, R, BT = float(cfg['center_x']), float(cfg['head_r']), float(cfg['bangs_tip_y'])
CC = cfg.get('clumps', {})
COL = [(230, 60, 60), (60, 160, 230), (240, 190, 40), (90, 200, 90), (200, 90, 220), (250, 130, 40), (60, 210, 200), (150, 110, 60), (120, 120, 240), (240, 110, 160)]


def load(e):
    return np.asarray(Image.open(os.path.join(out, e['file'])).convert('RGBA')).astype(np.float32)


def kmeans(P, seeds, allow, it=6):
    """P: 点、seeds: 初めの中心、allow[i]: 点 i が入れる房の番号"""
    C = np.array(seeds, np.float64)
    lab = np.zeros(len(P), int)
    for _ in range(it):
        for i, p in enumerate(P):
            a = allow[i]
            lab[i] = a[int(np.argmin([np.hypot(*(p - C[k])) for k in a]))]
        for k in range(len(C)):
            if (lab == k).any():
                C[k] = P[lab == k].mean(0)
    return lab


def cluster_front(L):
    nb = int(CC.get('bangs', 5))
    seeds, kinds = [], []
    for i in range(nb):
        u = (i / (nb - 1) * 2 - 1) * 0.72 if nb > 1 else 0
        seeds.append([HX + R * u, BT - 0.2 * R]); kinds.append('bangs')
    for sg in (-1, 1):
        seeds.append([HX + sg * 0.62 * R, BT + 1.1 * R]); kinds.append('side')     # 横髪の内側（顔の横に垂れる、長い房）
        seeds.append([HX + sg * 1.08 * R, BT - 0.1 * R]); kinds.append('side')     # 横髪の外側（外へはねる房）
    P = np.array([[e['tip'][0], e['tip'][1]] for e in L], np.float64)
    sc = np.array([1.0, 0.6])
    side_k = [k for k, g in enumerate(kinds) if g == 'side']
    allk = list(range(len(seeds)))
    allow = [side_k if e['g'] == 'side' else allk for e in L]
    lab = kmeans(P * sc, np.array(seeds) * sc, allow)
    return lab, kinds


def cluster_back(L):
    n = int(CC.get('back', 8))
    cy = man['field_back']['top'] - 0.4 * R
    mid = np.array([[(e['root'][0] + 2 * e['tip'][0]) / 3, (e['root'][1] + 2 * e['tip'][1]) / 3] for e in L])
    ang = np.arctan2(mid[:, 0] - HX, np.maximum(mid[:, 1] - cy, 1))
    P = np.stack([ang, np.zeros(len(L))], 1)
    lo, hi = np.percentile(ang, 3), np.percentile(ang, 97)
    seeds = [[lo + (hi - lo) * i / (n - 1), 0] for i in range(n)]
    lab = kmeans(P, seeds, [list(range(n))] * len(L), it=10)
    return lab, ['back'] * n


def fix_labels(part, L, lab):
    """char.json の hair.clumps.move = {"前束11": 6, ...} で、束を別の房へ移す（自動の分け方を直すとき）"""
    for nm, k in CC.get('move', {}).items():
        for i, e in enumerate(L):
            if e['name'] == nm:
                lab[i] = int(k)
    return lab


def build(part):
    L = man.get(part) or []
    if not L:
        return
    if CC.get('each'):
        # 束が、はじめから大きな房として描いてあるとき（hairdraw.py parts）: 束 1 つ = 房 1 つ。まとめない
        lab, kinds = np.arange(len(L)), [e['g'] for e in L]
    else:
        lab, kinds = cluster_front(L) if part == 'front' else cluster_back(L)
    lab = fix_labels(part, L, lab)
    bkey = 'front_base' if part == 'front' else 'back_under'
    base = man.get(bkey)
    bimg = load(base) if base else None
    imgs = [load(e) for e in L]
    # widen: 房を、幅の向きへ、少しだけ太らせる（0.08 で 8%。widen_side は、横髪用）。房を 1 つずつ別の絵に描かせると、となりの房との境目がぴったり合わず、
    # 細いすき間から肌が見える。Live2D と同じように、となりの房の下へ、少し入りこませて重ねる。太ったぶんは、手前の房の下に隠れる。
    # 太らせ方: 行ごと（横へ流れる房は列ごと）に、その行での房のまん中を中心にして、幅だけを広げる（曲がった房でも、位置がずれない）
    wk0 = float(cfg['parts'][part].get('widen', 0)); wks = float(cfg['parts'][part].get('widen_side', wk0))
    if wk0 > 0 or wks > 0:
        pad = 120
        L = [dict(e) for e in L]
        for i, e in enumerate(L):
            wk = wks if e['g'] == 'side' else wk0
            if wk <= 0:
                continue
            im = imgs[i]
            pm = np.dstack([im[..., :3] * im[..., 3:4] / 255, im[..., 3]])
            pm = cv2.copyMakeBorder(pm, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
            d = np.array(e['tip'], np.float64) - np.array(e['root'], np.float64)
            rows = abs(d[1]) >= abs(d[0])
            if not rows:
                pm = pm.transpose(1, 0, 2).copy()
            a = pm[..., 3] > 128
            H_, W_ = a.shape
            xs_ = np.arange(W_, dtype=np.float32)
            has = a.any(1)
            cx = np.where(has, (a * xs_).sum(1) / np.maximum(a.sum(1), 1), np.nan)
            idx = np.arange(H_)
            cx = np.interp(idx, idx[has], cx[has])
            cx = cv2.GaussianBlur(cx.astype(np.float32)[:, None], (1, 0), 0, sigmaY=35)[:, 0] if False else np.convolve(np.pad(cx, 60, mode='edge'), np.ones(121) / 121, mode='valid')
            mx = (cx[:, None] + (xs_[None, :] - cx[:, None]) / (1 + wk)).astype(np.float32)
            my = np.repeat(np.arange(H_, dtype=np.float32)[:, None], W_, 1)
            o = cv2.remap(pm, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            if not rows:
                o = o.transpose(1, 0, 2).copy()
            al = o[..., 3:4]
            imgs[i] = np.dstack([np.where(al > 0.5, o[..., :3] * 255 / np.maximum(al, 0.5), 0), o[..., 3]]).astype(np.float32)
            e['x'] -= pad; e['y'] -= pad
    # adjust: 房の大きさ・比率を変えず（剛体変換: scale=1.0）、根元を支点にした回転（deg）と平行移動（dx, dy）で位置を微調整する。
    # 引き伸ばし（close_gaps）と違い、房のカーブ・輪郭線の太さ・ハイライトの比率が崩れない。
    # 指定: char.json の hair.<部分>.adjust = {"前束05": [dx, dy, deg], ...}（キーは束名またはインデックス文字列）
    adj = cfg['parts'][part].get('adjust')
    if adj:
        L = [dict(e) for e in L]
        pad = 160
        cnt = 0
        for i, e in enumerate(L):
            v = adj.get(e['name']) or adj.get(str(i))
            if not v:
                continue
            dx, dy, deg = float(v[0]), float(v[1]), float(v[2])
            im = imgs[i]
            pm = np.dstack([im[..., :3] * im[..., 3:4] / 255, im[..., 3]])
            pm = cv2.copyMakeBorder(pm, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
            rcx = float(e['root'][0]) - e['x'] + pad
            rcy = float(e['root'][1]) - e['y'] + pad
            M = cv2.getRotationMatrix2D((rcx, rcy), deg, 1.0)
            M[0, 2] += dx
            M[1, 2] += dy
            o = cv2.warpAffine(pm, M, (pm.shape[1], pm.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
            al = o[..., 3:4]
            imgs[i] = np.dstack([np.where(al > 0.5, o[..., :3] * 255 / np.maximum(al, 0.5), 0), o[..., 3]]).astype(np.float32)
            e['x'] -= pad; e['y'] -= pad
            # 根元と毛先も同じ剛体変換で更新する（揺れの軸を合わせる）
            rx, ry = float(e['root'][0]), float(e['root'][1])
            tx, ty = float(e['tip'][0]), float(e['tip'][1])
            Mg = cv2.getRotationMatrix2D((rx, ry), deg, 1.0)
            Mg[0, 2] += dx
            Mg[1, 2] += dy
            e['root'] = [rx + dx, ry + dy]
            e['tip'] = [float(Mg[0, 0] * tx + Mg[0, 1] * ty + Mg[0, 2]), float(Mg[1, 0] * tx + Mg[1, 1] * ty + Mg[1, 2])]
            cnt += 1
        print('%s: adjust %d parts (rigid)' % (part, cnt))
    # close_gaps: となり合う房の間のすき間を、埋める（素材は変えずに、房を、すき間の側へ、なめらかに広げる）。
    # 房を 1 つずつ別の絵に描かせると、房と房の間に、細いすき間（額・こめかみの肌が見える）が残る（素材と動きは良くても、すき間が目立つ）。
    #  - 行（高さ）ごとに、左から順に房を見て、となりの房との間が空いていたら（max より狭いすき間だけ。顔の開きのような広い所は、すき間ではない）、
    #    両側の房に、「すき間の半分 + 重なり（margin）」を、広げたい量として覚える。毛先に近い所（房の高さの下 taper の割合）は、だんだん 0 にする（毛先のぎざぎざを残す）。
    #  - 房は、行ごとの「まん中」を中心にして、右半分・左半分を、それぞれ別の倍率で、横へ伸ばす。
    #    **まん中の位置と、倍率は、縦方向に大きくならす**（行ごとの生の値を使うと、毛先が分かれる所で急に変わって、輪郭がギザギザに折れた）。
    #    倍率は stretch まで（輪郭線も同じ倍率で太るので、伸ばしすぎない）。足りないぶんのすき間は、残る。
    cg = cfg['parts'][part].get('close_gaps')
    if cg:
        gmax = float(cg.get('max', 0.2)) * R; mg = float(cg.get('margin', 8)); tp = float(cg.get('taper', 0.25)); smax = float(cg.get('stretch', 1.5))
        ks = int(cg.get('smooth', 121)) | 1
        pad = int(gmax) + 20
        L = [dict(e) for e in L]
        gy0 = min(e['y'] for e in L)
        gh = max(e['y'] + im.shape[0] for e, im in zip(L, imgs)) - gy0
        N = len(L)
        xl = np.full((N, gh), np.nan); xr = np.full((N, gh), np.nan); wt = np.zeros((N, gh)); cen = {}
        box = lambda v, k: np.convolve(np.pad(v, k // 2, mode='edge'), np.ones(k) / k, mode='valid')
        for i, (e, im) in enumerate(zip(L, imgs)):
            a = im[..., 3] > 128
            has = a.any(1)
            ys = np.where(has)[0]
            if not len(ys):
                continue
            first = a.argmax(1); last = a.shape[1] - 1 - a[:, ::-1].argmax(1)
            r0 = e['y'] - gy0
            xl[i, r0 + ys] = e['x'] + first[ys]; xr[i, r0 + ys] = e['x'] + last[ys]
            ya, yb = ys.min(), ys.max()
            wt[i, r0 + ys] = np.clip((yb - ys) / max(tp * (yb - ya), 1), 0, 1)
            # ならした「まん中」と、まん中から左右のふちまでの距離（絵の中の座標）
            idx = np.arange(a.shape[0])
            c = np.interp(idx, ys, (first[ys] + last[ys]) / 2.0); c = box(c, ks)
            hl = np.interp(idx, ys, np.maximum(c[ys] - first[ys], 4)); hr = np.interp(idx, ys, np.maximum(last[ys] - c[ys], 4))
            cen[i] = (c, box(hl, ks), box(hr, ks))
        exL = np.zeros((N, gh)); exR = np.zeros((N, gh))
        for y in range(gh):
            idx = [i for i in range(N) if not np.isnan(xl[i, y])]
            if len(idx) < 2:
                continue
            idx.sort(key=lambda i: xl[i, y])
            ra = idx[0]
            for b in idx[1:]:
                g = xl[b, y] - xr[ra, y]
                if 0 < g <= gmax:
                    w = min(wt[ra, y], wt[b, y])
                    exR[ra, y] = max(exR[ra, y], (g / 2 + mg) * w); exL[b, y] = max(exL[b, y], (g / 2 + mg) * w)
                if xr[b, y] > xr[ra, y]:
                    ra = b
        tot = 0; kmaxv = 0
        for i, (e, im) in enumerate(zip(L, imgs)):
            if i not in cen:
                continue
            r0 = e['y'] - gy0; hh = im.shape[0]
            c, hl, hr = cen[i]
            # 倍率（1 + k）。広げたい量 ÷ 半分の幅。上限を掛けてから、縦にならす（2 回ならして、角を作らない）
            kl = box(box(np.clip(exL[i, r0:r0 + hh] / hl, 0, smax - 1), ks), ks // 2 | 1)
            kr = box(box(np.clip(exR[i, r0:r0 + hh] / hr, 0, smax - 1), ks), ks // 2 | 1)
            if cg.get('uniform'):
                # uniform: 房ごとに、上から下まで同じ倍率で伸ばす（右半分・左半分で 1 つずつ）。房の輪郭のカーブ（デザインされた流れ）が、変わらない。
                # 行ごとに違う倍率で伸ばすと、すき間はよく閉じるが、房の形がぼってりして、ハイライトの帯もずれて、違和感が出た。
                # 倍率は、「広げたい量 ÷ 半分の幅」の、行の中での pct 番目（0 を除く）。それより広いすき間は、残る
                def one(ex, half):
                    v = (ex / half)[ex > 0.5]
                    return float(np.clip(np.percentile(v, float(cg.get('pct', 60))), 0, smax - 1)) if len(v) > 20 else 0.0
                kl = np.full(hh, one(exL[i, r0:r0 + hh], hl)); kr = np.full(hh, one(exR[i, r0:r0 + hh], hr))
            if kl.max() < 0.01 and kr.max() < 0.01:
                continue
            tot += 1; kmaxv = max(kmaxv, kl.max(), kr.max())
            pm = np.dstack([im[..., :3] * im[..., 3:4] / 255, im[..., 3]])
            pm = cv2.copyMakeBorder(pm, 0, 0, pad, pad, cv2.BORDER_CONSTANT, value=0)
            W_ = pm.shape[1]
            xs_ = np.arange(W_, dtype=np.float32)[None, :]
            c_ = (c + pad)[:, None]
            mx = np.where(xs_ >= c_, c_ + (xs_ - c_) / (1 + kr[:, None]), c_ + (xs_ - c_) / (1 + kl[:, None])).astype(np.float32)
            my = np.repeat(np.arange(hh, dtype=np.float32)[:, None], W_, 1)
            o = cv2.remap(pm, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            al = o[..., 3:4]
            imgs[i] = np.dstack([np.where(al > 0.5, o[..., :3] * 255 / np.maximum(al, 0.5), 0), o[..., 3]]).astype(np.float32)
            e['x'] -= pad
        print('%s: close_gaps %d parts, max stretch x%.2f' % (part, tot, 1 + kmaxv))
    x0 = min(e['x'] for e in L); y0 = min(e['y'] for e in L)
    x1 = max(e['x'] + im.shape[1] for e, im in zip(L, imgs)); y1 = max(e['y'] + im.shape[0] for e, im in zip(L, imgs))
    W, H = x1 - x0, y1 - y0
    bfull = np.zeros((H, W, 4), np.float32)
    if bimg is not None:
        bx, by = base['x'] - x0, base['y'] - y0
        sx0, sy0, sx1, sy1 = max(bx, 0), max(by, 0), min(bx + bimg.shape[1], W), min(by + bimg.shape[0], H)
        bfull[sy0:sy1, sx0:sx1] = bimg[sy0 - by:sy1 - by, sx0 - bx:sx1 - bx]
    # 埋める色・下地の色は、髪の「影の色」の 1 色にする（線の無い、平らな色）。
    # 髪の絵そのもの（線を消したもの）を敷いたら、房がずれたとき、同じ模様（ハイライト・影）が二重に見えて、中途半端に見えた。
    # 影の色 1 色なら、「髪の内側が見えている」絵になる（アニメ塗りの、髪の内側の塗り方）
    if bimg is not None:
        m_ = bimg[..., 3] > 200
        px = bimg[m_][:, :3]
        lum = px @ np.array([0.3, 0.59, 0.11], np.float32)
        # 影の色: 線（いちばん暗い所）を除いた、暗い側。大きな房のデザインは、影の面が少なく、暗い側が線の色に寄るので、
        # 「いちばん多い色（メインの色）を少し暗くした色」と比べて、明るい方を使う（暗すぎると、灰色のかたまりに見える）
        lo, hi = np.percentile(lum, 12), np.percentile(lum, 35)
        shade = px[(lum >= lo) & (lum <= hi)].mean(0) * float(cfg['parts'][part].get('shade_dark', 0.97))
        main = np.median(px, 0) * float(cfg['parts'][part].get('shade_main', 0.88))
        if main @ np.array([0.3, 0.59, 0.11], np.float32) > shade @ np.array([0.3, 0.59, 0.11], np.float32):
            shade = main
        bimg[..., :3] = shade
        bfull[..., :3] = shade
    kc = int(cfg['parts'][part].get('clump_close', 9)) | 1
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kc, kc))
    res, chk = [], np.zeros((H, W, 3), np.float32)
    order = sorted(set(lab.tolist()), key=lambda k: np.mean([i for i in range(len(L)) if lab[i] == k]))
    for zi, k in enumerate(order):
        mem = [i for i in range(len(L)) if lab[i] == k]
        cv = np.zeros((H, W, 4), np.float32)                       # 前乗算
        for i in mem:
            e, im = L[i], imgs[i]
            a = im[..., 3:4] / 255
            sl = (slice(e['y'] - y0, e['y'] - y0 + im.shape[0]), slice(e['x'] - x0, e['x'] - x0 + im.shape[1]))
            cv[sl] = np.dstack([im[..., :3] * a, a]) + cv[sl] * (1 - a)
        un = (cv[..., 3] > 0.5).astype(np.uint8)
        # 埋める所: 細いすき間（閉じる処理で埋まる所）と、束に囲まれた穴
        closed = cv2.morphologyEx(un, cv2.MORPH_CLOSE, ker)
        ff = np.pad(1 - closed, 1, constant_values=1).astype(np.uint8)
        cv2.floodFill(ff, None, (0, 0), 2)
        fill = ((ff[1:-1, 1:-1] != 2) | (closed > 0)).astype(np.float32)
        fill = cv2.GaussianBlur(fill, (0, 0), 1.2)
        fa = fill * bfull[..., 3] / 255
        a = cv[..., 3:4]
        rgb = cv[..., :3] + bfull[..., :3] * fa[..., None] * (1 - a)
        al = a[..., 0] + fa * (1 - a[..., 0])
        ys, xs = np.where(al > 0.004)
        cx0, cy0, cx1, cy1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        o = np.dstack([rgb / np.maximum(al[..., None], 1e-4), al * 255])[cy0:cy1, cx0:cx1]
        fn = 'clump_%s_%02d.png' % (part, zi)
        Image.fromarray(np.clip(o, 0, 255).astype(np.uint8)).save(os.path.join(out, fn))
        # 軸: 根元（いちばん上から始まる束の根元の平均）→ 毛先（長い束の毛先の平均）
        roots = np.array([L[i]['root'] for i in mem]); tips = np.array([L[i]['tip'] for i in mem])
        top = roots[:, 1].min()
        r = roots[roots[:, 1] < top + 0.15 * R].mean(0)
        proj0 = np.linalg.norm(tips - r, axis=1)
        w = (proj0 >= 0.75 * proj0.max()) * proj0 ** 2
        t = (tips * w[:, None]).sum(0) / w.sum()
        u = (t - r) / max(np.linalg.norm(t - r), 1)
        ln = float(max(((tips - r) @ u).max(), 40))
        tipp = r + u * ln
        g = kinds[k]
        res.append({'name': ('前房%02d' if part == 'front' else '後房%02d') % zi, 'file': fn, 'x': int(x0 + cx0), 'y': int(y0 + cy0), 'g': g,
                    'root': [float(r[0]), float(r[1])], 'tip': [float(tipp[0]), float(tipp[1])], 'members': [L[i]['name'] for i in mem]})
        c = np.array(COL[zi % len(COL)], np.float32)
        m = al[..., None]
        chk = chk * (1 - m) + (c * 0.55 + (rgb / np.maximum(al[..., None], 1e-4)) * 0.45) * m
        print('%s %s  束 %2d  根元 (%d,%d) 毛先 (%d,%d) 長さ %d' % (res[-1]['name'], g, len(mem), r[0], r[1], tipp[0], tipp[1], ln))
    chk = np.clip(chk, 0, 255).astype(np.uint8).copy()
    for zi, c in enumerate(res):
        p0 = (int(c['root'][0] - x0), int(c['root'][1] - y0)); p1 = (int(c['tip'][0] - x0), int(c['tip'][1] - y0))
        cv2.line(chk, p0, p1, (255, 255, 255), 3); cv2.circle(chk, p0, 9, (255, 255, 255), -1)
        cv2.putText(chk, str(zi), (p1[0] - 14, p1[1] + 44), 0, 1.5, (0, 0, 0), 8); cv2.putText(chk, str(zi), (p1[0] - 14, p1[1] + 44), 0, 1.5, (255, 255, 255), 3)
    Image.fromarray(chk).save(os.path.join(out, '_clumps_%s.png' % part))
    if bimg is not None and part == 'front':
        # 頭頂の下地: 房の根元（頭に付いたまま動かない所）の下に敷く。房が開いたとき、根元のすき間から肌が見えないように。
        # 生え際より下は、なめらかに消す（そこから下は、房のすき間から顔が見えるのが正しい）
        f = man['field_front']
        cut = f['top'] + float(cfg['parts'][part].get('top_cut', 0.4)) * f['bangs_len'] - base['y']
        yy = np.arange(bimg.shape[0], dtype=np.float32)[:, None]
        o = bimg.copy(); o[..., 3] *= np.clip((cut + 60 - yy) / 120, 0, 1)
        h_ = int(min(bimg.shape[0], cut + 62))
        Image.fromarray(np.clip(o[:h_], 0, 255).astype(np.uint8)).save(os.path.join(out, 'clump_front_top.png'))
        man['clump_front_top'] = {'name': '前髪下地', 'file': 'clump_front_top.png', 'x': base['x'], 'y': base['y']}
    if bimg is not None and part == 'back':
        if cfg['parts'][part].get('under', True) is False:
            man.pop('clump_back_under', None)
        else:
            # 後ろ髪の下地: 房のすき間から見える、内側の髪。ふちを内側へ縮めて（房の外へはみ出さないように）、房と同じように曲げて動かす
            ke = int(cfg['parts'][part].get('under_shrink', 70))
            a = cv2.erode(bimg[..., 3], cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ke + 1, 2 * ke + 1)))
            o = bimg.copy(); o[..., 3] = cv2.GaussianBlur(a, (0, 0), 1.0)
            Image.fromarray(np.clip(o, 0, 255).astype(np.uint8)).save(os.path.join(out, 'clump_back_under.png'))
            f = man['field_back']
            man['clump_back_under'] = {'name': '後ろ髪下地', 'file': 'clump_back_under.png', 'x': base['x'], 'y': base['y'], 'g': 'back', 'shared': True,
                                       'root': [HX, f['top']], 'tip': [HX, f['top'] + f['len']]}
    man['clumps_' + part] = res


for p in ('front', 'back'):
    build(p)
json.dump(man, open(man_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('ok')
