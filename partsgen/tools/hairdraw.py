# -*- coding: utf-8 -*-
"""hairdraw.py <キャラ名> <段階> [部分...]   髪を「大きな房 1 つ = パーツ 1 つ」に分けて描かせる（手順は WORKFLOW.md の「髪」の章）

今の手順で使う段階（この順）:
  key             髪型を整理した、キャラクターの完成絵（キービジュアル）を描かせる。髪のパーツを作る前に、全体の絵で髪型を決める。
                  指示文は chars/<キャラ名>/prompts/hair_key.txt。00_base_3x.png（PY upscale の出力）と、char.json の hair.back の box・size が要る
  design <部分>   髪を、房のはっきりしたフラット塗りに描き直させる（デザイン）。指示文は chars/<キャラ名>/prompts/hair_design_<部分>.txt
  parts <部分>    房を、見て決める。char.json の hair.<部分>.parts（房の名前と、おおよその範囲の多角形）から、目印の絵を作る
  draw <部分>     組ごとに、「元の位置のまま、目印の房だけ」を描かせる（後ろ髪は、後頭部も）
  locks           描かせた房を切り出して、モデルに入れられる形にする（hairlocks.py）。続けて、「房」のレイヤーにまとめる（hairclumps.py）
前の方式の段階（細い毛束に自動で分ける。今の手順では使わない）:
  map <部分>      デザインの「毛束の塗り分け図」を描かせる
  split <部分>    デザインを、輪郭線と塗り分け図で毛束ごとの領域に分け、となり合わない束の組ごとに、目印の絵を作る（parts の代わり）
  gaps <部分>     重ねてもまだ埋まらない所（すき間）に、束を足して描かせる（そのあと locks をやり直す）

部分は front（前の髪: 前髪・頭頂・横髪）と back（後ろ髪）。設定は char.json の "hair"（ひな形 chars/_template/char.json に、項目がそろっている）:
  {"front": {"from": "03b_front_hair_only", "box": [x0,y0,x1,y1], "size": [1024,1024], "kind": 指示文に入れる呼び名, "whorl": [x,y], "parts": [...]},
   "back":  {"from": "04_back_hair", "box": [...], "size": [1536,1024], "kind": ..., "cap": true, "under": false, "parts": [...]},
   "center_x": 顔の中心, "head_r": 頭の半幅, "bangs_tip_y": 前髪と横髪を分ける高さ（どれも 3 倍の絵の座標）, "tone_ref": 色を合わせる先の絵（"00_base" を勧める）, "tone_mask": tone_ref の中の髪の範囲を示す絵（"03b_front_hair_only"）}
指示文（hair_key.txt・hair_design_<部分>.txt）の中の {OUT} は、保存させる名前（key_1・design_front など）に置き換えて渡す。指示文には、
保存する名前を {OUT}.png と書いておく（key は、同じ指示文で 2 案を描かせるので、名前を固定で書くと 2 枚目が保存されない）。
作業フォルダは <キャラの作業フォルダ>/hair（src: 描かせた絵、grp: 目印、locks: 出来上がり）。作業フォルダの置き場所は kenv.py（環境変数 KESHIN2D_WORK で変えられる）。
"""
import sys, os, json, glob, shutil, subprocess, threading, time
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
HERE = os.path.dirname(os.path.abspath(__file__))
PARTSGEN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kenv
CODEX = os.path.join(HERE, 'codex')
PAL = {'red': (240, 20, 20), 'orange': (255, 130, 0), 'yellow': (255, 255, 0), 'lime': (170, 240, 20), 'green': (0, 170, 50),
       'cyan': (60, 210, 255), 'blue': (0, 60, 240), 'purple': (150, 30, 230), 'pink': (255, 140, 200), 'brown': (140, 90, 50),
       'black': (25, 25, 25), 'white': (255, 255, 255), 'cap': (200, 200, 200)}
ROOT_TEXT = {
    'front': '- 根元: どの毛束も、頭頂のつむじ（絵のいちばん上のまん中）へ向かって、細くすぼまりながら続きます。つむじの少し手前で、とがって終わらせます（ほかの毛束の根元に触れないように）。',
    'back': '- 根元: 後ろ髪の毛束は、上の丸いドーム（後頭部）から下りています。どの毛束も、根元を、後頭部の下に隠れる側（上）へ少し長めに描き足して、上へ行くほど細くすぼまって終わらせます（平らな切り口にしません）。根元のほうは、後頭部と同じ色・同じ明るさにして、輪郭線を薄くします（後頭部となめらかにつながるように）。後頭部そのもの（丸いドーム）は描きません。\n- 毛先の色が違う髪（毛先だけ別の色）は、hair.png と同じ毛束にだけ、同じように入れます。',
}
GAP_TEXT = '\n- 赤い所は、毛束の幅いっぱいに塗ってあります。描く毛束の幅は、赤い所より細くしないでください（少し広めにします）。'
# 房の目印を、房の幅いっぱいに取ったとき（char.json の hair.<部分>.parts_full: true）。
# デザインが、細い毛筋を 1 本ずつ輪郭線で囲んだ絵のとき、「赤い所を含む房 1 つ」と頼むと、毛筋 1 本だけの細い束が描かれて、
# 重ねても面が埋まらない（kurage02: 前の髪は 9 本の細い束、後ろ髪は 5 本の細い束になり、顔の横と首の後ろが抜けた）。
# 赤い範囲の全体を、中の毛筋ごと、1 つの房として写させる
FULL_TEXT = ('\n- **今回の毛束は、大きな「房」です。赤く塗った範囲の全体が、1 つの房です。** 赤い範囲には、hair.png の細い毛筋が何本も入っています。'
             'その全部を、まとめて 1 つのつながった形（1 つのパーツ）として、hair.png のとおりに写してください（外形・中の線・塗り・毛先の形と数を、そのまま）。'
             '赤い範囲の中の 1 本だけを取り出したり、細い 1 本の束に描き直したり、形を単純な葉っぱ形にしたりしないでください。'
             '**房の幅は、赤い範囲より細くしません。** となりの房の下に隠れる左右のふちは、赤い範囲より少し外まで、同じ絵柄で広めに描き足します（動いたとき、すき間が開かないように）。'
             '房の毛先は、赤い範囲の下の端にある毛先までです。赤くない房の毛先は描きません。赤い範囲が 2 つ以上あるときは、それぞれを別の房として、互いに離して描きます。')
ROOT_FULL = {
    'front': ROOT_TEXT['front'],
    'back': '- 根元: 房の上の端は、後頭部（丸いドーム）の下に隠れます。赤い範囲の上の端から、さらに上へ少し（房の長さの 1〜2 割）描き足して、**幅を保ったまま**、ゆるい弧で終わらせます（細くとがらせません）。根元のほうは、後頭部と同じ色・同じ明るさにして、輪郭線を薄くします（後頭部となめらかにつながるように）。後頭部そのもの（丸いドーム）は描きません。\n- 毛先の色が違う髪（毛先だけ別の色）は、hair.png と同じ毛先にだけ、同じように入れます。',
}


def codex_exe():
    exe = kenv.codex_exe()                           # 探し方は kenv.py（pipeline.py と同じ）
    if not exe:
        sys.exit('Codex CLI が見つかりません。環境変数 CODEX_EXE に codex の実行ファイルを指定してください。')
    return exe


class Ctx:
    def __init__(self, char):
        self.char = char
        self.chardir = os.path.join(PARTSGEN, 'chars', char)
        cfg = os.path.join(self.chardir, 'char.json')
        if not os.path.isfile(cfg):
            sys.exit('キャラの設定がありません: ' + cfg)
        self.conf = json.load(open(cfg, encoding='utf-8'))
        self.hair = self.conf.get('hair') or sys.exit('char.json に "hair" がありません')
        # 完成絵の見本（chara.png）の背景色。char.json の hair.ref_bg: [R, G, B]（書かなければ白 = 前と同じ）。
        # 髪が白・白銀のキャラは、白い背景では、髪の外形（毛先・はねた毛）が背景に溶けて、見本から読み取れない。
        # キャラの絵に無い色（髪より暗く、服より明るい色）にする（WORKFLOW.md の段階 2）
        self.ref_bg = tuple(int(v) for v in self.hair.get('ref_bg', (255, 255, 255)))
        self.work = kenv.char_work(char)
        self.hd = os.path.join(self.work, 'hair')
        for d in ('src', 'grp', 'jobs'):
            os.makedirs(os.path.join(self.hd, d), exist_ok=True)

    def src(self, name):
        return os.path.join(self.hd, 'src', name + '.png')

    def crop(self, stem, part, bg):
        """3 倍の絵の、その部分の範囲を、背景色に重ねて切り出す"""
        pc = self.hair[part]
        p = os.path.join(self.work, stem + '_3x.png')
        if not os.path.isfile(p):
            sys.exit('3 倍の絵がありません（先に PY upscale <キャラ名> を）: ' + p)
        im = Image.open(p).convert('RGBA')
        b = Image.new('RGBA', im.size, tuple(bg) + (255,)); b.alpha_composite(im)
        # 範囲が、絵の外へ出てもよい（外は、背景色で埋める）。髪が、絵の幅いっぱい・絵の上の端まであるキャラ（大きく広がる髪、高いアホ毛）は、
        # 余白を 1 割取ると、範囲が絵からはみ出す。PIL の crop のままだと、はみ出した所が黒くなり、描かせた絵に黒い帯が入る
        x0, y0, x1, y1 = [int(round(v)) for v in pc['box']]
        out = Image.new('RGBA', (x1 - x0, y1 - y0), tuple(bg) + (255,))
        out.paste(b, (-x0, -y0))
        return out.convert('RGB').resize(tuple(pc['size']), Image.LANCZOS)


def on_gray(path):
    D = np.asarray(Image.open(path).convert('RGBA')).astype(np.float32)
    return Image.fromarray((D[..., :3] * (D[..., 3:4] / 255) + 128 * (1 - D[..., 3:4] / 255)).astype(np.uint8))


def run_jobs(c, jobs, par=4):
    """jobs: [(出力の名前, 指示文, {渡す名前: PIL の絵})]。同時に par 個まで。出来た絵は hair/src/<名前>.png"""
    if os.environ.get('HAIR_ONLY'):                 # HAIR_ONLY=front_in_1,back_in_0: その絵だけ描き直す
        jobs = [j_ for j_ in jobs if j_[0] in os.environ['HAIR_ONLY'].split(',')]
    exe = codex_exe(); res = {}; sem = threading.Semaphore(par)

    def one(name, prompt, ins):
        with sem:
            job = os.path.join(c.hd, 'jobs', name)
            shutil.rmtree(job, ignore_errors=True); os.makedirs(job)
            args = []
            for nm, im in ins.items():
                im.save(os.path.join(job, nm + '.png')); args += ['-i', nm + '.png']
            open(os.path.join(job, 'prompt.txt'), 'w', encoding='utf-8').write(prompt)
            t0 = time.time()
            try:
                with open(os.path.join(job, 'out.txt'), 'wb') as log:
                    subprocess.run([exe, 'exec', '--skip-git-repo-check', '-s', 'workspace-write', '-C', job] + args + ['-'],
                                   input=prompt.encode('utf-8'), stdout=log, stderr=subprocess.STDOUT, cwd=job, timeout=420)
            except subprocess.TimeoutExpired:
                pass
            got = os.path.join(job, name + '.png')
            if os.path.isfile(got):
                dst = c.src(name)
                if os.path.isfile(dst):                      # やり直しのときは、前の絵を残す
                    os.makedirs(os.path.join(c.hd, '_tries'), exist_ok=True)
                    shutil.move(dst, os.path.join(c.hd, '_tries', '%s_%d.png' % (name, int(os.path.getmtime(dst)))))
                shutil.copy(got, dst)
                im = Image.open(dst).convert('RGBA')
                n = cv2.connectedComponentsWithStats((np.asarray(im)[..., 3] > 128).astype(np.uint8))[0] - 1
                b = Image.new('RGBA', im.size, (0, 200, 0, 255)); b.alpha_composite(im)
                os.makedirs(os.path.join(c.hd, '_check'), exist_ok=True)
                b.convert('RGB').save(os.path.join(c.hd, '_check', 'v_' + name + '.png'))
                res[name] = '%3d 秒  大きさ %s  塊 %d' % (time.time() - t0, im.size, n)
            else:
                res[name] = '%3d 秒  失敗（記録: %s）' % (time.time() - t0, os.path.join(job, 'out.txt'))

    th = [threading.Thread(target=one, args=j) for j in jobs]
    for t in th: t.start()
    for t in th: t.join()
    for name, _, _ in jobs:
        print('%-16s %s' % (name, res.get(name)))
    print('緑の背景に重ねた確認画像:', os.path.join(c.hd, '_check'))


def tpl(name, **kw):
    s = open(os.path.join(CODEX, name), encoding='utf-8').read()
    for k, v in kw.items():
        s = s.replace('{' + k + '}', str(v))
    return s


# ---------------------------------------------------------------- design / map
def design(c, part):
    pr = os.path.join(c.chardir, 'prompts', 'hair_design_%s.txt' % part)
    if not os.path.isfile(pr):
        sys.exit('指示文がありません: ' + pr)
    name = 'design_' + part
    prompt = open(pr, encoding='utf-8').read().replace('{OUT}', name) + '\n' + open(os.path.join(CODEX, 'hair_design_rules.txt'), encoding='utf-8').read()
    ins = {'chara': c.crop('00_base', part, c.ref_bg), 'hair': c.crop(c.hair[part]['from'], part, (128, 128, 128))}
    if os.path.isfile(c.src('key')):
        # 全体の絵（キービジュアル。HD key で描かせて、選んだものを hair/src/key.png に置く）があれば、その部分の範囲を切り出して渡す。
        # キービジュアルは、後ろ髪の範囲（頭のまわりの全体）で描いてある
        kb, pb = c.hair['back']['box'], c.hair[part]['box']
        k = Image.open(c.src('key')).convert('RGB')
        sc = k.width / float(kb[2] - kb[0])
        cv = Image.new('RGB', (int(round((pb[2] - pb[0]) * sc)), int(round((pb[3] - pb[1]) * sc))), c.ref_bg)
        cv.paste(k, (int(round((kb[0] - pb[0]) * sc)), int(round((kb[1] - pb[1]) * sc))))
        ins['key'] = cv.resize(ins['hair'].size, Image.LANCZOS)
    run_jobs(c, [(name, prompt, ins)])


def key(c, part):
    """髪型を整理した、キャラクターの完成絵（キービジュアル）を描かせる。髪のパーツを作る前に、顔・帽子・服と合わせた全体の絵で、髪型を決める。
    （髪だけの絵を、前と後ろで別々に描かせてからパーツにしたら、塗り・動き・パーツ分けは良くても、髪型の全体としてのまとまりが足りなかった）
    HAIR_KEY_N=2 で、案を 2 枚。出来た絵は hair/src/key_1.png …（範囲は、後ろ髪の範囲 = 頭のまわりの全体）"""
    if part != 'back':
        return
    kp = os.path.join(c.chardir, 'prompts', 'hair_key.txt')
    if not os.path.isfile(kp):
        sys.exit('指示文がありません: ' + kp)
    pr = open(kp, encoding='utf-8').read()
    if '{OUT}' not in pr:
        sys.exit('hair_key.txt に {OUT} がありません。保存する名前を {OUT}.png と書いてください（同じ指示文で、案を key_1・key_2 … と描かせます）')
    chara = c.crop('00_base', 'back', c.ref_bg)
    run_jobs(c, [('key_%d' % (i + 1), pr.replace('{OUT}', 'key_%d' % (i + 1)), {'chara': chara}) for i in range(int(os.environ.get('HAIR_KEY_N', 2)))])


def hmap(c, part):
    extra = ''
    if c.hair[part].get('cap'):
        extra = '- 後頭部（上の丸いドーム。毛束に分かれていない、なめらかな面）は、全体を 1 つとして、薄い灰色で塗ります。後頭部と毛束の境目は、毛束が後頭部から分かれ始める高さ（毛束どうしの間の切れ込みのいちばん上をつないだ、ゆるい弧）にします。そこから下は、毛束ごとに塗り分けます。'
    name = 'map_' + part
    run_jobs(c, [(name, tpl('hair_map.txt', OUT=name, KIND=c.hair[part]['kind'], EXTRA=extra), {'hair': on_gray(c.src('design_' + part))})])


# ---------------------------------------------------------------- split
def split(c, part, amin=None, gap=21):
    """デザインを、「輪郭線」と「塗り分け図の色」の両方で区切って、毛束ごとの領域にする。そのあと、となり合わない領域の組に分ける。
    領域は、描かせる束を指し示す目印に使うだけなので、少しくらい断片が混じってもよい（同じ束を 2 回描いたら、あとで片方を捨てる）"""
    D = np.asarray(Image.open(c.src('design_' + part)).convert('RGBA')).astype(np.float32)
    rgb, op = D[..., :3], D[..., 3] > 128
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    line = cv2.dilate((op & (lum < np.median(lum[op]) * 0.62)).astype(np.uint8), k3) > 0
    m = np.asarray(Image.open(c.src('map_' + part)).convert('RGB').resize((D.shape[1], D.shape[0]), Image.LANCZOS))
    m = cv2.medianBlur(m, 5).astype(np.float32)
    pal = np.array(list(PAL.values()), np.float32)
    cls = ((m[:, :, None, :] - pal[None, None]) ** 2).sum(-1).argmin(-1)
    amin = amin or int(0.0012 * D.shape[0] * D.shape[1])
    lab = np.zeros(op.shape, np.int32); nxt = 1; caps = set()
    k7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    for ci in range(len(pal)):
        msk = cv2.morphologyEx((op & ~line & (cls == ci)).astype(np.uint8), cv2.MORPH_OPEN, k7)
        n, l, st, _ = cv2.connectedComponentsWithStats(msk, connectivity=4)
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] >= amin:
                lab[l == i] = nxt
                if ci == len(pal) - 1:
                    caps.add(nxt)
                nxt += 1
    ids = [i for i in range(1, nxt) if i not in caps]
    K = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gap, gap))
    dil = {i: cv2.dilate((lab == i).astype(np.uint8), K) > 0 for i in ids}
    adj = {i: {j for j in ids if j != i and (dil[i] & dil[j]).any()} for i in ids}
    grp, size = {}, {}
    for i in sorted(ids, key=lambda i: -len(adj[i])):
        used = {grp[j] for j in adj[i] if j in grp}
        free = [g for g in size if g not in used]
        g = min(free, key=lambda g: size[g]) if free else len(size)
        grp[i] = g; size[g] = size.get(g, 0) + 1
    for f in glob.glob(os.path.join(c.hd, 'grp', part + '_g*.png')):
        os.remove(f)
    bg = np.asarray(on_gray(c.src('design_' + part))).astype(np.float32)
    tiles = []
    for g in sorted(size):
        mk = np.isin(lab, [i for i in ids if grp[i] == g])
        img = bg.copy(); img[mk] = img[mk] * 0.35 + np.array([255, 0, 0], np.float32) * 0.65
        Image.fromarray(img.astype(np.uint8)).save(os.path.join(c.hd, 'grp', '%s_g%d.png' % (part, g)))
        tiles.append(cv2.resize(img.astype(np.uint8), (420, int(420 * img.shape[0] / img.shape[1]))))
    Image.fromarray(np.hstack(tiles)).save(os.path.join(c.hd, 'grp', part + '_groups.png'))
    json.dump({str(g): size[g] for g in sorted(size)}, open(os.path.join(c.hd, 'grp', part + '_groups.json'), 'w'))
    print('%s: 領域 %d 個を %d 組に分けた %s  一覧: %s' % (part, len(ids), len(size), [size[g] for g in sorted(size)], os.path.join(c.hd, 'grp', part + '_groups.png')))


# ---------------------------------------------------------------- parts
def parts_guide(c, part, gap=25):
    """房を、人（Claude）がデザインを見て決める方式。char.json の hair.<部分>.parts = [{"name": 名前, "poly": [[x, y], ...]}, ...]
    （poly は、デザインの絵の座標での、その房のおおよその範囲。房の内側に収まるように、小さめに取る）から、目印の絵を作る。
    大きな房（前髪 5・横髪 4・後ろ髪 8 くらい）は、輪郭線が閉じていないことが多く、自動の領域分け（split）では、細切れになるか、つながってしまう。
    どれが 1 つのパーツかは、役目で決まる（まん中の前髪、顔の横の房、…）ので、Live2D のモデラーと同じように、見て決める"""
    P = c.hair[part].get('parts')
    if not P:
        sys.exit('char.json の hair.%s.parts がありません' % part)
    D = np.asarray(Image.open(c.src('design_' + part)).convert('RGBA'))
    op = D[..., 3] > 128
    ms = []
    for e in P:
        m = np.zeros(op.shape, np.uint8)
        cv2.fillPoly(m, [np.array(e['poly'], np.int32)], 1)
        ms.append((m > 0) & op)
    gap = int(c.hair[part].get('parts_gap', 0.11) * op.shape[1]) | 1          # となりの房は、同じ絵に入れない（描き足した分が触れると、切り出せない）
    K = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gap, gap))
    dil = [cv2.dilate(m.astype(np.uint8), K) > 0 for m in ms]
    ids = list(range(len(P)))
    adj = {i: {j for j in ids if j != i and (dil[i] & dil[j]).any()} for i in ids}
    grp, size = {}, {}
    for i in sorted(ids, key=lambda i: -len(adj[i])):
        used = {grp[j] for j in adj[i] if j in grp}
        free = [g for g in size if g not in used]
        g = min(free, key=lambda g: size[g]) if free else len(size)
        grp[i] = g; size[g] = size.get(g, 0) + 1
    os.makedirs(os.path.join(c.hd, 'grp'), exist_ok=True)
    for f in glob.glob(os.path.join(c.hd, 'grp', part + '_g*.png')):
        os.remove(f)
    bg = np.asarray(on_gray(c.src('design_' + part))).astype(np.float32)
    tiles = []
    for g in sorted(size):
        img = bg.copy()
        for i in ids:
            if grp[i] == g:
                img[ms[i]] = img[ms[i]] * 0.35 + np.array([255, 0, 0], np.float32) * 0.65
        Image.fromarray(img.astype(np.uint8)).save(os.path.join(c.hd, 'grp', '%s_g%d.png' % (part, g)))
        tiles.append(cv2.resize(img.astype(np.uint8), (420, int(420 * img.shape[0] / img.shape[1]))))
    Image.fromarray(np.hstack(tiles)).save(os.path.join(c.hd, 'grp', part + '_groups.png'))
    json.dump({str(g): size[g] for g in sorted(size)}, open(os.path.join(c.hd, 'grp', part + '_groups.json'), 'w'))
    json.dump({'big': True, 'names': {str(g): [P[i]['name'] for i in ids if grp[i] == g] for g in sorted(size)}, 'notes': {str(g): ' '.join(P[i].get('note', '') for i in ids if grp[i] == g).strip() for g in sorted(size)}}, open(os.path.join(c.hd, 'grp', part + '_parts.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('%s: 房 %d 個を %d 組に分けた %s  一覧: %s' % (part, len(ids), len(size), [size[g] for g in sorted(size)], os.path.join(c.hd, 'grp', part + '_groups.png')))


# ---------------------------------------------------------------- draw / gaps
def inplace_jobs(c, part, prefix, guides, extra=''):
    hair = on_gray(c.src('design_' + part))
    jobs = []
    root = (ROOT_FULL if c.hair[part].get('parts_full') else ROOT_TEXT)[part]
    for g, (path, n) in guides.items():
        name = '%s_%s_%s' % (part, prefix, g)
        pr = tpl('hair_inplace.txt', OUT=name, KIND=c.hair[part]['kind'], NUM=n, ROOT=root + extra)
        jobs.append((name, pr, {'hair': hair, 'guide': Image.open(path).convert('RGB')}))
    return jobs


def draw(c, part):
    G = json.load(open(os.path.join(c.hd, 'grp', part + '_groups.json')))
    extra = ''
    if c.hair[part].get('parts'):
        extra = '\n- **今回の毛束は、大きな「房」です。** 幅の広い、1 枚の大きな形で、数は少なく、1 つ 1 つが髪型に欠かせないパーツです。赤い範囲は、房のまん中あたりを大まかに示しているだけです。その赤い所を含む房 1 つの全体を、hair.png の輪郭線のとおりに描いてください。房を、細い毛束に割らないでください（中の線は、hair.png にある線だけ）。となりの房の下に隠れていた所は、広めにたっぷり描き足します（動いたとき、切り口が見えないように）。房の毛先は、hair.png でその房が終わっている所（赤い範囲の下の端のあたり）までです。その下に続いて見える、別の房（赤くない房）のぎざぎざの毛先まで、つなげて描かないでください。同じ毛先が 2 つの房に入ると、重ねたとき二重に見えます。'
    if c.hair[part].get('parts') and c.hair[part].get('parts_full'):
        extra = FULL_TEXT
    notes = {}
    pj = os.path.join(c.hd, 'grp', part + '_parts.json')
    if c.hair[part].get('parts') and os.path.isfile(pj):
        notes = json.load(open(pj, encoding='utf-8')).get('notes', {})
    jobs = []
    for g, n in G.items():                      # 房ごとの注文（char.json の parts の note）は、その房の入っている絵の指示文にだけ足す
        ex = extra + ('\n- **この絵についての注文:** ' + notes[g] if notes.get(g) else '')
        jobs += inplace_jobs(c, part, 'in', {g: (os.path.join(c.hd, 'grp', '%s_g%s.png' % (part, g)), n)}, ex)
    if c.hair[part].get('cap'):
        jobs.append((part + '_cap', tpl('hair_cap.txt', OUT=part + '_cap'), {'hair': on_gray(c.src('design_' + part))}))
    run_jobs(c, jobs)


def gaps(c, part, amin=250, gmax=2):
    """デザインのうち、束がまだ無い所を、離れた組に分けて、そこに束を足して描かせる（下地があるので穴は開かないが、束の無い所は、毛先の動きが出ない）"""
    asm = os.path.join(c.hd, 'locks', '_locks_%s.png' % part)          # 束だけを重ねた絵（下地なし）
    if not os.path.isfile(asm):
        sys.exit('先に locks を実行してください')
    D = np.asarray(Image.open(c.src('design_' + part)).convert('RGBA')).astype(np.float32)
    A = np.asarray(Image.open(asm).convert('RGBA').resize((D.shape[1], D.shape[0]))).astype(np.float32)
    miss = cv2.morphologyEx(((D[..., 3] > 128) & (A[..., 3] <= 128)).astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(miss, connectivity=8)
    ids = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= amin]
    if not ids:
        print('すき間はありません'); return
    K = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 45))
    dil = {i: cv2.dilate((lab == i).astype(np.uint8), K) > 0 for i in ids}
    grp, size = {}, {}
    for i in sorted(ids, key=lambda i: -st[i, cv2.CC_STAT_AREA]):
        used = {grp[j] for j in grp if (dil[i] & dil[j]).any()}
        free = [g for g in size if g not in used]
        g = min(free, key=lambda g: size[g]) if free else len(size)
        if g < gmax:
            grp[i] = g; size[g] = size.get(g, 0) + 1
    k = 1 + max([int(os.path.basename(f).split('_gap')[1].split('_')[0]) for f in glob.glob(c.src(part + '_gap*'))] + [0])
    bg = np.asarray(on_gray(c.src('design_' + part))).astype(np.float32)
    guides = {}
    for g in sorted(size):
        mk = np.isin(lab, [i for i in grp if grp[i] == g])
        img = bg.copy(); img[mk] = img[mk] * 0.3 + np.array([255, 0, 0], np.float32) * 0.7
        p = os.path.join(c.hd, 'grp', '%s_gap%d_g%d.png' % (part, k, g))
        Image.fromarray(img.astype(np.uint8)).save(p); guides[str(g)] = (p, size[g])
    print('%s: すき間 %d か所（デザインの %.1f%%）を %d 枚で描かせる' % (part, len(grp), 100.0 * miss.sum() / (D[..., 3] > 128).sum(), len(guides)))
    run_jobs(c, inplace_jobs(c, part, 'gap%d' % k, guides, GAP_TEXT))


# ---------------------------------------------------------------- locks
def locks(c):
    h = c.hair
    cfg = {'out': 'locks', 'center_x': h['center_x'], 'head_r': h['head_r'], 'bangs_tip_y': h['bangs_tip_y'], 'parts': {}}
    if h.get('tone_ref'):
        cfg['tone_ref'] = os.path.join(c.work, h['tone_ref'] + '_3x.png')
    if h.get('tone_mask'):
        cfg['tone_mask'] = os.path.join(c.work, h['tone_mask'] + '_3x.png')
    for part in ('front', 'back'):
        if part not in h or not os.path.isfile(c.src('design_' + part)):
            continue
        srcs = sorted(glob.glob(c.src(part + '_in_*'))) + sorted(glob.glob(c.src(part + '_gap*')))
        pc = {'design': c.src('design_' + part), 'box': h[part]['box'], 'srcs': srcs}
        for k in ('whorl', 'base', 'base_cut', 'under', 'under_open', 'under_dark', 'widen', 'widen_side', 'adjust', 'close_gaps', 'top_cut', 'under_shrink', 'clump_close', 'fit_tip', 'fit_tip_min', 'lock_scale'):
            if k in h[part]:
                pc[k] = h[part][k]
        if h[part].get('parts'):
            pc['dedupe_contain'] = h[part].get('dedupe_contain', 0.7)
            if h[part].get('parts_full'):
                # 絵ごとの、その絵に描かせた房の目印（多角形）。つながって描かれた房を分ける・房ごとに位置を合わせる（hairlocks.py）のに使う
                pj = os.path.join(c.hd, 'grp', part + '_parts.json')
                names = json.load(open(pj, encoding='utf-8')).get('names', {}) if os.path.isfile(pj) else {}
                byname = {e['name']: e['poly'] for e in h[part]['parts']}
                pc['src_polys'] = {'%s_in_%s.png' % (part, g): [byname[n_] for n_ in ns if n_ in byname] for g, ns in names.items()}
        if h[part].get('cap') and os.path.isfile(c.src(part + '_cap')):
            pc['cap'] = c.src(part + '_cap')
        cfg['parts'][part] = pc
    p = os.path.join(c.hd, 'hairlocks.json')
    json.dump(cfg, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    rc = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'hairlocks.py'), p]).returncode
    if rc == 0 and h.get('clumps', True) is not False:
        # 毛束を「房」（前髪 5・横髪 4・後ろ髪 8 くらい）にまとめる。モデルには、房が入る（char.json の hair.clumps で、数と分け方を変えられる）
        if isinstance(h.get('clumps'), dict):
            cfg['clumps'] = h['clumps']
            json.dump(cfg, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        rc = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'hairclumps.py'), p]).returncode
    sys.exit(rc)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    c = Ctx(sys.argv[1]); st = sys.argv[2]; parts = sys.argv[3:] or [p for p in ('front', 'back') if p in c.hair]
    if st == 'locks':
        locks(c)
    for part in parts:
        {'key': key, 'design': design, 'map': hmap, 'split': split, 'parts': parts_guide, 'draw': draw, 'gaps': gaps}[st](c, part)
