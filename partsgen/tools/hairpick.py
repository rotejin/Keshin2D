# -*- coding: utf-8 -*-
"""hairpick.py <キャラ名> --list <絵>
hairpick.py <キャラ名> <出来る絵> <もとの絵>[#塊の番号] [<もとの絵>[#塊の番号] …]

房を描かせた絵（作業フォルダの hair/src/ の下。<部分>_in_<番号>.png）から、**使う房（つながった塊）だけを選んで、1 枚の絵にまとめ直す**。

房を描かせると（`HD draw`）、目印（赤い範囲）より広く、となりの房の毛先まで描かれることがある。`HD locks` は、房を、描かせた絵の
「つながった塊」で切り出す（目印の多角形では切らない）ので、そのまま組むと、同じ毛先が 2 つの房に入り、揺れたとき二重に見える。
その絵だけ描き直すと、同じ絵に入っていた、うまく描けた房まで、描き変わる。ここでは、
  - 何回か描かせた絵の中から、房ごとに、いちばん良い塊を選ぶ
  - 房の分け方（目印）を変えたあと、もう描けている房を、新しい組（hair/grp/<部分>_parts.json）どおりの絵に並べ直す
ために、塊を、そのまま（位置も中身も変えずに）写す。房の中を、切ったり、塗ったり、つないだりは、しない（絵は、どれも同じキャンバス・同じ位置）。

  --list <絵>       その絵の塊を、左から 0, 1, 2 … と番号を付けて出す（面積 400 画素より小さい切れ端は、数えない）。
                    番号を重ねた確認の絵が、hair/_check/pick_<絵の名前>.png にできる
  <出来る絵>        hair/src/ の下の名前（拡張子なし。例 front_in_1）。もうあれば、前の絵を hair/_tries/ へ移す
  <もとの絵>        hair/src/ の下の名前（拡張子なし。フォルダを付けてよい。例 _v1/front_in_2）。#番号 を付けると、その塊だけ。付けなければ、塊の全部

使い方の例（描かせた絵を、先に hair/src/_v1/ へ写しておく）:
  hairpick.py chara7 --list _v1/front_in_2
  hairpick.py chara7 front_in_0 _v1/front_in_2#1 _v1/front_in_2#0
このあと `HD locks`。まとめ直した絵の、どの房が、どの絵のどの塊かは、キャラの NOTES.md に書いておく（作り直せるように）。
"""
import sys, os, shutil
import numpy as np, cv2
from PIL import Image, ImageDraw

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kenv

MIN_AREA = 400            # これより小さい切れ端は、房と数えない（hairlocks.py と同じ）


def comps(path):
    """(絵, 塊の番号の絵, 左から順に並べた塊の番号, 塊ごとの [x, y, 幅, 高さ, 面積])"""
    if not os.path.isfile(path):
        sys.exit("絵がありません: " + path)
    A = np.asarray(Image.open(path).convert("RGBA"))
    n, lab, st, cen = cv2.connectedComponentsWithStats((A[..., 3] > 128).astype(np.uint8), connectivity=8)
    ids = sorted([i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= MIN_AREA], key=lambda i: cen[i][0])
    return A, lab, ids, st


def main():
    a = sys.argv[1:]
    if len(a) < 3:
        sys.exit(__doc__)
    hd = os.path.join(kenv.char_work(a[0]), "hair")
    src = os.path.join(hd, "src")
    if a[1] == "--list":
        p = os.path.join(src, a[2] + ".png")
        A, lab, ids, st = comps(p)
        bg = Image.new("RGBA", (A.shape[1], A.shape[0]), (0, 200, 0, 255)); bg.alpha_composite(Image.fromarray(A))
        d = ImageDraw.Draw(bg)
        for k, i in enumerate(ids):
            x, y, w, h, area = [int(v) for v in st[i]]
            print("%d: 範囲 %d,%d-%d,%d  面積 %d" % (k, x, y, x + w, y + h, area))
            d.rectangle([x, y, x + w, y + h], outline=(255, 0, 0, 255), width=3)
            d.text((x + 6, y + 6), str(k), fill=(255, 255, 0, 255))
        os.makedirs(os.path.join(hd, "_check"), exist_ok=True)
        cp = os.path.join(hd, "_check", "pick_%s.png" % a[2].replace("/", "_").replace("\\", "_"))
        bg.convert("RGB").save(cp)
        print("確認の絵:", cp)
        return
    out, items = a[1], a[2:]
    res = None
    for it in items:
        nm, _, k = it.partition("#")
        A, lab, ids, st = comps(os.path.join(src, nm + ".png"))
        if k != "" and not (k.isdigit() and int(k) < len(ids)):
            sys.exit("%s に、塊 %s はありません（塊は 0〜%d。--list で確かめます）" % (nm, k, len(ids) - 1))
        for i in ([ids[int(k)]] if k != "" else ids):
            m = cv2.dilate((lab == i).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0     # ふちの半透明の画素まで
            m &= ~((lab > 0) & (lab != i))
            B = A.copy(); B[..., 3] = np.where(m, A[..., 3], 0)
            if res is None:
                res = B
                continue
            if res.shape != B.shape:
                sys.exit("絵の大きさが違います（同じキャンバスの絵だけを、まとめられます）: " + nm)
            if ((res[..., 3] > 128) & (B[..., 3] > 128)).any():
                print("注意: %s の塊が、先に入れた房と重なっています（同じ絵に、となり合う房は入れられません。組を確かめます）" % it)
            keep = B[..., 3] > res[..., 3]
            res[keep] = B[keep]
    dst = os.path.join(src, out + ".png")
    if os.path.isfile(dst):                                   # 前の絵を残す（hairdraw.py と同じ）
        os.makedirs(os.path.join(hd, "_tries"), exist_ok=True)
        shutil.move(dst, os.path.join(hd, "_tries", "%s_%d.png" % (os.path.basename(out), int(os.path.getmtime(dst)))))
    Image.fromarray(res).save(dst)
    n = cv2.connectedComponentsWithStats((res[..., 3] > 128).astype(np.uint8))[0] - 1
    print("%s  <- %s  塊 %d" % (dst, " ".join(items), n))


if __name__ == "__main__":
    main()
