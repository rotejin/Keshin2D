# -*- coding: utf-8 -*-
"""rootgrid.py <キャラ名> <番号> [--box x0,y0,x1,y1] [--edge top|bottom|left|right] [--poly "x,y;x,y;…"] [--scale 倍率] [--out 出力.png]

追加で描かせて置いた絵（char.json の extras.jobs.<番号>。頭に付いた耳など）の**付け根**を、もとの絵と比べる。
付け根を、もとの絵から描き足す指定（extras.jobs.<番号>.root。extras.py の冒頭の説明）の、多角形を決めるときに使う。

描かせた絵は、髪の下へもぐる付け根が、もとの絵より短く・細く描かれることがある。置いた確認の絵（_check/p_<番号>.png）は、
物の先・模様が合っていれば、合って見えるので、付け根は、ここで別に見る。

出すもの:
  1. 絵（既定 <作業フォルダ>/_check/root_<番号>.png）。座標は、3 倍の絵の画素。目盛りは 50 ごと（100 ごとに数字）
       上: もとの絵（背景は緑）に、置いた絵の外形（赤）と、覆いの絵の範囲（青の点。root.cover。無ければ 03_front_hair）を重ねた物
       下: 置いた絵だけ
     多角形（--poly か、char.json の root.poly）があれば、水色で描く
  2. 数字: 外形の、--edge の向きの端（top = 列ごとの上の端）を、もとの絵と置いた絵で比べた差。
     物の先の側は、差が 0 に近く、付け根の側へ行くほど差が開くなら、付け根が短い・細い。差が 3 画素以内になる所が、多角形の境目の目安

  --box   見る範囲（3 倍の絵の画素）。書かなければ、置いた絵の範囲の、まわり 60 画素
  --edge  比べる向き。頭の上の耳は top（上は背景なので、外形の上の端が、そのまま比べられる）。既定 top

使い方の例:
  rootgrid.py chara7 43 --box 1800,340,2800,900
  rootgrid.py chara7 43 --box 1800,340,2800,900 --poly "1894,551;1950,524;…"      # 多角形を重ねて確かめる
"""
import sys, os, json, argparse
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


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("char"); ap.add_argument("job")
    ap.add_argument("--box"); ap.add_argument("--edge", default="top", choices=["top", "bottom", "left", "right"])
    ap.add_argument("--poly"); ap.add_argument("--scale", type=float); ap.add_argument("--out")
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    o = ap.parse_args()
    cfg = os.path.join(HERE, "..", "chars", o.char, "char.json")
    if not os.path.isfile(cfg):
        sys.exit("char.json がありません: " + os.path.abspath(cfg))
    job = ((json.load(open(cfg, encoding="utf-8")).get("extras") or {}).get("jobs") or {}).get(o.job)
    if not job:
        sys.exit("char.json の extras.jobs に、その番号がありません: " + o.job)
    work = kenv.char_work(o.char)
    root = job.get("root") or {}
    bp = os.path.join(work, ((job.get("ref") or {}).get("from") or "00_base") + "_3x.png")
    pp = os.path.join(work, job["out"] + "_placed.png")
    for p in (bp, pp):
        if not os.path.isfile(p):
            sys.exit("絵がありません（先に PY place を）: " + p)
    base = Image.open(bp).convert("RGBA"); part = Image.open(pp).convert("RGBA")
    if base.size != part.size:
        sys.exit("もとの絵と、置いた絵の大きさが違います: %s %s" % (base.size, part.size))
    PA = np.asarray(part)[..., 3] > 128; BA = np.asarray(base)[..., 3] > 128
    if o.box:
        box = [int(float(v)) for v in o.box.split(",")]
    else:
        ys, xs = np.where(PA)
        box = [int(max(0, xs.min() - 60)), int(max(0, ys.min() - 60)), int(min(base.width, xs.max() + 61)), int(min(base.height, ys.max() + 61))]
    x0, y0, x1, y1 = box
    poly = None
    if o.poly:
        poly = [tuple(float(t) for t in p.split(",")) for p in o.poly.split(";") if p]
    elif root.get("poly"):
        poly = [tuple(p) for p in root["poly"]]
    cov = np.zeros(PA.shape, bool)
    for c in (root.get("cover") or ["03_front_hair"]):
        cp = os.path.join(work, c + "_3x.png")
        if os.path.isfile(cp):
            cov |= np.asarray(Image.open(cp).convert("RGBA"))[..., 3] > 128
    S = o.scale or min(2.5, max(0.5, 1400.0 / max(1, x1 - x0)))

    def panel(im, marks):
        bg = Image.new("RGBA", im.size, (60, 170, 60, 255)); bg.alpha_composite(im)
        A = np.asarray(bg.convert("RGB").crop(box)).copy()
        if marks:
            pa = PA[y0:y1, x0:x1]
            A[(cv2.dilate(pa.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & ~pa] = (255, 0, 0)
            yy, xx = np.mgrid[0:A.shape[0], 0:A.shape[1]]
            A[cov[y0:y1, x0:x1] & (xx % 8 == 0) & (yy % 8 == 0)] = (60, 120, 255)
        im2 = Image.fromarray(A).resize((int(A.shape[1] * S), int(A.shape[0] * S)), Image.LANCZOS)
        d = ImageDraw.Draw(im2)
        for x in range((x0 // 50 + 1) * 50, x1, 50):
            d.line([((x - x0) * S, 0), ((x - x0) * S, im2.height)], fill=(255, 255, 0) if x % 100 == 0 else (120, 120, 0), width=1)
            if x % 100 == 0:
                d.text(((x - x0) * S + 3, 3), str(x), fill=(255, 255, 0))
        for y in range((y0 // 50 + 1) * 50, y1, 50):
            d.line([(0, (y - y0) * S), (im2.width, (y - y0) * S)], fill=(255, 255, 0) if y % 100 == 0 else (120, 120, 0), width=1)
            if y % 100 == 0:
                d.text((3, (y - y0) * S + 3), str(y), fill=(255, 255, 0))
        if poly:
            d.line([((x - x0) * S, (y - y0) * S) for x, y in poly + poly[:1]], fill=(0, 255, 255), width=2)
        return im2

    a, b = panel(base, True), panel(part, False)
    sheet = Image.new("RGB", (a.width, a.height * 2 + 6), (0, 0, 0)); sheet.paste(a, (0, 0)); sheet.paste(b, (0, a.height + 6))
    out = o.out or os.path.join(work, "_check", "root_%s.png" % o.job)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out)
    # 外形の端の差（もとの絵 − 置いた絵。＋は、置いた絵の方が、内側 = 短い・細い）
    col = o.edge in ("top", "bottom")
    lo, hi = (x0, x1) if col else (y0, y1)
    step = max(20, (hi - lo) // 24 // 10 * 10)
    name = {"top": "上の端", "bottom": "下の端", "left": "左の端", "right": "右の端"}[o.edge]
    print("外形の%s（%s ごと。もとの絵 / 置いた絵 / 差。差が＋なら、置いた絵の方が内側）:" % (name, "列" if col else "行"))
    for t in range((lo // step + 1) * step, hi, step):
        vb = np.where(BA[y0:y1, t] if col else BA[t, x0:x1])[0]; vp = np.where(PA[y0:y1, t] if col else PA[t, x0:x1])[0]
        if not len(vb) or not len(vp):
            continue
        off = y0 if col else x0
        eb, ep = ((vb.min(), vp.min()) if o.edge in ("top", "left") else (vb.max(), vp.max()))
        d = (ep - eb) if o.edge in ("top", "left") else (eb - ep)
        print("  %s %5d   %5d / %5d   差 %+d" % ("x" if col else "y", t, eb + off, ep + off, d))
    print("絵:", out, sheet.size, " 範囲", box, " 倍率 %.2f" % S)


if __name__ == "__main__":
    main()
