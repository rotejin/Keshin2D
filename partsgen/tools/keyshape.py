# -*- coding: utf-8 -*-
"""差分シートのコマを「キーの形」にする（絵 + まぶた・口の線）。エンジンは、キーとキーの間を、線の変形でつなぐ（絵は入れ替えない）。

  keyshape.py eye   <作業フォルダ> <シートの絵> <縦x横 例 3x3> <コマの名前,…（使わないコマは -）> <見本の範囲.json> <髪なしの 3 倍の絵>
  keyshape.py mouth <作業フォルダ> <シートの絵> <縦x横> <コマの名前,…> <見本の範囲.json> <髪なしの 3 倍の絵>

  eye:   瞳を描かせていない目のシート（tools/codex/key_eye1.txt・key_eye2.txt）。
         出力 <作業フォルダ>/key/eye_<名前>.png（まつげだけの透過の絵。見本と同じ範囲）と、key/eye.json
         （名前ごとの、上まつげの帯の上のふち T・下のふち B・下まぶたの線 L。見本の範囲を CW×CH に置いたときの画素。列は xa〜xb）。
         開いた目のコマ（open）から eye_under.png（下まつげ）・eye_corner.png（目尻・目頭の線と、目尻の影）、
         半目のコマ（o50。無ければ o70・smileNarrow・o20）から eye_crease.png（二重の線。eye.json の crease.key に、取ったコマの名前）。
  mouth: 口のシート（tools/codex/sheet_mouth.txt・key_mouth2.txt）。
         出力 key/mouth_<名前>.png（口だけの透過の絵）と、key/mouth.json（名前ごとの、口の外形の上の線 U・下の線 Lo を N 点で。左右の口角 xa・xb。
         open は、口の中が見える形かどうか）。
  確認用: key/_eye_check_<シート名>.png・key/_mouth_check_<シート名>.png（左: そろえたコマ、右: 緑の背景に重ねた絵 + 取り出した線）。

同じ種類のシートを何枚か続けて処理すると、json に足していく（同じ名前は上書き）。

  --lash-fill <面積>（eye だけ。書かなければ前と同じ）: 濃いまつげの帯に、まわりを囲まれた小さな穴（面積が、CW×CH の上でこの画素数まで）を、帯に入れる。
         目尻のはねの中に、赤みのある暗い影が描かれた絵柄では、その影が「濃いまつげ」の色の条件から外れて、帯の中の穴になり、
         モデルで、黒いはねの中に肌色の点が見える（1500 で埋まった例がある）。
  --dark-static（eye だけ。書かなければ前と同じ）: 黒い輪郭線・耳の線（見本の中の、細くてコマのふちまで続く濃い線）を、まつげから外す。
         輪郭線を黒で描く絵柄で、目尻のはねが輪郭線とつながり、線が取れないとき。
  --white-shade（eye だけ。書かなければ前と同じ）: 白目の上の、薄い紫がかった灰色の影（まつげの帯の下）も、白目に入れる。
         影が少し赤みを帯びていると（例: (202,184,195)）、白目の色の条件から外れ、白目の上のふち B が、影と白の境目（平らな線）になる。
         モデルで、帯と白目の間に肌色のすき間が開き、影は動かない灰色のまだらとして残った
  --lower-rim <高さ>（eye だけ。書かなければ前と同じ）: 白目の下のふちの線（下まぶたの線）の全体を、下まつげの絵（eye_under.png）に入れる
         （開いた目のコマの、白目のすぐ下、この画素数までにある、肌よりはっきり暗い所。黒も赤茶も。CW×CH の上で。例 8）。
         下まぶたの線のうち、黒い所は、開いた目のキーの絵（上まつげ）に入り、赤茶の所だけが、下まつげの絵に入る。
         笑って細めた目は、別のキーの絵に替わり、下まぶたが上がって瞳を切るので、線が無いと、瞳と白目が、まっすぐ切れて見える。
         下まつげの絵は、下まぶたの線について動くので、ここに線の全体があれば、どの目の形でも、瞳の下に線が付く
  --white-warm <差>（eye だけ。書かなければ 16 = 前と同じ）: 白目と見なす色の、色味の幅（R と、G・B の小さい方の差が、この値未満）。
         見本（髪なしの絵）の白目がクリーム色のキャラ（例: (254,241,226) は差 28。肌は 60 前後）は、--dark-static で、白目が見つからず、
         瞳の光が白目に選ばれて、まつげの帯と瞳のふちの全部が「白目から離れた、動かない線」になる（まつげの帯が、ほとんど消える）。
         白目の差と、肌の差の間の値にする（例 40）。probe.py で、白目と肌の RGB を測って決める
  --white-by-lash（eye だけ。書かなければ前と同じ）: 白目は、濃いまつげの帯の近く（20 画素以内）にある塊だけにする。
         眉が、明るい灰色・白（白い髪のキャラ。例 (169,168,179)）だと、眉が「色味のない明るい色」に入り、白目の無いコマ（閉じた目）で、
         眉が白目に選ばれて、「線が取れません」になる
  --white-min <明るさ>（eye だけ。書かなければ 150 = 前と同じ）: 白目と見なす明るさ（R・G・B のいちばん小さい値）の下限。
         白目の上、まつげの帯のすぐ下に、灰色の影（濃淡）が描いてある絵柄では、影の暗い所が、白目にも帯にも入らず、白目と帯の間のすき間になる。
         すき間が 4 画素を超えたコマは、「線が取れません」になる（見開いた目・困った目）。影のいちばん暗い所より小さく、帯（84 未満）より大きい値にする（例 100）
  --white-diff <差>（eye だけ。書かなければ 14 = 前と同じ）: 白目と見なす、肌の色との差（R・G・B の差のいちばん大きい値）の下限。
         肌が、白に近い、彩度の低い色のキャラ（例 (220,198,200)）では、白目の上の灰色の影が、白 → 灰色へ変わる途中で、肌と同じ明るさを通る
         （例 (207,203,204) は、肌との差 13）。そこが白目から外れて、影の暗い側が、白目から切り離され、白目と帯の間のすき間になる。
         肌と白目は、色味（--white-warm）で分かれているので、差の下限を小さくしてよい（例 6）。--white-min と一緒に使う
  --red-margin <明るさの差>（eye だけ。書かなければ 28 = 前と同じ）: 赤茶の線（下まつげ・下まぶたの線・目尻の線・二重の線）と見なす、肌より暗い幅。
         まぶたのまわりに、淡いピンクの影（ぼかした濃淡）を塗る絵柄では、影まで「赤茶の線」に入り、下まつげの絵（eye_under.png）に、
         影の切れ端が、ピンクの帯として付く（白目から 27 画素以内の所だけが入るので、形が、途中で切れる）。まつげの帯の目頭側にも、ピンクのかけらが付く。
         線（例: 明るさ 153）は入り、淡い影（例: 170〜185）は入らない値にする（肌の明るさ 204 で、例 45）
  --soft-lines（eye だけ。書かなければ前と同じ）: 下まつげの絵（eye_under.png）と、目尻の絵（eye_corner.png）を、色のしきい値で切り抜いた形ではなく、
         「その形のまわり（9 画素 広げて、ふちをぼかした範囲）を、肌より暗いぶんだけ不透明にした絵」にする。まぶたのまわりを、ぼかした濃淡で塗る絵柄
         （厚塗り）では、下まぶたの影・目尻の影が、線と同じくらい暗く、しきい値で切ると、影のふちが、角ばった枠・ちぎれた帯として絵に入る
         （--red-margin を動かしても、まわりとの差で線だけを取っても、きれいに取れなかった）。線は、はっきり、影は、なだらかに薄れる絵になる。
         白目と、まつげの帯（そのふちの 2 画素）は、入れない。--lower-rim と一緒に使う（白目のすぐ下の線は、--lower-rim が入れる）
  --lash-rb <差>（eye だけ。書かなければ 30 = 前と同じ）: 濃いまつげと見なす色の、赤みの幅（R − B が、この値未満）。
         道具は、まつげの帯を「暗くて（明るさ 84 未満）、赤みのない色（R − B が 30 未満 = 紫がかった黒）」で見分ける（輪郭線が赤茶の絵柄で、線と分けるため）。
         まつげが、赤茶がかった黒（例 (52,32,36)〜(66,25,21)。帯の画素の半分が、R − B 30 以上）の絵柄では、帯が、ちぎれた切れ端になる
         （「線が取れません」は出ないのに、帯の太さが 2〜13 しか無い。確認の絵 _eye_check で、帯が、まだらに欠けている）。
         シートの暗い画素（明るさ 50 未満）の R − B の 99% が入る値にする（例 70）。輪郭線も黒〜赤茶がかった黒の絵柄なので、--dark-static と一緒に使う
  --lash-lum <明るさ>（eye だけ。書かなければ 84 = 前と同じ）: 濃いまつげと見なす明るさの上限。
         上まつげの帯の中に、灰色のつや（帯より明るい、色味のない灰色の面。例 (119,107,113) = 明るさ 110）が描いてある絵柄では、つやが、帯の穴になる。
         帯に、まわりを囲まれた穴は --lash-fill で埋まるが、目を細めたコマでは、つやが、帯の下のふち（白目の側）まで届いて、穴が白目の側へ開き、
         埋まらない（帯の太さが 2〜5 になる。開いた目・閉じた目のコマだけ、太さが 47 前後で取れる）。つやの明るさより大きく、白目の上の影（例 194）より
         小さい値にする（例 125）。つやの中の白い点は、--lash-fill で埋める。--lash-rb・--dark-static と一緒に使う
  --static-min <面積>（eye だけ。--dark-static と一緒に。書かなければ 0 = 前と同じ）: 見本の中の「白目から離れた、濃い塊」のうち、この画素数より小さい物は、
         動かない線にしない。目尻のはねのそばの短い毛・下まつげの点が、白目から離れた小さな塊になり、広げて、シートの帯から四角く抜かれる
         （はねの付け根に、四角い欠けができる）。眉のふち・耳の線・鼻の影（動かない線にしたい物）は、ずっと大きい
"""
import sys, os, json
import numpy as np, cv2
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
CW, CH = 768, 512          # コマをそろえる大きさ（見本の範囲を、この大きさに置く）
LASH_FILL = 0              # まつげの帯に囲まれた穴を、帯に入れる面積の上限（--lash-fill。0 なら前と同じ）
DARK_STATIC = None         # 黒い輪郭線・耳の線（--dark-static。見本から作る。None なら前と同じ）
WHITE_SHADE = False        # 白目の上の、赤みのある灰色の影も、白目に入れる（--white-shade。False なら前と同じ）
WHITE_WARM = 16            # 白目と見なす、色味の幅（R と、G・B の小さい方の差が、これ未満。--white-warm。16 なら前と同じ）
LOWER_RIM = 0              # 白目の下のふちの線（下まぶたの線）の全体を、下まつげの絵（under）に入れる高さ（--lower-rim。0 なら前と同じ）
WHITE_BY_LASH = False      # 白目は、濃いまつげの帯の近くにある塊だけにする（--white-by-lash。False なら前と同じ）
WHITE_MIN = 150            # 白目と見なす明るさの下限（--white-min。150 なら前と同じ）
WHITE_DIFF = 14            # 白目と見なす、肌の色との差の下限（--white-diff。14 なら前と同じ）
RED_MARGIN = 28            # 赤茶の線と見なす、肌より暗い幅（--red-margin。28 なら前と同じ）
STATIC_MIN = 0             # 白目から離れた濃い塊のうち、これより小さい物は、動かない線にしない（--static-min。0 なら前と同じ）
SOFT_LINES = False         # 下まつげ・目尻の絵を、肌より暗いぶんだけ不透明にした、なめらかな絵にする（--soft-lines。False なら前と同じ）
LASH_RB = 30               # 濃いまつげと見なす、赤みの幅（R − B が、これ未満。--lash-rb。30 なら前と同じ）
LASH_LUM = 84              # 濃いまつげと見なす、明るさの上限（--lash-lum。84 なら前と同じ）


def dark_static(ref):
    """見本の中の、黒い動かない線（輪郭線・耳の線）。輪郭線を黒で描く絵柄では、輪郭線が「濃いまつげ」の色の条件に入り、
    目尻のはねと 1 つにつながって、コマのふちに触れる塊として外される（9 コマ中 7 コマで、線が取れなかった例がある）。
    濃い色のうち、細く（太い面を開いて残らない）、コマのふちに触れる線だけを取る。はねと交わる所は、太い面の一部なので残る"""
    r, g, b = ref[..., 0], ref[..., 1], ref[..., 2]
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    dk = ((lum < LASH_LUM) & ((r - b) < LASH_RB)).astype(np.uint8)
    core = cv2.morphologyEx(dk, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))   # 輪郭線は、太さ 8〜10 画素（CW×CH の上で）
    thin = dk & (1 - cv2.dilate(core, np.ones((3, 3), np.uint8)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(thin, connectivity=8)
    m = np.zeros((CH, CW), np.uint8)
    for k in range(1, n):
        x, y, w, h, a_ = st[k]
        if x <= 1 or y <= 1 or x + w >= CW - 1 or y + h >= CH - 1:
            m[lab == k] = 1
    m = cv2.dilate(m, np.ones((9, 9), np.uint8))           # 描かせたコマの輪郭線は、見本と数画素ずれる。はねの下に、輪郭線の短い切れ端が残った
    far = np.zeros((CH, CW), np.uint8)
    # 白目の近くに無い、濃い色の塊（眉・耳の中の線・鼻の影）も、動かない線。目のまわりを広く切り出すと、コマのふちに触れない塊として残り、
    # まぶたと一緒に動いてしまう（眉が、目のすぐ上にある絵柄）。白目の近くの塊（まつげの帯。輪郭線と交わっていても）は残す
    mn = ref.min(2)
    w0 = ((mn > 150) & ((r - np.minimum(g, b)) < WHITE_WARM)).astype(np.uint8)
    wn_, wl_, ws_, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(w0, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), connectivity=8)
    cand_ = [k for k in range(1, wn_) if ws_[k, 4] >= 300 and ws_[k, 0] > 1 and ws_[k, 0] + ws_[k, 2] < CW - 1 and ws_[k, 1] + ws_[k, 3] < CH - 1]
    if cand_:
        main_ = wl_ == max(cand_, key=lambda k: ws_[k, 4])
        near_ = cv2.dilate(main_.astype(np.uint8), np.ones((31, 31), np.uint8)) > 0
        dn_, dl_, dst_, _ = cv2.connectedComponentsWithStats(dk, connectivity=8)
        # 目の中（まつげの帯と、瞳のふちに囲まれた所）。見本には瞳が写っているので、瞳孔の黒い輪は「白目から離れた塊」になる。
        # それを動かない線にすると、閉じかけた目・笑って閉じた目で、下りてきたまつげの帯が、瞳孔のあった所で切れる（シートに瞳は無い）
        eye_ = np.zeros((CH, CW), bool)
        for k in range(1, dn_):
            if ((dl_ == k) & near_).any():
                eye_ |= dl_ == k
        eye_ &= ~(m > 0)                                   # 輪郭線・耳の線（はねと交わって、帯とつながっている）は除く
        ff_ = (eye_ | main_).astype(np.uint8); fm_ = np.zeros((CH + 2, CW + 2), np.uint8); cv2.floodFill(ff_, fm_, (0, 0), 2)
        inside_ = ff_ != 2
        iy_, ix_ = np.where(inside_)
        if len(ix_):
            # 目の中にある、ほかの白（瞳の向こう側の白目・瞳の光）のそばも、「白目の近く」（目頭側の、まつげの短い線が、帯から離れた塊になる）
            for k in cand_:
                cx_, cy_ = ws_[k, 0] + ws_[k, 2] / 2.0, ws_[k, 1] + ws_[k, 3] / 2.0
                if ix_.min() - 16 <= cx_ <= ix_.max() + 16 and iy_.min() - 16 <= cy_ <= iy_.max() + 16:
                    near_ |= cv2.dilate((wl_ == k).astype(np.uint8), np.ones((31, 31), np.uint8)) > 0
        for k in range(1, dn_):
            cm_ = dl_ == k
            if not (cm_ & near_).any() and (cm_ & ~inside_).any():
                if STATIC_MIN and dst_[k, 4] < STATIC_MIN:
                    continue                               # 小さな塊（はねのそばの短い毛・下まつげの点）は、動かない線にしない（--static-min）
                far[cm_] = 1
    return (m > 0) | (cv2.dilate(far, np.ones((13, 13), np.uint8)) > 0)  # 眉のふちの細い線も残らないように、広めに
NM = 33                    # 口の線の点の数


def cells(path, rows, cols):
    im = Image.open(path).convert("RGB"); w, h = im.size; cw, ch = w / cols, h / rows
    return [np.asarray(im.crop((round(c * cw), round(r * ch), round((c + 1) * cw), round((r + 1) * ch))).resize((CW, CH), Image.LANCZOS)).astype(np.float32)
            for r in range(rows) for c in range(cols)]


def best_shift(ref, cell, mask, R=22):
    """表情で変わらない所（mask）で、見本といちばん合うずれを探す。粗く探してから、細かく"""
    A = cv2.cvtColor(ref.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    B = cv2.cvtColor(cell.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    def score(dx, dy):
        return float(np.abs(A - np.roll(np.roll(B, dy, 0), dx, 1))[mask].mean())
    best = (1e9, 0, 0)
    for dy in range(-R, R + 1, 2):
        for dx in range(-R, R + 1, 2):
            s = score(dx, dy)
            if s < best[0]:
                best = (s, dx, dy)
    _, bx, by = best
    for dy in range(by - 2, by + 3):
        for dx in range(bx - 2, bx + 3):
            s = score(dx, dy)
            if s < best[0]:
                best = (s, dx, dy)
    return best


def load_ref(refjson, nohair):
    box = json.load(open(refjson))["box"]
    nb = Image.open(nohair).convert("RGBA")
    bg = Image.new("RGBA", nb.size, (255, 255, 255, 255)); bg.alpha_composite(nb)
    ref = np.asarray(bg.convert("RGB").crop(tuple(box)).resize((CW, CH), Image.LANCZOS)).astype(np.float32)
    return box, ref


def static_lines(ref, skin_ref, kind):
    """見本の中の、動かない線（輪郭線・耳・ほほの線・鼻）: 肌と違う色の塊のうち、ふちに触れるもの"""
    rnon = (np.abs(ref - skin_ref).max(2) > 34)
    lum = 0.3 * ref[..., 0] + 0.59 * ref[..., 1] + 0.11 * ref[..., 2]
    if kind == "eye":
        # 目尻のはねは、輪郭線や耳に重なる。濃いまつげの色（暗い紫〜黒）は、動かない線に入れない（赤茶の輪郭線・耳の線だけ）
        rnon &= lum > 80
    rn, rlab, rst, _ = cv2.connectedComponentsWithStats(rnon.astype(np.uint8), connectivity=8)
    static = np.zeros((CH, CW), np.uint8)
    for k in range(1, rn):
        x, y, w, h, a_ = rst[k]
        if x <= 1 or x + w >= CW - 1 or y + h >= CH - 1 or (kind == "mouth" and y <= 1):
            if kind == "eye" and x > CW * 0.12 and x + w < CW * 0.9 and y + h < CH - 1:
                continue                                   # コマの上のふちにだけ触れる、まん中の塊（眉など）は、ここでは外さない
            static[rlab == k] = 1
    return cv2.dilate(static, np.ones((9, 9), np.uint8))


def align(cs, ref, kind):
    st = np.zeros((CH, CW), bool)
    if kind == "eye":
        st[:, :int(CW * 0.16)] = True; st[int(CH * 0.62):, int(CW * 0.82):] = True
    else:
        st[int(CH * 0.45):, :int(CW * 0.22)] = True; st[int(CH * 0.45):, int(CW * 0.78):] = True; st[:int(CH * 0.14), int(CW * 0.4):int(CW * 0.6)] = True
    st[:8] = False; st[-8:] = False; st[:, :8] = False; st[:, -8:] = False
    skin_ref = np.median(ref.reshape(-1, 3), 0)
    out = []
    for c in cs:
        d, dx, dy = best_shift(ref, c, st)
        c = np.roll(np.roll(c, dy, 0), dx, 1)
        skin = np.median(c.reshape(-1, 3), 0)
        c = np.clip(c + (skin_ref - skin), 0, 255)
        out.append((c, dx, dy, skin - skin_ref))
    return out, skin_ref


def soft_rgba(c, mask, core_erode=2):
    """mask の所だけを残した透過の絵。ふちの画素は、肌や白目の色が混じっているので、色は内側の色を外へのばして使い、不透明度だけをなめらかにする"""
    m = mask.astype(np.uint8)
    core = cv2.erode(m, np.ones((2 * core_erode + 1, 2 * core_erode + 1), np.uint8))
    if core.sum() < 20:
        core = m
    rgb = c.copy().astype(np.uint8)
    # 内側の色を、外へのばす（近い core の色で埋める）
    inp = cv2.inpaint(rgb, ((1 - core) * 255).astype(np.uint8), 4, cv2.INPAINT_TELEA) if core.sum() < core.size else rgb
    a = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 0.9)
    a = np.clip((a - 0.25) / 0.5, 0, 1)
    return np.dstack([inp, (a * 255)]).astype(np.uint8)


def matte_rgba(c, mask, skin_ref, block, grow=9, d0=5.0, d1=24.0):
    """mask（線と影の、おおよその形）のまわりを、肌より暗いぶんだけ不透明にした、透過の絵（--soft-lines）。
    色は、コマの色そのまま。不透明度 = （肌の明るさ − その画素の明るさ）を d0〜d1 で 0〜1 にした値 ×（mask を grow 画素 広げて、ふちをぼかした範囲）。
    線（肌より 50 ほど暗い）は不透明、淡い影（10〜20 暗い）は半透明、肌と同じ明るさの所は透明になる。形のふちは、しきい値の切り口ではなく、
    絵の濃淡のとおりに薄れる。block（白目・まつげの帯とそのふち）は、入れない"""
    m = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    reg = np.clip((cv2.GaussianBlur(m.astype(np.float32), (0, 0), grow * 0.45) - 0.15) / 0.7, 0, 1)
    lum = 0.3 * c[..., 0] + 0.59 * c[..., 1] + 0.11 * c[..., 2]
    skin_lum = float(0.3 * skin_ref[0] + 0.59 * skin_ref[1] + 0.11 * skin_ref[2])
    a = np.clip((skin_lum - lum - d0) / (d1 - d0), 0, 1) * reg
    a[block] = 0
    a = cv2.GaussianBlur(a.astype(np.float32), (0, 0), 0.6)
    a[block] = 0
    return np.dstack([np.clip(c, 0, 255), a * 255]).astype(np.uint8)


def smooth1(v, sig=2.0):
    v = np.asarray(v, np.float32)
    k = max(1, int(sig * 3)); xs = np.arange(-k, k + 1); g = np.exp(-(xs / sig) ** 2 / 2); g /= g.sum()
    p = np.pad(v, k, mode="edge")
    return np.convolve(p, g, "valid")


def med1(v, k=5):
    v = np.asarray(v, np.float32); h = k // 2
    p = np.pad(v, h, mode="edge")
    return np.array([np.median(p[i:i + k]) for i in range(len(v))], np.float32)


# ---------------------------------------------------------------- 目
def eye_masks(c, skin_ref, static=None):
    """コマから、まつげ（濃い線: 上まつげ・二重・下まつげ・目のふちの線）と、白目を分ける。
    色で 3 つに分ける: 濃いまつげ（暗い紫〜黒）、赤茶の細い線（下まつげ・二重・目尻の線。顔の輪郭線・耳の線も同じ色）、白目。
    赤茶の線は、コマのふちに触れる塊（輪郭線・耳）を外す。濃いまつげは、目尻のはねが輪郭線に重なっていても、色で分かれるので残る"""
    diff = np.abs(c - skin_ref).max(2)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mn = c.min(2)
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    skin_lum = float(0.3 * skin_ref[0] + 0.59 * skin_ref[1] + 0.11 * skin_ref[2])
    white0 = (mn > WHITE_MIN) & ((r - np.minimum(g, b)) < WHITE_WARM) & (diff > WHITE_DIFF)
    if WHITE_SHADE:
        # 影の灰色: 色の幅が小さく（肌は R と B の差が 60 くらい）、B が G より小さくない（紫がかっている）
        white0 = white0 | ((mn > 150) & ((c.max(2) - mn) < 30) & (b >= g - 4) & (diff > 14))
    lashdark = (lum < LASH_LUM) & ((r - b) < LASH_RB)        # 濃いまつげ（紫がかった黒）。輪郭線・耳の線は、暗くても赤茶（R が B より大きい）。赤茶がかった黒のまつげは --lash-rb
    red = (diff > 34) & ~white0 & ~lashdark & (lum < skin_lum - RED_MARGIN)
    if DARK_STATIC is not None:                         # 黒い輪郭線・耳の線は、まつげにも、赤茶の線にも入れない（--dark-static）
        lashdark = lashdark & ~DARK_STATIC
        red = red & ~DARK_STATIC

    def inner(mask, close=3, amin=30, top_ok=False):
        m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((close, close), np.uint8))
        n, lab, st, cen = cv2.connectedComponentsWithStats(m, connectivity=8)
        keep = np.zeros((CH, CW), bool)
        for k in range(1, n):
            x, y, w, h, a = st[k]
            if a < amin or x <= 1 or x + w >= CW - 1 or y + h >= CH - 1 or y <= 1:
                continue
            if cen[k][1] > CH * 0.86 or cen[k][0] > CW * 0.93 or cen[k][1] < CH * 0.1:
                continue
            keep[lab == k] = True
        return keep & mask

    dk = inner(lashdark, amin=40)
    if LASH_FILL:
        # 目尻のはねの中の、赤みのある暗い影は、濃いまつげの色の条件から外れて、帯の中の穴になる。帯に囲まれた小さな穴だけを、帯に入れる
        ff_ = dk.astype(np.uint8).copy(); m_ = np.zeros((CH + 2, CW + 2), np.uint8); cv2.floodFill(ff_, m_, (0, 0), 2)
        hn_, hlab_, hst_, _ = cv2.connectedComponentsWithStats((ff_ == 0).astype(np.uint8), connectivity=4)
        for k_ in range(1, hn_):
            if hst_[k_, 4] <= LASH_FILL:
                dk |= hlab_ == k_
    if DARK_STATIC is not None:
        # まつげは、いちばん大きい帯と、そこから 15 画素以内の塊だけ（眉のふちの細い線・もう片方の眉の端など、離れた切れ端を落とす）
        dn_, dl_, dst_, _ = cv2.connectedComponentsWithStats(dk.astype(np.uint8), connectivity=8)
        if dn_ > 1:
            bb_ = 1 + int(np.argmax(dst_[1:, 4]))
            near_ = cv2.dilate((dl_ == bb_).astype(np.uint8), np.ones((31, 31), np.uint8)) > 0
            dk = np.isin(dl_, [k_ for k_ in range(1, dn_) if k_ == bb_ or (near_ & (dl_ == k_)).any()])
    rd = inner(red, amin=24)
    # 白目: いちばん大きい塊（鼻の光などの小さい白は外す）。穴は埋める
    wn, wlab, wst, wcen = cv2.connectedComponentsWithStats(cv2.morphologyEx(white0.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), connectivity=8)
    wmain = np.zeros((CH, CW), bool)
    eg_ = 12 if DARK_STATIC is not None else 1     # 目のまわりを広く切り出したコマでは、ふちの近くに背景の白い切れ端がある（白目の無いコマで、白目に選ばれた）
    cand = [k for k in range(1, wn) if wst[k, 4] >= 300 and wst[k, 0] > eg_ and wst[k, 0] + wst[k, 2] < CW - eg_ and wst[k, 1] > (eg_ if eg_ > 1 else -1) and wst[k, 1] + wst[k, 3] < CH - eg_ and wcen[k][0] < CW * 0.86]
    if WHITE_BY_LASH:
        # 白目は、まつげの帯のすぐ下にある。帯から離れた、色味のない明るい塊（灰色・白の眉）は、白目にしない（--white-by-lash）
        nd_ = cv2.dilate(dk.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0
        cand = [k for k in cand if ((wlab == k) & nd_).any()]
    if cand:
        big = max(cand, key=lambda k: wst[k, 4])
        wmain = cv2.dilate((wlab == big).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        wmain &= ~dk
        ff = wmain.astype(np.uint8).copy(); m = np.zeros((CH + 2, CW + 2), np.uint8); cv2.floodFill(ff, m, (0, 0), 2)
        wmain = (ff != 2) & ~dk
    # 赤茶の線（下まつげ・目尻の線・二重の線）は、コマごとに、輪郭線とつながったり離れたりして、取れ方がそろわない。
    # キーの絵には入れず（濃いまつげだけにする）、開いた目のコマからだけ取り出して、別の 1 枚（under）にする:
    #   下まつげ・目尻の線 = 白目から 27 画素以内の赤茶 / 二重の線 = 上まつげの帯のすぐ上（白目の左右の範囲の中）の赤茶
    under = np.zeros((CH, CW), bool)
    if wmain.sum() > 300:
        nearw = cv2.dilate(wmain.astype(np.uint8), np.ones((55, 55), np.uint8)) > 0
        wx = np.where(wmain.any(0))[0]; wy = np.where(wmain.any(1))[0]
        above = np.zeros((CH, CW), bool)
        above[max(0, wy.min() - 150):wy.min() + 10, wx.min():min(CW, wx.max() + 50)] = True
        neard = cv2.dilate(dk.astype(np.uint8), np.ones((91, 91), np.uint8)) > 0
        under = red & ((nearw) | (above & neard)) & ~wmain & ~dk
        n, lab, st, cen = cv2.connectedComponentsWithStats(under.astype(np.uint8), connectivity=8)
        # 小さな切れ端は落とす（帯より上は、二重の線だけを残したいので、大きめの塊だけ）
        ymid = (wy.min() + wy.max()) / 2
        up = [k for k in range(1, n) if cen[k][1] < wy.min()]
        upbig = max(up, key=lambda k: st[k, 4]) if up else -1
        under = np.isin(lab, [k for k in range(1, n) if (k == upbig) or (k not in up and st[k, 4] >= 12)])
    if LOWER_RIM and wmain.sum() > 300:
        # 白目の下のふちの線（下まぶたの線）: 列ごとに、白目のいちばん下の画素のすぐ下 LOWER_RIM 画素のうち、肌よりはっきり暗い所（黒も赤茶も）。
        # 下まつげの絵（under）に入れる（開いた目のコマのぶんだけが、eye_under.png になる）。under は、下まぶたの線 L について動くので、
        # 笑って細めた目（下まぶたが上がって、瞳を切る）でも、瞳の下に線が付く
        darkish_ = (diff > 34) & ~white0 & (lum < skin_lum - RED_MARGIN)
        below_ = np.zeros((CH, CW), bool)
        for x_ in np.where(wmain.any(0))[0]:
            yb_ = int(np.where(wmain[:, x_])[0].max())
            below_[yb_ + 1:yb_ + 1 + LOWER_RIM, x_] = True
        rim_ = darkish_ & below_
        if DARK_STATIC is not None:
            rim_ &= ~DARK_STATIC
        rim_ = cv2.morphologyEx(rim_.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0      # 1 画素の点は入れない
        under = under | (rim_ & ~wmain)
        eye_masks.rim = rim_ & ~wmain                      # do_eye が、まつげの帯と重なる所（線の黒い所）も、下まつげの絵に残すために使う
    return dk & ~wmain, wmain, under, red & ~wmain


def split_corner(under, white):
    """under のうち、目尻・目頭の線（白目の左右の端の外側にあって、白目の下のふちより上にある所）。目を閉じると、まつげの帯に隠れる"""
    wx = np.where(white.any(0))[0]; wy = np.where(white.any(1))[0]
    w = wx.max() - wx.min(); h = wy.max() - wy.min()
    yy, xx = np.mgrid[0:CH, 0:CW]
    side = (xx < wx.min() + 0.07 * w) | (xx > wx.max() - 0.05 * w)
    corner = under & side & (yy < wy.max() - 0.18 * h) & (yy > wy.min() - 4)
    # 目尻の影（下まぶたの線の目尻側にある、太い くさび形）は、全体を、目尻の線の側へ入れる。上の「白目の端から 7%」で縦に切ると、くさびの右半分が
    # 下まつげの側に残り、目を閉じたとき、まつげの帯の下に、切り口のまっすぐな しみ として見えた。
    # 下まつげの線は細いので、太さで分ける（太い所のうち、目尻側のいちばん大きい塊 = くさび）。
    # 下まつげの側（keep）には、くさびの「ほほ側のふち」（下まぶたの線の続き）だけを残す。開いた目では、その上に、くさびを重ねて描くので、境目は出ない
    low = under & (yy > wy.min() + 0.25 * h)
    body = cv2.morphologyEx(low.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    body[:, int(wx.min() + 0.5 * w):] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(body, connectivity=8)
    keep = under & ~corner
    if n > 1:
        big = 1 + int(np.argmax(st[1:, 4]))
        if st[big, 4] >= 120:
            wedge = (cv2.dilate((lab == big).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) > 0) & under
            corner = corner | wedge
            # ほほ側のふち: 肌（赤茶でも白目でもない所）から 3.5 画素以内で、白目の下から 3 割の高さより下（閉じたまつげの帯より上へ、線が出ないように）
            skin = ~(under | white)
            near_skin = cv2.dilate(skin.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) > 0
            below_white = np.zeros((CH, CW), bool)                 # 白目より下（白目の列では、白目の下のふちより下）。くさびの、白目側のふちは残さない
            for x in range(CW):
                ys = np.where(white[:, x])[0]
                below_white[(ys.max() + 1 if len(ys) else int(wy.min() + 0.5 * h)):, x] = True
            keep = (under & ~corner) | (wedge & near_skin & below_white & (yy > wy.min() + 0.72 * h))
    return corner, keep


def crease_mask(lash, red, T, xa, xb, c=None):
    """二重の線: まつげの帯の上のふち T より上にある赤茶の線（いちばん大きい塊と、まつげのはねで切れた続き）。無ければ None"""
    m = np.zeros((CH, CW), bool)
    for x in range(max(0, xa - 60), min(CW, xb + 70)):
        i = min(max(x - xa, 0), len(T) - 1)
        y1 = int(T[i]) - 1 + (10 if x > xb else 0)
        y0 = max(0, y1 - 100)
        if y1 > y0:
            m[y0:y1, x] = red[y0:y1, x]
    m &= ~lash
    if c is not None:
        # まつげのはねのふち（黒と肌色が混じった、暗い赤茶）は、線に入れない。入れると、はねが線を横切る所に、小さな こぶ が残る。
        # 二重の線は、明るい赤〜ピンク（R が大きい）
        m &= c[..., 0] > 150
    n, lab, st, cen = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n <= 1:
        return None
    big = 1 + int(np.argmax(st[1:, 4]))
    keep = lab == big
    near = cv2.dilate(keep.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 11))) > 0
    for i in range(1, n):
        if i != big and st[i, 4] >= 20 and (near & (lab == i)).any():
            keep |= lab == i
    return keep


def crease_rgba(c, keep):
    """二重の線の絵。まつげのはねが横切って切れている所は、線の色でつなぐ（線は、まつげの下に敷く。目を閉じると、はねが下がって、切れ目が見えてしまう）"""
    m = keep.astype(np.uint8)
    full = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (27, 5)))
    core = cv2.erode(m, np.ones((3, 3), np.uint8))
    if core.sum() < 20:
        core = m
    rgb = c.copy().astype(np.uint8)
    inp = cv2.inpaint(rgb, ((1 - core) * 255).astype(np.uint8), 4, cv2.INPAINT_TELEA)
    a = cv2.GaussianBlur(full.astype(np.float32), (0, 0), 0.9)
    a = np.clip((a - 0.25) / 0.5, 0, 1)
    return np.dstack([inp, (a * 255)]).astype(np.uint8), full > 0


def eye_lines(lash, white, xr=None):
    """列ごとの、上まつげの帯の上のふち T・下のふち B・下まぶたの線 L（白目の下のふち）。xr = (xa, xb) を渡すと、その範囲で出す"""
    has_white = white.sum() > 300
    T = np.full(CW, np.nan, np.float32); B = T.copy(); Lw = T.copy()
    # 上まつげの帯 = まつげの塊のうち、いちばん大きいもの
    n, lab, st, cen = cv2.connectedComponentsWithStats(lash.astype(np.uint8), connectivity=8)
    if n <= 1:
        return None
    big = 1 + int(np.argmax(st[1:, 4]))
    band = lab == big
    if has_white:
        cols = np.where(white.any(0))[0]
        for x in cols:
            ys = np.where(white[:, x])[0]
            b, l = ys.min(), ys.max() + 1
            # 白目のすぐ上の、まつげの続き（1〜3 画素のすき間は許す）
            y = b - 1; gap = 0; top = None
            while y >= 0 and gap <= 4:
                if lash[y, x]:
                    top = y; gap = 0
                else:
                    gap += 1
                y -= 1
            if top is None:
                continue
            T[x], B[x], Lw[x] = top, b, l
    else:
        for x in np.where(band.any(0))[0]:
            ys = np.where(band[:, x])[0]
            # その列の、いちばん太い連続
            runs = np.split(ys, np.where(np.diff(ys) > 2)[0] + 1)
            r = max(runs, key=len)
            T[x], B[x] = r.min(), r.max() + 1
            Lw[x] = B[x]
    ok = np.where(~np.isnan(T))[0]
    if len(ok) < 20:
        return None
    xa, xb = (int(ok.min()), int(ok.max())) if xr is None else xr
    xs = np.arange(xa, xb + 1)
    def fill(v):
        o = np.where(~np.isnan(v))[0]
        return np.interp(xs, o, v[o])           # 範囲の外は、端の値
    T2, B2, L2 = fill(T), fill(B), fill(Lw)
    if has_white:
        # 白目の無い列（目頭・目尻の外）は、上下のまぶたが合わさる所。B と L を、白目の端の列の高さのまん中へ寄せる
        wx = np.where(white.any(0))[0]
        for i, x in enumerate(xs):
            if x < wx.min() or x > wx.max():
                e = wx.min() if x < wx.min() else wx.max()
                mid = (B[e] + Lw[e]) / 2 if not np.isnan(B[e]) else B2[i]
                B2[i] = L2[i] = mid
                T2[i] = min(T2[i], mid - 2)
    B2, L2 = smooth1(med1(B2), 2.5), smooth1(med1(L2), 2.5)
    # 帯の上のふちは、上へ出る毛（はね）を除いた、帯の本体のふち。太さを、左右 ±22 列の最小でならしてから、B から引く
    th = np.maximum(B2 - T2, 2)
    k = 22; p = np.pad(th, k, mode="edge")
    th = np.array([p[i:i + 2 * k + 1].min() for i in range(len(th))], np.float32)
    T2 = B2 - smooth1(th, 6.0)
    B2 = np.maximum(B2, T2 + 2); L2 = np.maximum(L2, B2)
    return xa, xb, T2, B2, L2


def do_eye(work, sheet, grid, names, refjson, nohair):
    rows, cols = [int(v) for v in grid.split("x")]
    box, ref = load_ref(refjson, nohair)
    cs, skin_ref = align(cells(sheet, rows, cols), ref, "eye")
    static = static_lines(ref, skin_ref, "eye")
    global DARK_STATIC
    if DARK_STATIC is not None:
        DARK_STATIC = dark_static(ref)
    out = os.path.join(work, "key"); os.makedirs(out, exist_ok=True)
    jp = os.path.join(out, "eye.json")
    data = json.load(open(jp)) if os.path.isfile(jp) else {"canvas": [CW, CH], "box": box, "keys": {}}
    data["box"] = box
    res = []
    for (c, dx, dy, dskin), name in zip(cs, names):
        eye_masks.rim = None
        lash, white, under, red = eye_masks(c, skin_ref, static)
        res.append([name, c, lash, white, dx, dy, dskin, under, red, eye_masks.rim])
    # 列の範囲は、開いた目（open）の白目の範囲。このシートに open が無ければ、前に処理したシートの値
    xr = tuple(data.get("xr") or ()) or None
    for name, c, lash, white, *_ in res:
        if name == "open":
            wx = np.where(white.any(0))[0]
            xr = (int(wx.min()), int(wx.max())); data["xr"] = list(xr)
    if xr is None:
        sys.exit("open のコマがありません（列の範囲が決まりません）")
    # まつげの帯の目頭側の先は、濃い紫から赤茶へ変わっていく。濃い色だけで切ると、先がぎざぎざにちぎれるので、
    # 帯に接している赤茶（14 画素以内）は、帯に入れる。目尻のはね（白目の左端より外）のまわりは、輪郭線が近いので広げない
    xx = np.mgrid[0:CH, 0:CW][1]
    for r_ in res:
        grow = cv2.dilate(r_[2].astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (29, 29))) > 0
        add = r_[8] & grow & (xx > xr[0] + 0.6 * (xr[1] - xr[0]))
        r_[2] = r_[2] | add
        if LASH_FILL:
            # 赤茶を足したあとに、帯の中に残った小さな穴も、帯に入れる（--lash-fill）。帯の目頭側が、黒から暗い赤茶へ変わる絵柄では、
            # 足す範囲の境目（白目の幅の 6 割）の左に、足されなかった暗い赤茶が、帯の中の四角い穴として残る
            ff_ = r_[2].astype(np.uint8).copy(); m_ = np.zeros((CH + 2, CW + 2), np.uint8); cv2.floodFill(ff_, m_, (0, 0), 2)
            hn_, hlab_, hst_, _ = cv2.connectedComponentsWithStats((ff_ == 0).astype(np.uint8), connectivity=4)
            for k_ in range(1, hn_):
                if hst_[k_, 4] <= LASH_FILL:
                    r_[2] = r_[2] | (hlab_ == k_)
        r_[7] = r_[7] & ~r_[2]
        if r_[9] is not None:
            # 下まぶたの線（--lower-rim）は、まつげの帯に入った黒い所も、下まつげの絵に残す（開いた目では、同じ線を 2 枚で描くことになるが、
            # どちらも下まぶたの線 L について動くので、重なる。笑って細めた目など、別のキーの絵に替わっても、線の全体が残る）
            r_[7] = r_[7] | r_[9]
    LN = {r_[0]: eye_lines(r_[2], r_[3], xr) for r_ in res if r_[0] != "-"}
    # 二重の線は、半目のコマから取る（まつげの帯が下がって、線が、端から端まで 1 本で見えている）。開いた目のコマでは、線の左半分が
    # まつげのはねに切られて別の塊になり、右の 4 割しか取れなかった（目を閉じると、短い切れ端だけが、まぶたに浮いて見えた）。
    # エンジンは、この 1 本を、まつげの下に敷いて、帯の動きの 4 割だけ動かす（開いた目では、左半分が、まつげの下に隠れる）
    crease_view = None
    for nm_ in ("o50", "o70", "smileNarrow", "o20"):
        r_ = next((r2_ for r2_ in res if r2_[0] == nm_), None)
        if r_ is None or LN.get(nm_) is None:
            continue
        xa_, xb_, T_ = LN[nm_][0], LN[nm_][1], LN[nm_][2]
        keep = crease_mask(r_[2], r_[8], T_, xa_, xb_, r_[1])
        if keep is None:
            continue
        kx = np.where(keep.any(0))[0]
        if kx.max() - kx.min() < 0.6 * (xr[1] - xr[0]):
            continue
        rgba_c, full_c = crease_rgba(r_[1], keep)
        if SOFT_LINES:
            # 二重の線も、線のまわりを、肌より暗いぶんだけ不透明にした絵にする（まぶたの淡い影が、線から、なだらかに薄れる）。
            # まつげのはねが横切る所（帯と、そのふち）だけは、上の「線の色でつないだ絵」を使う（つながないと、目を閉じたとき、切れ目が見える）
            lz_ = cv2.dilate(r_[2].astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
            mt_ = matte_rgba(r_[1], keep, skin_ref, lz_, grow=6)
            ao_ = np.where(lz_, rgba_c[..., 3], 0)
            use_ = ao_ > mt_[..., 3]
            mt_[use_] = rgba_c[use_]
            rgba_c = mt_
        Image.fromarray(rgba_c, "RGBA").save(os.path.join(out, "eye_crease.png"))
        data["crease"] = {"key": nm_}
        crease_view = (nm_, rgba_c)
        print("二重の線: %s のコマから（x %d〜%d）" % (nm_, kx.min(), kx.max()))
        break
    tiles = []
    for name, c, lash, white, dx, dy, dskin, under, red, _rim in res:
        g = np.zeros((CH, CW, 3), np.float32); g[:] = (60, 200, 90)
        if name == "-":
            tiles.append(np.hstack([c.astype(np.uint8), g.astype(np.uint8)])); continue
        ln = LN.get(name)
        if ln is None:
            print("%s: 線が取れません" % name); tiles.append(np.hstack([c.astype(np.uint8), g.astype(np.uint8)])); continue
        xa, xb, T, B, L = ln
        rgba = soft_rgba(c, lash)
        Image.fromarray(rgba, "RGBA").save(os.path.join(out, "eye_%s.png" % name))
        if name == "open":                               # 開いた目の白目（確認用。モデルの白目は 31 の絵）と、赤茶の線（下まつげ・目尻の線・二重の線）
            Image.fromarray(soft_rgba(c, white), "RGBA").save(os.path.join(out, "eye_white_open.png"))
            if data.get("crease"):                       # 二重の線を別の 1 枚（eye_crease.png）にしたときは、ここからは外す（帯の上のふちより上の赤茶）
                yy_, xx_ = np.mgrid[0:CH, 0:CW]
                Tl = np.interp(np.arange(CW), np.arange(xa, xb + 1), T) + np.where(np.arange(CW) > xb, 10, 0)
                under = under & (yy_ >= Tl[None, :])
            corner, keep_u = split_corner(under, white)
            if SOFT_LINES:
                # 白目は、細い切れ端（目尻の影の中の、明るい筋が、白目に入った物）を落としてから、外す（落とさないと、目尻の絵に、その形の穴が開く）
                wh_ = cv2.morphologyEx(white.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0
                blk_ = wh_ | (cv2.dilate(lash.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
                if data.get("crease"):                   # 二重の線は、別の 1 枚（eye_crease.png）。帯の上のふちより上は、ここには入れない
                    blk_ = blk_ | (yy_ < Tl[None, :])
                Image.fromarray(matte_rgba(c, keep_u, skin_ref, blk_), "RGBA").save(os.path.join(out, "eye_under.png"))
                Image.fromarray(matte_rgba(c, corner, skin_ref, blk_), "RGBA").save(os.path.join(out, "eye_corner.png"))
                rgba_u = matte_rgba(c, under, skin_ref, blk_)
            else:
                Image.fromarray(soft_rgba(c, keep_u, core_erode=1), "RGBA").save(os.path.join(out, "eye_under.png"))
                Image.fromarray(soft_rgba(c, corner, core_erode=1), "RGBA").save(os.path.join(out, "eye_corner.png"))
                rgba_u = soft_rgba(c, under, core_erode=1)
        data["keys"][name] = {"xa": xa, "xb": xb, "T": [round(float(v), 2) for v in T], "B": [round(float(v), 2) for v in B], "L": [round(float(v), 2) for v in L],
                              "closed": bool(white.sum() <= 300)}
        al = rgba[..., 3:4] / 255.0
        v = (rgba[..., :3] * al + g * (1 - al)).astype(np.uint8).copy()
        if name == "open":
            au = rgba_u[..., 3:4] / 255.0
            v = (rgba_u[..., :3] * au + v * (1 - au)).astype(np.uint8)
        if crease_view and crease_view[0] == name:       # 二重の線を取ったコマには、取った線を重ねて見せる
            au = crease_view[1][..., 3:4] / 255.0
            v = (crease_view[1][..., :3] * au + v * (1 - au)).astype(np.uint8)
        v[white] = (v[white] * 0.4 + np.array([255, 255, 255]) * 0.6).astype(np.uint8)
        for i, x in enumerate(range(xa, xb + 1)):
            for arr, col in ((T, (255, 60, 60)), (B, (255, 220, 0)), (L, (0, 120, 255))):
                y = int(round(arr[i]))
                if 0 <= y < CH:
                    v[y, x] = col
        cv2.putText(v, name, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        tiles.append(np.hstack([c.astype(np.uint8), v]))
        print("%-12s ずれ dx %+d dy %+d  肌の差 %+.0f %+.0f %+.0f  開き（まん中） %.1f  帯の太さ %.1f  白目 %d" % (name, dx, dy, *dskin, float((L - B)[len(B) // 2]), float((B - T)[len(B) // 2]), int(white.sum())))
    json.dump(data, open(jp, "w"))
    chk = np.vstack(tiles)
    p = os.path.join(out, "_eye_check_%s.png" % os.path.splitext(os.path.basename(sheet))[0])
    Image.fromarray(chk).save(p); print(p)


# ---------------------------------------------------------------- 口
def mouth_mask(c, skin_ref, static):
    diff = np.abs(c - skin_ref).max(2)
    non = (diff > 34).astype(np.uint8)
    non = cv2.morphologyEx(non, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    non[static > 0] = 0
    n, lab, st, cen = cv2.connectedComponentsWithStats(non, connectivity=8)
    keep = np.zeros((CH, CW), np.uint8)
    for k in range(1, n):
        x, y, w, h, a = st[k]
        if a < 60 or x <= 1 or x + w >= CW - 1 or y + h >= CH - 1 or y <= 1:
            continue
        if not (CW * 0.22 < cen[k][0] < CW * 0.78 and CH * 0.14 < cen[k][1] < CH * 0.76):
            continue
        keep[lab == k] = 1
    line = keep.copy()
    ff = keep.copy(); m = np.zeros((CH + 2, CW + 2), np.uint8); cv2.floodFill(ff, m, (0, 0), 2)
    keep = ((ff != 2) | (keep == 1))
    inside = keep & (line == 0)                          # 線に囲まれた内側（口の中）
    return keep, int(inside.sum())


def do_mouth(work, sheet, grid, names, refjson, nohair):
    rows, cols = [int(v) for v in grid.split("x")]
    box, ref = load_ref(refjson, nohair)
    cs, skin_ref = align(cells(sheet, rows, cols), ref, "mouth")
    static = static_lines(ref, skin_ref, "mouth")
    out = os.path.join(work, "key"); os.makedirs(out, exist_ok=True)
    jp = os.path.join(out, "mouth.json")
    data = json.load(open(jp)) if os.path.isfile(jp) else {"canvas": [CW, CH], "box": box, "keys": {}}
    data["box"] = box
    tiles = []
    for (c, dx, dy, dskin), name in zip(cs, names):
        g = np.zeros((CH, CW, 3), np.float32); g[:] = (60, 200, 90)
        if name == "-":
            tiles.append(np.hstack([c.astype(np.uint8), g.astype(np.uint8)])); continue
        m, inside = mouth_mask(c, skin_ref, static)
        if m.sum() < 80:
            print("%s: 口が取れません" % name); tiles.append(np.hstack([c.astype(np.uint8), g.astype(np.uint8)])); continue
        # 色のある所のうち、肌にごく近い薄い色（口の下の唇のつや）は、線と離れていれば落とす: いちばん大きい塊と、その幅の中の塊だけ
        n, lab, st, cen = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        big = 1 + int(np.argmax(st[1:, 4]))
        m = lab == big
        xsm = np.where(m.any(0))[0]
        xa, xb = int(xsm.min()), int(xsm.max())
        U = np.array([np.where(m[:, x])[0].min() for x in range(xa, xb + 1)], np.float32)
        Lo = np.array([np.where(m[:, x])[0].max() + 1 for x in range(xa, xb + 1)], np.float32)
        U, Lo = smooth1(med1(U, 3), 1.2), smooth1(med1(Lo, 3), 1.2)
        uu = np.linspace(0, len(U) - 1, NM)
        Us, Ls = np.interp(uu, np.arange(len(U)), U), np.interp(uu, np.arange(len(Lo)), Lo)
        rgba = soft_rgba(c, m, core_erode=1)
        Image.fromarray(rgba, "RGBA").save(os.path.join(out, "mouth_%s.png" % name))
        is_open = float((Ls - Us).max()) > 34          # 線だけの口は、高さ（線の太さ）が 10〜16
        data["keys"][name] = {"xa": xa, "xb": xb, "U": [round(float(v), 2) for v in Us], "Lo": [round(float(v), 2) for v in Ls], "open": bool(is_open)}
        al = rgba[..., 3:4] / 255.0
        v = (rgba[..., :3] * al + g * (1 - al)).astype(np.uint8).copy()
        for i in range(NM):
            x = int(round(xa + (xb - xa) * i / (NM - 1)))
            for arr, col in ((Us, (255, 255, 0)), (Ls, (0, 120, 255))):
                y = int(round(arr[i]))
                if 0 <= y < CH:
                    cv2.circle(v, (x, y), 2, col, -1)
        cv2.putText(v, name + (" open" if is_open else ""), (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        tiles.append(np.hstack([c.astype(np.uint8), v]))
        print("%-10s ずれ dx %+d dy %+d  肌の差 %+.0f %+.0f %+.0f  幅 %d  高さ %.0f  口の中 %d %s" % (name, dx, dy, *dskin, xb - xa, float((Ls - Us).max()), inside, "開" if is_open else "線"))
    json.dump(data, open(jp, "w"))
    chk = np.vstack(tiles)
    p = os.path.join(out, "_mouth_check_%s.png" % os.path.splitext(os.path.basename(sheet))[0])
    Image.fromarray(chk).save(p); print(p)


if __name__ == "__main__":
    if "--lash-fill" in sys.argv:
        i_ = sys.argv.index("--lash-fill"); LASH_FILL = int(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if "--dark-static" in sys.argv:
        DARK_STATIC = True; sys.argv.remove("--dark-static")
    if "--white-shade" in sys.argv:
        WHITE_SHADE = True; sys.argv.remove("--white-shade")
    if "--lower-rim" in sys.argv:
        i_ = sys.argv.index("--lower-rim"); LOWER_RIM = int(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if "--white-warm" in sys.argv:
        i_ = sys.argv.index("--white-warm"); WHITE_WARM = float(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if "--white-by-lash" in sys.argv:
        WHITE_BY_LASH = True; sys.argv.remove("--white-by-lash")
    if "--red-margin" in sys.argv:
        i_ = sys.argv.index("--red-margin"); RED_MARGIN = float(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if "--white-diff" in sys.argv:
        i_ = sys.argv.index("--white-diff"); WHITE_DIFF = float(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if "--white-min" in sys.argv:
        i_ = sys.argv.index("--white-min"); WHITE_MIN = float(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if "--soft-lines" in sys.argv:
        SOFT_LINES = True; sys.argv.remove("--soft-lines")
    if "--static-min" in sys.argv:
        i_ = sys.argv.index("--static-min"); STATIC_MIN = int(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if "--lash-rb" in sys.argv:
        i_ = sys.argv.index("--lash-rb"); LASH_RB = float(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if "--lash-lum" in sys.argv:
        i_ = sys.argv.index("--lash-lum"); LASH_LUM = float(sys.argv[i_ + 1]); del sys.argv[i_:i_ + 2]
    if len(sys.argv) < 8 or sys.argv[1] not in ("eye", "mouth"):
        sys.exit(__doc__)
    (do_eye if sys.argv[1] == "eye" else do_mouth)(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5].split(","), sys.argv[6], sys.argv[7])
