# -*- coding: utf-8 -*-
"""parts_audit.py <モデルのフォルダ> <出力フォルダ>

モデルの各パーツを、単体で緑の背景に出す（小さいパーツは拡大する）。パーツの質を目で確かめるためのもの。
  <番号>_<名前>.png   パーツ単体（ふちがなめらかか、切れ端・半透明の抜けが無いかを見る）
  head_diff.png       頭の、なめらかな肌からの差を 6 倍に強調した絵（目・眉を消した跡は、等倍では見えない）
  face_parts.png      顔の小さなパーツ（目・眉・耳・鼻・口）を 1 枚に並べたもの
重ねた絵がきれいでも、単体が汚れていることがある。動かしたときに見えるのは単体の質。
"""
import json, io, sys, os, numpy as np
from PIL import Image, ImageFilter

for _f in (sys.stdout, sys.stderr):          # 出力は UTF-8（OS の文字コードのままだと、日本語の Windows 以外で、日本語の表示で止まる）
    try:
        _f.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

model, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
m = json.load(io.open(os.path.join(model, "model.json"), encoding="utf-8"))
ASCII = {"輪郭ベース": "head", "耳R": "earR", "耳L": "earL", "鼻": "nose", "下唇線": "mouth_line", "リップ": "lip", "白目R": "whiteR", "白目L": "whiteL",
         "瞳ベースR": "irisR", "瞳ベースL": "irisL", "下まつげR": "lash_lowerR", "下まつげL": "lash_lowerL", "アイライン線R": "lash_upperR", "アイライン線L": "lash_upperL",
         "眉毛R": "browR", "眉毛L": "browL", "首": "neck", "シャツ": "body", "前髪1": "bangs", "前髪2": "hair_base", "前髪6": "sideR", "前髪7": "sideL",
         "後ろ髪2": "back_hair", "後ろ髪1R": "tailR", "後ろ髪1L": "tailL", "帽子": "hat", "髪飾り": "ornament", "前髪1影": "bang_shadow",
         "帽子垂れR": "hat_drapeR", "帽子垂れL": "hat_drapeL", "髪飾りリボン": "orn_ribbon", "髪飾り鎖": "orn_chain", "アホ毛": "ahoge", "編み込み": "braid", "閉じ目R": "closedR", "閉じ目L": "closedL", "笑い目R": "smileR", "笑い目L": "smileL", "胸タイ": "chest_tie", "胸ブローチ": "chest_brooch", "髪飾り金具": "orn_charm", "胸リボン": "chest_ribbon", "胸パール": "chest_pearls", "胸の花": "chest_flower"}
small = {}
for l in m["layers"]:
    im = Image.open(os.path.join(model, "parts", l["src"])).convert("RGBA")
    if im.width < 8:
        continue
    z = max(1, min(6, 1400 // max(im.width, im.height)))
    bg = Image.new("RGBA", im.size, (0, 200, 0, 255)); bg.alpha_composite(im)
    bg = bg.convert("RGB").resize((im.width * z, im.height * z), Image.LANCZOS)
    if max(bg.size) > 1500:
        bg.thumbnail((1500, 1500), Image.LANCZOS)
    name = ASCII.get(l["name"], "diff%02d" % l["id"])
    # 毛束に分けた髪（前束NN・後束NN・後頭部・下地）
    if l["name"][:2] in ("前束", "後束"):
        name = ("lock_front" if l["name"][0] == "前" else "lock_back") + l["name"][2:]
    if l["name"][:2] in ("前房", "後房"):
        name = ("clump_front" if l["name"][0] == "前" else "clump_back") + l["name"][2:]
    name = {"後頭部": "back_cap", "前髪下地": "front_base", "後ろ髪下地": "back_under"}.get(l["name"], name)
    bg.save(os.path.join(out, "%02d_%s.png" % (l["id"], name)))
    a = np.asarray(im)[..., 3]
    print("%2d %-12s %-14s %4dx%-4d 半透明 %.1f%%" % (l["id"], name, l["path"].split("/")[-1], im.width, im.height, 100.0 * ((a > 8) & (a < 247)).sum() / max(1, (a > 8).sum())))
    if name in ("lash_upperR", "whiteR", "lash_lowerR", "irisR", "browR", "browL", "earR", "earL", "nose", "lip"):
        small[name] = bg
    if name == "head":
        arr = np.asarray(im).astype(np.float32); rgb, al = arr[..., :3], arr[..., 3] / 255
        sm = np.asarray(Image.fromarray(rgb.astype(np.uint8)).filter(ImageFilter.GaussianBlur(14))).astype(np.float32)
        d = np.clip(128 + (rgb - sm) * 6, 0, 255) * al[..., None] + np.array([0, 200, 0]) * (1 - al[..., None])
        Image.fromarray(d.astype(np.uint8)).save(os.path.join(out, "head_diff.png"))
if small:
    ims = [small[k] for k in ("lash_upperR", "whiteR", "lash_lowerR", "irisR", "browR", "browL", "nose", "lip", "earR", "earL") if k in small]
    ims = [i if i.height <= 520 else i.resize((i.width * 520 // i.height, 520), Image.LANCZOS) for i in ims]
    W = 1700; x = y = rowh = 0; pos = []
    for i in ims:
        if x + i.width > W and x > 0:
            x = 0; y += rowh + 8; rowh = 0
        pos.append((x, y)); x += i.width + 8; rowh = max(rowh, i.height)
    sheet = Image.new("RGB", (W, y + rowh), (255, 255, 255))
    for i, p in zip(ims, pos):
        sheet.paste(i, p)
    sheet.save(os.path.join(out, "face_parts.png"))
print("->", out)
