# -*- coding: utf-8 -*-
"""元の絵・基準画像（00_base）・出来たモデルの顔を、同じ大きさで横に並べる（「元の絵に似ているか」を見るため）。

  fidelity.py <作業フォルダ> <char.json> [モデル名 | key]

出力: <作業フォルダ>/_check/fidelity.png
  上段: 頭の全体（元の絵 | 00_base | モデルの正面）。key と書いたときは、モデルの代わりに、髪のキービジュアルの案（hair/src/key_*.png）
  下段: 目・鼻・口のあたりの拡大

char.json の項目（どちらも無くても動くが、新しいキャラでは、段階 1 で 2 つとも書く。縦横の比をそろえると、同じ大きさで並ぶ）:
  "src_face_box":  [x0, y0, x1, y1]   元の絵（src.png）の中の、頭（髪・髪飾りを含む）の範囲。
                                      元の絵が設定画（全身や後ろ姿が並んだ絵）のときは、顔アップの範囲を書く。無ければ絵の全体
                                      （そのときは、元の絵の「目鼻口の拡大」は出ない）
  "base_face_box": [x0, y0, x1, y1]   00_base（1024×1536）の中の、頭の範囲。無ければ、build.seed_head と hair.head_r から、
                                      それも無ければ、絵の上半分から決める（ひな形の seed_head・head_r は、手本のキャラの値なので、
                                      段階 1 の時点では、頭が切れる）
範囲が書かれていないときは、その旨を出す（絵は、今までどおりに作る）。

「崩れていないか」の点検（audit・shots）は、元の絵と違っていても通ってしまう。この絵を見て、下の項目を 1 つずつ言葉で答える。
"""
import sys, os, json, subprocess, shutil
sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CELL = 900
CHECKLIST = [
    "鼻: 形・大きさ・色（元に無い白い点や影が付いていないか）",
    "髪の色: 明るさと色合い（黒が茶色になっていないか、など）。ハイライトの色",
    "前髪の形: 毛先のそろい方（ぱっつん／とがった房）、すき間、分け目の位置",
    "横髪・後ろ髪の長さと外形。結んだ髪・アホ毛・おくれ毛",
    "瞳: 色、濃淡の向き、瞳孔と光の形、描き込みの量",
    "まつげ・二重・眉: 太さ、色、はねの向き",
    "顔の輪郭と、目・鼻・口の位置の比率（目の大きさ、目と目の間、あごの長さ）",
    "肌の色、頬の赤み、ほくろ等の印の位置（左右を取り違えていないか）",
    "髪飾りの形・色・位置",
    "服の色と模様（えり、リボン、編み目など）",
]


def font(size):
    for p in (r"C:\Windows\Fonts\meiryo.ttc", r"C:\Windows\Fonts\YuGothM.ttc", r"C:\Windows\Fonts\msgothic.ttc"):
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def on_white(im):
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, im).convert("RGB")


def crop_box(im, box):
    """絵の外へ出る範囲は白で埋めて切り出す。"""
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    out = Image.new("RGB", (x1 - x0, y1 - y0), (255, 255, 255))
    out.paste(im, (-x0, -y0))
    return out


def fit(im, cell=CELL):
    """縦横比を保って、cell×cell の白いコマに収める。"""
    s = min(cell / im.width, cell / im.height)
    r = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    out = Image.new("RGB", (cell, cell), (255, 255, 255))
    out.paste(r, ((cell - r.width) // 2, (cell - r.height) // 2))
    return out


def face_zoom(head):
    """頭の切り出しから、目・鼻・口のあたり（横 18〜82%、縦 42〜88%）を取り出す。"""
    w, h = head.size
    return head.crop((round(w * 0.18), round(h * 0.42), round(w * 0.82), round(h * 0.88)))


def main():
    work, cfgp = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else ""
    conf = json.load(open(cfgp, encoding="utf-8")) if os.path.isfile(cfgp) else {}
    panels = []

    srcp = os.path.join(work, "src.png")
    if not os.path.isfile(srcp):
        sys.exit("元の絵がありません: " + srcp)
    src = on_white(Image.open(srcp))
    notes = []                                  # 頭の範囲が書かれていないときの注意（絵は、今までどおりに作る）
    if conf.get("src_face_box"):
        panels.append(("元の絵", crop_box(src, conf["src_face_box"])))
    else:
        panels.append(("元の絵（全体。char.json に src_face_box を書くと頭だけになる）", src))
        notes.append("char.json に src_face_box がありません。元の絵は全体のまま並べ、目鼻口の拡大は出しません"
                     "（src.png の中の、頭 = 髪・髪飾りまで入る範囲を [x0, y0, x1, y1] で書く）")

    basep = os.path.join(work, "00_base.png")
    if os.path.isfile(basep):
        base = on_white(Image.open(basep))
        bb = conf.get("base_face_box")
        if not bb:
            seed = (conf.get("build") or {}).get("seed_head"); r = (conf.get("hair") or {}).get("head_r")
            if seed and r:                      # どちらも 3 倍の絵での値
                cx, cy, r = seed[0] / 3.0, seed[1] / 3.0, r / 3.0
                bb = [cx - 1.75 * r, cy - 1.5 * r, cx + 1.75 * r, cy + 2.1 * r]
                notes.append("char.json に base_face_box がありません。00_base の頭は、build.seed_head と hair.head_r から決めた範囲で切り出しました"
                             "（ひな形のままなら、手本のキャラの値です。頭が切れていたら、00_base.png の中の頭の範囲を base_face_box に書く）")
            else:
                bb = [base.width * 0.15, 0, base.width * 0.85, base.width * 0.70]
                notes.append("char.json に base_face_box がありません。00_base の頭は、絵の上のほうを切り出しました（頭が切れていたら、base_face_box を書く）")
        panels.append(("基準画像 00_base", crop_box(base, bb)))

    if model == "key":
        # 髪のキービジュアルの案（HD key が hair/src/key_*.png に描く。00_base の頭のまわりを切り出した範囲の絵）
        import glob
        for kp in sorted(glob.glob(os.path.join(work, "hair", "src", "key_*.png"))):
            panels.append(("髪のキービジュアル " + os.path.basename(kp)[:-4], on_white(Image.open(kp))))
        if len(panels) < 3:
            print("キービジュアルの案がありません（HD key を先に走らせる）")
    elif model and os.path.isfile(os.path.join(HERE, "..", "..", "models", model, "model.json")):
        tmp = os.path.join(work, "_check", "_fid")
        pose = "front=hair=1&yaw=0&zoom=1.3&cx=1500&cy=640&sim=4"
        rc = subprocess.run([sys.executable, "-I", os.path.join(HERE, "regress.py"), "shoot", model, tmp, "--poses", pose, "--size", "1100"],
                            capture_output=True).returncode
        shot = os.path.join(tmp, "front.png")
        if rc == 0 and os.path.isfile(shot):
            panels.append(("モデル（正面）", Image.open(shot).convert("RGB").copy()))
        else:
            print("モデルの撮影に失敗しました（元の絵と 00_base だけ並べます）")
        shutil.rmtree(tmp, ignore_errors=True)

    n = len(panels); pad = 46; f = font(26)
    S = Image.new("RGB", (n * CELL + (n + 1) * 12, 2 * (CELL + pad) + 12), (255, 255, 255)); dr = ImageDraw.Draw(S)
    for i, (label, im) in enumerate(panels):
        x = 12 + i * (CELL + 12)
        dr.text((x + 4, 6), label, fill=(0, 0, 0), font=f)
        S.paste(fit(im), (x, pad))
        if i == 0 and not conf.get("src_face_box"):
            continue                                        # 元の絵の全体しか無いときは、拡大は出さない
        dr.text((x + 4, pad + CELL + 6), label + " ・目鼻口の拡大", fill=(0, 0, 0), font=f)
        S.paste(fit(face_zoom(im)), (x, 2 * pad + CELL))
    os.makedirs(os.path.join(work, "_check"), exist_ok=True)
    outp = os.path.join(work, "_check", "fidelity.png")
    S.save(outp)
    print(outp, S.size)
    for t in notes:
        print("注意: " + t)
    print("この絵を見て、元の絵との違いを、次の項目ごとに言葉で答える（「同じ」「違う: どこがどう違うか」）。違いは、直すか、ユーザーに見せて判断してもらう:")
    for i, c in enumerate(CHECKLIST, 1):
        print("  %2d. %s" % (i, c))


if __name__ == "__main__":
    main()
