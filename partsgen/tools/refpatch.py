# -*- coding: utf-8 -*-
"""refpatch.py <土台の絵> <もらう絵> <出力.png> <x0,y0,x1,y1> [ふちを ぼかす幅（既定 8）]
土台の絵の、その範囲だけを、もらう絵の同じ範囲に置き換えた「見本」を作る（2 枚は、同じ大きさ・同じ構図の絵）。

描かせ直すための見本を作る道具。**出来上がりの絵としては使わない**（継ぎはぎの跡が残る。見本として渡して、「そのまま写す。
はめ込みの跡だけ、まわりになじませる」と描かせる）。

使いどころ（WORKFLOW.md の段階 1）: ほぼ良い基準画像の、小さな 1 か所（髪飾りの形など）だけを、前に描かせた絵の形に戻したいとき。
「この見本の形にして」と、言葉と拡大の見本で頼むだけでは、今の絵の形が残って、戻らないことがある（もとの絵の中の形の方が、強く効く）。
見本そのものを直しておけば、「変えない」で通る。
"""
import sys
from PIL import Image, ImageFilter

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def main(argv):
    if len(argv) < 4:
        sys.exit(__doc__)
    a = Image.open(argv[0]).convert("RGBA")
    b = Image.open(argv[1]).convert("RGBA")
    if a.size != b.size:
        sys.exit("2 枚の大きさが違います: %s と %s" % (a.size, b.size))
    x0, y0, x1, y1 = [int(round(float(v))) for v in argv[3].split(",")]
    f = int(argv[4]) if len(argv) > 4 else 8
    m = Image.new("L", a.size, 0)
    m.paste(255, (x0 + f, y0 + f, x1 - f, y1 - f))
    if f > 0:
        m = m.filter(ImageFilter.GaussianBlur(f / 2.0))
    Image.composite(b, a, m).save(argv[2])
    print("%s（%s の %d,%d〜%d,%d を、%s から）" % (argv[2], argv[0], x0, y0, x1, y1, argv[1]))


if __name__ == "__main__":
    main(sys.argv[1:])
