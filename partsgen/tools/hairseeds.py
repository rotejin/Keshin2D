# -*- coding: utf-8 -*-
"""hairseeds.py <キャラ名> <front|back> [--write] [出力.png]

髪の房の目印（char.json の hair.<部分>.parts の多角形）を、**房の中を通る「種の線」**から作る。

髪のデザインの絵（作業フォルダの hair/src/design_<部分>.png）が、細い毛筋を 1 本ずつ輪郭線で囲んだ絵のときは、房の境目を、
手で多角形に引くのが難しい（つむじから、弧を描いて下りる毛筋が、何十本もある。まっすぐな多角形では、毛筋の途中を横切る）。
ここでは、房ごとに、その房の中を通る折れ線（種）を書くだけで、髪の全体を「輪郭線を越えにくい広がり方」（watershed）で塗り分けて、
房ごとの範囲を多角形にする。境目は、デザインの輪郭線に沿う。どの房にも入らない髪は、残らない（毛先まで、いちばん近い房に入る）。

種は、char.json の hair.<部分>.seeds に書く（デザインの絵の画素。grid.py で、目盛りを付けた拡大図から読む）:
  "seeds": {
    "locks": [{"name": "前髪まん中", "lines": [[[x, y], [x, y], …], …], "note": "その房を描かせる絵にだけ足す注文（省略できる）"}, …],
    "exclude": [[[x, y], …], …],      どの房にも入れない所を通る折れ線（後頭部のドームなど。省略できる）
    "clip": [x0, y0, x1, y1],         この範囲の外は、どの房にも入れない（省略できる）
    "line_thr": 22                    輪郭線と見なす、まわりとの明るさの差（省略で 22。輪郭線の無い、なめらかな塗りの絵は 10）
  }
種の引き方:
  - **根元（つむじの近く）から毛先まで、毛筋に沿って引く。** 毛先の近くにだけ置くと、房が、毛筋の途中で、まっすぐ横に切れる。
  - 毛先が何本もある房は、毛先ごとに 1 本ずつ引く（引かなかった毛先は、となりの房へ入ることがある）。
  - 上の層の房の下から出ている毛束（根元が見えない房）は、見えている所だけに引く。
  - 種が、となりの房の中へ入らないように、太い輪郭線（房の境目）の内側を通す。

--write を付けたときだけ、char.json の hair.<部分>.parts を書き換える（付けなければ、確認の絵を出すだけ）。
確認の絵（省略すると 作業フォルダ/_obs/hairseeds_<部分>.png）: 房ごとに色を変え、種の線（黒）と、房の番号を重ねた絵。
見る所: 1 つの色が、根元から毛先まで、毛筋に沿って続いているか（途中で、まっすぐ切れていないか）。毛先が、となりの色に入っていないか。
このあと、haircover.py（覆えていない髪）→ hairdraw.py parts（組に分ける）へ進む。
"""
import sys, os, json
import numpy as np, cv2
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kenv

args = [a for a in sys.argv[1:] if a != "--write"]
write = "--write" in sys.argv
if len(args) < 2 or args[1] not in ("front", "back"):
    sys.exit(__doc__)
char, part = args[0], args[1]
work = kenv.char_work(char)
cj = os.path.join(HERE, "..", "chars", char, "char.json")
conf = json.load(open(cj, encoding="utf-8"))
S = conf["hair"][part].get("seeds")
if not S or not S.get("locks"):
    sys.exit("char.json の hair.%s.seeds.locks がありません（房ごとの、種の線を書きます）" % part)
outp = args[2] if len(args) > 2 else os.path.join(work, "_obs", "hairseeds_%s.png" % part)
D = np.asarray(Image.open(os.path.join(work, "hair", "src", "design_%s.png" % part)).convert("RGBA")).astype(np.float32)
op = D[..., 3] > 128
H, W = op.shape
lum = D[..., 0] * 0.3 + D[..., 1] * 0.59 + D[..., 2] * 0.11
# 輪郭線 = まわり（ぼかした明るさ）より、はっきり暗い所。影の面（なだらかな暗さ）は、線にしない
line = ((cv2.GaussianBlur(lum, (0, 0), 6) - lum) > float(S.get("line_thr", 22))) & op
line = cv2.morphologyEx(line.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
img = np.zeros((H, W, 3), np.uint8)
img[line] = 255
N = len(S["locks"])
BG, EX = N + 1, N + 2                       # 髪の外・どの房にも入れない所
LOCK_IDS = list(range(1, N + 1))
mk = np.zeros((H, W), np.int32)
mk[~cv2.dilate(op.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)] = BG
SW = int(S.get("seed_w", 5))
for i, e in enumerate(S["locks"]):
    for ln in e["lines"]:
        cv2.polylines(mk, [np.array(ln, np.int32)], False, i + 1, SW)
for ln in S.get("exclude", []):
    cv2.polylines(mk, [np.array(ln, np.int32)], False, EX, SW)
mk[~op & (mk != BG)] = 0
for i, e in enumerate(S["locks"]):
    if (mk == i + 1).sum() < 20:
        print("注意: %s の種が、髪の上に乗っていません（座標を確かめます）" % e["name"])
lab = cv2.watershed(img, mk.copy())
for _ in range(3):                           # 境目（-1）は、となりの房へ入れる（すき間を残さない）
    m = lab <= 0
    if not m.any():
        break
    lab[m] = cv2.dilate(np.where(lab > 0, lab, 0).astype(np.float32), np.ones((3, 3), np.uint8)).astype(np.int32)[m]
lab[~op] = BG
# 輪郭線で閉じた毛先に、外（背景）の塗りが入り込むことがある。髪の中で、どの房にも入らなかった所は、いちばん近い房へ入れる
need = op & ~np.isin(lab, LOCK_IDS + [EX])
if need.any():
    src = np.isin(lab, LOCK_IDS + [EX]) & op
    _, idx = cv2.distanceTransformWithLabels((~src).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.where(src)
    lut = np.zeros(int(idx.max()) + 1, np.int32)
    lut[idx[ys, xs]] = lab[ys, xs]
    lab[need] = lut[idx][need]
if S.get("clip"):
    cx0, cy0, cx1, cy1 = S["clip"]
    keep = np.zeros((H, W), bool); keep[cy0:cy1, cx0:cx1] = True
    lab[~keep & np.isin(lab, LOCK_IDS)] = EX
cols = [(255, 60, 60), (60, 200, 60), (255, 200, 0), (200, 60, 255), (0, 200, 255), (255, 120, 200), (120, 255, 120), (255, 255, 255), (255, 140, 0), (90, 90, 255), (160, 110, 60), (0, 140, 140)]
vis = D[..., :3] * 0.45 + 40
polys = []
for i, e in enumerate(S["locks"]):
    m = cv2.morphologyEx((lab == i + 1).astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, cl, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        print("注意: %s は、範囲が取れません（種を確かめます）" % e["name"]); polys.append(None); continue
    big = 1 + int(np.argmax(st[1:, 4]))
    lost = int(m.sum() - st[big, 4])
    m = cv2.dilate((cl == big).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    cnt = max(cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    ap = cv2.approxPolyDP(cnt, 1.5, True)[:, 0, :]
    polys.append([[int(x), int(y)] for x, y in ap])
    vis[m > 0] = vis[m > 0] * 0.45 + np.array(cols[i % len(cols)], np.float32) * 0.55
    print("%2d %s  面積 %d  頂点 %d%s" % (i, e["name"], int(st[big, 4]), len(ap), "  （離れた切れ端 %d 画素は、入れていない）" % lost if lost > 50 else ""))
vis[line] = vis[line] * 0.5
vis = np.ascontiguousarray(np.clip(vis, 0, 255).astype(np.uint8))
for i, e in enumerate(S["locks"]):
    for ln in e["lines"]:
        cv2.polylines(vis, [np.array(ln, np.int32)], False, (0, 0, 0), 2)
    if polys[i]:
        cv2.polylines(vis, [np.array(polys[i], np.int32)], True, (20, 20, 20), 1)
        ys, xs = np.nonzero(lab == i + 1)
        if len(xs):                              # 番号（日本語の名前は putText で描けないので、番号だけ）
            cv2.putText(vis, str(i), (int(xs.mean()) - 10, int(ys.mean())), 0, 1.1, (0, 0, 0), 5)
            cv2.putText(vis, str(i), (int(xs.mean()) - 10, int(ys.mean())), 0, 1.1, (255, 255, 255), 2)
for ln in S.get("exclude", []):
    cv2.polylines(vis, [np.array(ln, np.int32)], False, (255, 0, 255), 2)
un = op & ~np.isin(lab, LOCK_IDS)
print("どの房にも入らない髪 %.1f%%（exclude・clip で外した所。後頭部のドームなど）" % (100.0 * un.sum() / max(int(op.sum()), 1)))
os.makedirs(os.path.dirname(outp), exist_ok=True)
Image.fromarray(vis).save(outp)
print("確認の絵:", outp)
if write:
    parts = []
    for e, p in zip(S["locks"], polys):
        if p:
            d = {"name": e["name"], "poly": p}
            if e.get("note"):
                d["note"] = e["note"]
            parts.append(d)
    conf["hair"][part]["parts"] = parts
    json.dump(conf, open(cj, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
    print("char.json の hair.%s.parts に、房 %d 個を書きました" % (part, len(parts)))
