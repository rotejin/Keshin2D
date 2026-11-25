# -*- coding: utf-8 -*-
"""refsheet.py <絵> <出力.png> <範囲>... [--height 画素] [--cols 数] [--bg R,G,B]
絵の中の小さな物（小物・瞳・口など）を、拡大して並べた「見本」を作る。描かせる絵に、もう 1 枚の見本として添える（char.json の job_inputs）。

  範囲: x0,y0,x1,y1[,角度]   その絵の画素。角度は、時計回りの度（頭をかしげた絵の小物を、まっすぐに起こすときに書く。省略で 0）
  --height  1 つを、この高さに そろえる（既定 560）
  --cols    1 段に並べる数（既定 3）。範囲が 1 つなら、その 1 つだけの絵になる（仕切りなし）
  --bg      透過の絵を重ねる背景色と、回したときに空く所の色（既定 255,255,255）

元の絵 1 枚を、そのまま渡すだけでは、小さな小物の形（ドット絵の輪郭、鎖の輪の数、模様）は、読み取られにくい。
拡大した見本を添えて、指示文に「左上から順に、何の見本か」を書く（WORKFLOW.md の段階 1）。
例: refsheet.py src.png items.png 1305,280,1465,424,21 1425,120,1665,550,21 1410,615,1630,895 1180,1495,1640,1705
"""
import sys
from PIL import Image

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def cut(im, box, deg, bg, k=4):
    x0, y0, x1, y1 = box
    cx, cy, hw, hh = (x0 + x1) / 2.0, (y0 + y1) / 2.0, (x1 - x0) / 2.0, (y1 - y0) / 2.0
    if not deg:
        c = Image.new("RGB", (int(x1 - x0), int(y1 - y0)), bg)
        c.paste(im, (-int(x0), -int(y0)))
        return c
    R = int((hw * hw + hh * hh) ** 0.5) + 4                      # 回しても、角が欠けない大きさで切ってから回す
    c = Image.new("RGB", (2 * R, 2 * R), bg)
    c.paste(im, (-int(cx - R), -int(cy - R)))
    c = c.resize((c.width * k, c.height * k), Image.LANCZOS).rotate(-deg, resample=Image.BICUBIC, fillcolor=bg)
    m = c.width // 2
    return c.crop((int(m - hw * k), int(m - hh * k), int(m + hw * k), int(m + hh * k)))


def main(argv):
    opt = {"--height": "560", "--cols": "3", "--bg": "255,255,255"}
    args = []
    i = 0
    while i < len(argv):
        if argv[i] in opt:
            opt[argv[i]] = argv[i + 1]; i += 2
        else:
            args.append(argv[i]); i += 1
    if len(args) < 3:
        sys.exit(__doc__)
    H, cols = int(opt["--height"]), int(opt["--cols"])
    bg = tuple(int(v) for v in opt["--bg"].split(","))
    src = Image.open(args[0]).convert("RGBA")
    base = Image.new("RGBA", src.size, bg + (255,)); base.alpha_composite(src)
    base = base.convert("RGB")
    tiles = []
    for a in args[2:]:
        v = [float(t) for t in a.split(",")]
        if len(v) not in (4, 5):
            sys.exit("範囲は x0,y0,x1,y1[,角度] と書きます: " + a)
        c = cut(base, v[:4], v[4] if len(v) == 5 else 0.0, bg)
        tiles.append(c.resize((max(1, int(round(c.width * H / float(c.height)))), H), Image.LANCZOS))
    if len(tiles) == 1:
        out = tiles[0]
    else:
        G = 24                                                    # 仕切り（灰色）
        rows = [tiles[j:j + cols] for j in range(0, len(tiles), cols)]
        w = max(sum(t.width for t in r) + G * (len(r) + 1) for r in rows)
        out = Image.new("RGB", (w, (H + G) * len(rows) + G), (120, 120, 120))
        y = G
        for r in rows:
            x = G
            for t in r:
                out.paste(t, (x, y)); x += t.width + G
            y += H + G
    out.save(args[1])
    print("%s 大きさ %s（%d 個）" % (args[1], out.size, len(tiles)))


if __name__ == "__main__":
    main(sys.argv[1:])
