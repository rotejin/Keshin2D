# -*- coding: utf-8 -*-
"""キャラクター画像 1 枚から、動かせるモデルを作るまでの各段階を実行する。

  pipeline.py check                        キャラを作るのに要るもの（Python のライブラリ・Node.js・Chrome・Codex CLI・Real-ESRGAN）がそろっているか
  pipeline.py install-upscaler             拡大に使う Real-ESRGAN を、配布元から取ってきて置く（1 回だけ。約 50MB。upscale.py --install）
  pipeline.py draw    <キャラ名> <番号>...     Codex CLI に絵を描かせる（複数指定すると同時に走らせる）
  pipeline.py upscale <キャラ名>               作業フォルダの絵を 3 倍に拡大する（Real-ESRGAN）
  pipeline.py place   <キャラ名> [番号...]     追加で描かせた絵（揺れ物など。char.json の extras）を、もとの絵の中の位置へ置く
  pipeline.py face    <キャラ名>               髪なしの絵から、顔・目・耳を切り出す
  pipeline.py model   <キャラ名> [モデル名]    モデルを書き出す。成功したときだけ models/<モデル名> を差し替える
  pipeline.py shots   <キャラ名> [モデル名]    決まった姿勢を一括で撮る（regress.py shoot）
  pipeline.py audit   <キャラ名> [モデル名]    各パーツを単体で緑の背景に出す（parts_audit.py）。作業フォルダの _audit/
  pipeline.py fidelity <キャラ名> [モデル名]   元の絵・00_base・モデルの顔を同じ大きさで並べる（fidelity.py）。作業フォルダの _check/fidelity.png
  pipeline.py status  <キャラ名>               作業フォルダに、どの絵があるかを出す

キャラごとのものは partsgen/chars/<キャラ名>/ に置く:
  char.json   色の条件、目の箱と折れ線、上限などの初期値
  prompts/    Codex への指示文（prompt_<番号>.txt）。無い番号は tools/codex/ の共通の指示文を使う
              （20〜36 は prompt_<番号>.txt、キーの形のシート 61〜68 は key_eye1・key_eye2・sheet_mouth・key_mouth2）。
              指示文の中の {OUT} は、その絵の出力の名前（例 65_key_eye1b）に置き換えて渡す

作業フォルダは、既定で %LOCALAPPDATA%\\keshin2d_work\\<キャラ名>（Windows 以外は ~/keshin2d_work/<キャラ名>）。
OpenCV と Real-ESRGAN は日本語のパスを読めないので、英数字だけのパスにする。既定の場所に日本語などが入るとき
（Windows のユーザー名が日本語、など）は、道具が、英数字だけの別の場所を選ぶ（決め方は kenv.py。check が場所を出す）。
置き場所ごと変えるのは、環境変数 KESHIN2D_WORK（どの道具にも効く）。--work は、この道具だけ、キャラ 1 体のフォルダを変える。
"""
import sys, os, json, glob, shutil, subprocess, threading, time, argparse

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PARTSGEN = os.path.dirname(HERE)
ROOT = os.path.dirname(PARTSGEN)            # Keshin2D
PY = [sys.executable, "-I"]
sys.path.insert(0, HERE)
import kenv

# 番号 -> (出力の名前, 入力 {指示文の中での名前: 作業フォルダの絵})
JOBS = {
    "00": ("00_base", {"src": "src"}),
    "01": ("01_base_nohair", {"base": "00_base"}),
    "03": ("03_front_hair", {"base": "00_base", "nohair": "01_base_nohair"}),
    "03b": ("03b_front_hair_only", {"front": "03_front_hair"}),
    "04": ("04_back_hair", {"base": "00_base", "nohair": "01_base_nohair"}),
    "05": ("05_twintails", {"base": "00_base", "nohair": "01_base_nohair"}),
    "09": ("09_bangs_only", {"hair": "03b_front_hair_only"}),
    "10": ("10_side_hair_only", {"hair": "03b_front_hair_only"}),
    "11": ("11_neck_down", {"nohair": "01_base_nohair"}),
    "12": ("12_hat", {"base": "00_base", "nohair": "01_base_nohair"}),
    "13": ("13_ornament", {"base": "00_base", "nohair": "01_base_nohair"}),
    "20": ("20_tears", {"nohair": "01_base_nohair"}),
    "21": ("21_sweat", {"nohair": "01_base_nohair"}),
    "22": ("22_iris_heart", {"eye": "_eye_ref"}),
    "23": ("23_iris_star", {"eye": "_eye_ref"}),
    "24": ("24_iris_swirl", {"eye": "_eye_ref"}),
    "25": ("25_iris_dark", {"eye": "_eye_ref"}),
    "26": ("26_tears_eye", {"eye": "_eyec_ref"}),
    "32": ("32_eye_closed", {"eye": "_eyec_ref"}),
    "34": ("34_eye_smile", {"eye": "_eyec_ref"}),
    "30": ("30_iris_base", {"eye": "_eye_ref"}),
    "31": ("31_eye_frame", {"eye": "_eye_ref"}),
    "33": ("33_brow", {"brow": "_brow_ref"}),
    "35": ("35_ear", {"ear": "_ear_ref"}),
    "36": ("36_head", {"head": "_head_ref"}),
}
SQUARE = {"22", "23", "24", "25", "26", "30", "31", "32", "33", "34", "35", "36"}           # 位置合わせをしない絵（拡大もしない）
# build2.py へ環境変数で渡す絵
MODEL_ENV = {"FRONT_ONLY": "03b_front_hair_only", "BANGS_ONLY": "09_bangs_only", "SIDE_ONLY": "10_side_hair_only",
             "NECKDOWN": "11_neck_down", "HAT": "12_hat", "ORNAMENT": "13_ornament", "TEARS": "20_tears", "SWEAT": "21_sweat"}
MODEL_ENV_RAW = {"HEAD": "36_head", "BROW": "33_brow", "EAR": "35_ear", "IRIS_BASE": "30_iris_base", "EYE_FRAME": "31_eye_frame", "IRIS_HEART": "22_iris_heart", "IRIS_STAR": "23_iris_star", "IRIS_SWIRL": "24_iris_swirl", "IRIS_DARK": "25_iris_dark",
                 "EYE_CLOSED": "32_eye_closed", "EYE_SMILE": "34_eye_smile", "TEARS_EYE": "26_tears_eye"}
# キーの形のシート（段階 5c）の、共通の指示文。chars/<キャラ名>/prompts/prompt_<番号>.txt が無ければ、これを使う
# （61〜64 と、2 つ目の案 65〜68 は、同じ指示文。保存する名前は、指示文の中の {OUT} を置き換えて渡す）
KEY_PROMPTS = {"61": "key_eye1.txt", "65": "key_eye1.txt", "63": "key_eye2.txt", "67": "key_eye2.txt",
               "62": "sheet_mouth.txt", "66": "sheet_mouth.txt", "64": "key_mouth2.txt", "68": "key_mouth2.txt"}


def prompt_path(o, n):
    """その番号の指示文（無ければ None）。キャラ用 → 共通の prompt_<番号>.txt → キーの形のシートの共通の指示文、の順"""
    cands = [os.path.join(o.chardir, "prompts", "prompt_%s.txt" % n), os.path.join(HERE, "codex", "prompt_%s.txt" % n)]
    if n in KEY_PROMPTS:
        cands.append(os.path.join(HERE, "codex", KEY_PROMPTS[n]))
    return next((p for p in cands if os.path.isfile(p)), None)


def setup(o):
    o.chardir = os.path.join(PARTSGEN, "chars", o.char)
    o.cfg = os.path.join(o.chardir, "char.json")
    if o.work:
        o.work = os.path.abspath(o.work)
        if not kenv.is_ascii(o.work):
            sys.exit("作業フォルダのパスに日本語などが入っています。--work には、英数字だけのパスを指定してください: " + o.work)
    else:
        o.work = kenv.char_work(o.char)
    os.makedirs(o.work, exist_ok=True)
    o.conf = json.load(open(o.cfg, encoding="utf-8")) if os.path.isfile(o.cfg) else {}
    # キャラごとの追加の絵（揺れ物など）。char.json の extras.jobs = {番号: {"out": 名前, "ref": {"name": 指示文の中での名前, "from": もとの絵, "box": 3 倍の絵での範囲（省略で絵の全体）, "pad": 余白の割合, "long": 見本の長辺}}}
    # 見本（もとの絵の、その部分の拡大）を渡して大きく清書させ、place の段階で、見本との対応から元の位置へ置く
    o.extra = (o.conf.get("extras") or {}).get("jobs") or {}
    for n, j in o.extra.items():
        if j.get("mirror"):
            continue                                                         # 描かせない（別の絵を左右に返して使う）
        JOBS[n] = (j["out"], {j["ref"]["name"]: "_ref_" + n})
        SQUARE.add(n)
    # 決まった番号の絵に、渡す絵を足す・替える。char.json の "job_inputs": {"00": {"src": "src", "front": "front"}}
    # （指示文の中での名前: 作業フォルダの絵）。承認済みの基準画像を見本に、塗りだけ描き直させるときなどに使う
    for n, ins in (o.conf.get("job_inputs") or {}).items():
        if n in JOBS:
            JOBS[n] = (JOBS[n][0], dict(ins))
    os.environ["CHARCFG"] = o.cfg if os.path.isfile(o.cfg) else ""
    if not os.environ["CHARCFG"]:
        del os.environ["CHARCFG"]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------- draw
def codex_exe():
    exe = kenv.codex_exe()                           # 探し方は kenv.py（hairdraw.py と同じ）
    if not exe:
        sys.exit("Codex CLI が見つかりません。環境変数 CODEX_EXE に codex の実行ファイルを指定してください。")
    return exe


def eye_ref(o):
    """瞳の差分を描かせるときの見本: 髪なしの絵の片目を大きく切り出す（char.json の eyeL.box は 3 倍の絵での座標）"""
    from PIL import Image
    dst = os.path.join(o.work, "_eye_ref.png")
    box = (o.conf.get("eyeL") or {}).get("box")
    if not box:
        sys.exit("char.json に eyeL.box がありません（瞳の差分は、目の箱を決めた後に描かせます）")
    big = os.path.join(o.work, "01_base_nohair_3x.png")
    if os.path.isfile(big):
        im = Image.open(big).convert("RGB").crop(tuple(box))
    else:
        im = Image.open(os.path.join(o.work, "01_base_nohair.png")).convert("RGB")
        im = im.crop(tuple(int(round(v / 3)) for v in box)).resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
    s = 1040.0 / im.width
    im.resize((1040, int(round(im.height * s))), Image.LANCZOS).save(dst)


def eyec_ref(o):
    """閉じた目・片目の涙・目のキーの形のシートを描かせるときの見本: 髪なしの絵の、画面左の目のまわりを、横 3:縦 2 で切り出して 1536×1024 にする
    （大きさは char.json の eyec_ref_scale = 目の箱の幅の何倍か。既定 1.25。位置は eyec_ref_shift = [dx, dy]。既定は、瞳の中心がまん中）。
    描かせる絵は、この見本と同じキャンバス・同じ位置に描かせる。切り出した範囲は _eyec_ref.json に残し、build2.py が、
    その範囲へ縮めて置く（画面右の目へは、左右を返して置く）。位置を合わせて小さく描かせるより、ずれが小さい"""
    from PIL import Image
    box = (o.conf.get("eyeL") or {}).get("box")
    man = os.path.join(o.work, "face", "manifest.json")
    if not box or not os.path.isfile(man):
        sys.exit("目の箱（char.json の eyeL.box）と face/manifest.json が要ります（PY face の後に描かせます）")
    e = json.load(open(man, encoding="utf-8"))["notes"]["eye_L"]
    cx, cy = e["box"][0] + e["iris_circle_in_box"][0], e["box"][1] + e["iris_circle_in_box"][1]
    w = int(round((box[2] - box[0]) * float(o.conf.get("eyec_ref_scale", 1.25)) / 6)) * 6          # 3:2 にしやすい幅
    h = w * 2 // 3
    # 範囲のまん中は、瞳の中心。目尻のはねが長い絵柄では、目の全体が、瞳より目尻の側へ寄るので、範囲に、もう片方の目の目頭が入る。
    # char.json の eyec_ref_shift [dx, dy]（3 倍の絵の画素。書かなければ [0, 0]）で、範囲をずらす（目尻の側へは、dx を負に）
    sx, sy = [int(round(float(v))) for v in (o.conf.get("eyec_ref_shift") or [0, 0])]
    crop = [int(round(cx - w / 2)) + sx, int(round(cy - h / 2)) + sy, int(round(cx - w / 2)) + sx + w, int(round(cy - h / 2)) + sy + h]
    im = Image.open(os.path.join(o.work, "01_base_nohair_3x.png")).convert("RGBA").crop(tuple(crop))
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im)
    bg.convert("RGB").resize((1536, 1024), Image.LANCZOS).save(os.path.join(o.work, "_eyec_ref.png"))
    json.dump({"box": crop, "center": [cx, cy]}, open(os.path.join(o.work, "_eyec_ref.json"), "w"))


def brow_ref(o):
    """眉を清書させるときの見本: 髪なしの絵の、画面左の眉を大きく切り出す（char.json の build.brow_L は 3 倍の絵での座標）"""
    from PIL import Image
    box = (o.conf.get("build") or {}).get("brow_L")
    if not box:
        sys.exit("char.json に build.brow_L がありません（眉は、眉の箱を決めた後に描かせます）")
    mx, my = int((box[2] - box[0]) * 0.12), int((box[3] - box[1]) * 0.6)
    box = [box[0] - mx, box[1] - my, box[2] + mx, box[3] + my]
    big = os.path.join(o.work, "01_base_nohair_3x.png")
    if os.path.isfile(big):
        im = Image.open(big).convert("RGB").crop(tuple(box))
    else:
        im = Image.open(os.path.join(o.work, "01_base_nohair.png")).convert("RGB")
        im = im.crop(tuple(int(round(v / 3)) for v in box)).resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
    s = 1040.0 / im.width
    im.resize((1040, int(round(im.height * s))), Image.LANCZOS).save(os.path.join(o.work, "_brow_ref.png"))


def ear_ref(o):
    """耳を清書させるときの見本: 髪なしの絵の、画面左の耳を大きく切り出す（範囲は、切り出し済みの face/11_ears.png から取る）"""
    import numpy as np
    from PIL import Image
    p = os.path.join(o.work, "face", "11_ears.png")
    if not os.path.isfile(p):
        sys.exit("face/11_ears.png がありません（耳は、face の段階の後に描かせます）")
    a = np.asarray(Image.open(p).convert("RGBA"))[..., 3] > 127
    a[:, a.shape[1] // 2:] = False
    ys, xs = np.where(a)
    w, h = xs.max() - xs.min(), ys.max() - ys.min()
    box = (int(xs.min() - 0.25 * w), int(ys.min() - 0.15 * h), int(xs.max() + 0.6 * w), int(ys.max() + 0.15 * h))
    im = Image.open(os.path.join(o.work, "01_base_nohair_3x.png")).convert("RGB").crop(box)
    s = 1000.0 / im.height
    im.resize((int(round(im.width * s)), 1000), Image.LANCZOS).save(os.path.join(o.work, "_ear_ref.png"))


def head_ref(o):
    """頭を清書させるときの見本: 髪なしの絵の頭を大きく切り出す（範囲は、切り出し済みの face/10_head.png から取る）"""
    import numpy as np
    from PIL import Image
    p = os.path.join(o.work, "face", "10_head.png")
    if not os.path.isfile(p):
        sys.exit("face/10_head.png がありません（頭は、face の段階の後に描かせます）")
    a = np.asarray(Image.open(p).convert("RGBA"))[..., 3] > 127
    ys, xs = np.where(a)
    w, h = xs.max() - xs.min(), ys.max() - ys.min()
    box = (int(xs.min() - 0.22 * w), int(ys.min() - 0.06 * h), int(xs.max() + 0.22 * w), int(ys.max() + 0.12 * h))
    im = Image.open(os.path.join(o.work, "01_base_nohair_3x.png")).convert("RGBA").crop(box)
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im)
    s = 1400.0 / im.height
    bg.convert("RGB").resize((int(round(im.width * s)), 1400), Image.LANCZOS).save(os.path.join(o.work, "_head_ref.png"))


def extra_ref(o, n):
    """追加の絵の見本: もとの絵（3 倍）の指定の範囲を、灰色の背景に重ねて大きく切り出す。範囲と倍率は _ref_<番号>.json に残す（place で使う）"""
    import numpy as np
    from PIL import Image
    r = o.extra[n]["ref"]
    src = os.path.join(o.work, r["from"] + "_3x.png")
    if not os.path.isfile(src):
        sys.exit("見本のもとの絵がありません: " + src)
    im = Image.open(src).convert("RGBA")
    box = r.get("box")
    if not box:
        a = np.asarray(im)[..., 3] > 8
        ys, xs = np.where(a)
        box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    pad = r.get("pad", 0.04)
    mx, my = int((box[2] - box[0]) * pad), int((box[3] - box[1]) * pad)
    box = [max(0, box[0] - mx), max(0, box[1] - my), min(im.width, box[2] + mx), min(im.height, box[3] + my)]
    c = im.crop(tuple(box))
    bg = Image.new("RGBA", c.size, tuple(r.get("bg", [128, 128, 128])) + (255,)); bg.alpha_composite(c)
    s = float(r.get("long", 1400)) / max(c.size)
    bg.convert("RGB").resize((int(round(c.width * s)), int(round(c.height * s))), Image.LANCZOS).save(os.path.join(o.work, "_ref_%s.png" % n))
    json.dump({"box": box, "scale": s, "from": r["from"]}, open(os.path.join(o.work, "_ref_%s.json" % n), "w"))


def alpha_report(path, check_dir):
    import numpy as np
    from PIL import Image
    im = Image.open(path)
    if im.mode != "RGBA":
        return "%s  大きさ %s  透過なし（%s）" % (os.path.basename(path), im.size, im.mode)
    a = np.asarray(im)[..., 3]
    ys, xs = np.where(a > 128)
    os.makedirs(check_dir, exist_ok=True)
    bg = Image.new("RGBA", im.size, (0, 200, 0, 255)); bg.alpha_composite(im)
    bg.convert("RGB").save(os.path.join(check_dir, "v_" + os.path.basename(path)))
    half = int(((a > 8) & (a < 247)).sum())
    box = "%d,%d-%d,%d" % (xs.min(), ys.min(), xs.max(), ys.max()) if len(xs) else "なし"
    return "%s  大きさ %s  不透明 %.1f%%  半透明 %.2f%%  範囲 %s" % (os.path.basename(path), im.size, 100.0 * (a > 128).mean(), 100.0 * half / a.size, box)


def draw_one(o, exe, n, res):
    out, ins = JOBS[n]
    pr = prompt_path(o, n)
    if not pr:
        res[n] = "指示文がありません: chars/%s/prompts/prompt_%s.txt" % (o.char, n); return
    # 指示文の中の {OUT} を、保存させる名前に置き換える（共通の指示文を、番号の違う絵に使い回せるように）
    prompt = open(pr, encoding="utf-8").read().replace("{OUT}", out)
    job = os.path.join(o.work, "_jobs", "j" + n)
    shutil.rmtree(job, ignore_errors=True); os.makedirs(job)
    args = []
    for name, stem in ins.items():
        src = os.path.join(o.work, stem + ".png")
        if not os.path.isfile(src):
            res[n] = "入力の絵がありません: " + src; return
        shutil.copy(src, os.path.join(job, name + ".png")); args += ["-i", name + ".png"]
    open(os.path.join(job, "prompt.txt"), "w", encoding="utf-8", newline="\n").write(prompt)     # 渡した指示文（記録用）
    t0 = time.time(); note = ""
    try:
        with open(os.path.join(job, "out.txt"), "wb") as log:
            subprocess.run([exe, "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", job] + args + ["-"],
                           input=prompt.encode("utf-8"), stdout=log, stderr=subprocess.STDOUT, cwd=job, timeout=o.timeout)
    except subprocess.TimeoutExpired:
        note = "（%d 秒で打ち切り）" % o.timeout
    got = os.path.join(job, out + ".png")
    if not os.path.isfile(got):
        # 打ち切られても、描けた絵が Codex 側に残っていることがある
        c = [p for p in glob.glob(os.path.join(os.path.expanduser("~"), ".codex", "generated_images", "**", "*.png"), recursive=True) if os.path.getmtime(p) >= t0]
        if len(c) == 1 and len(res["_ns"]) == 1:
            shutil.copy(c[0], got); note += "（Codex 側に残っていた絵を使った）"
        elif c:
            note += "（Codex 側に %d 枚残っています。見て選んでください: %s）" % (len(c), os.path.dirname(c[0]))
    if os.path.isfile(got):
        old = os.path.join(o.work, out + ".png")
        if os.path.isfile(old):                       # やり直しのときは、前の絵を残す
            k = 1
            while os.path.isfile(os.path.join(o.work, "_tries", "%s_try%d.png" % (out, k))):
                k += 1
            os.makedirs(os.path.join(o.work, "_tries"), exist_ok=True)
            shutil.move(old, os.path.join(o.work, "_tries", "%s_try%d.png" % (out, k)))
            big = os.path.join(o.work, out + "_3x.png")
            if os.path.isfile(big):
                os.remove(big)                        # 古い絵を拡大したものは使わせない
        shutil.copy(got, old)
        res[n] = "%3d 秒 %s %s" % (time.time() - t0, note, alpha_report(old, os.path.join(o.work, "_check")))
    else:
        res[n] = "%3d 秒 失敗 %s  記録: %s" % (time.time() - t0, note, os.path.join(job, "out.txt"))


def draw(o):
    exe = codex_exe()
    ns = o.args
    for n in ns:
        if n not in JOBS:
            sys.exit("知らない番号です: %s（%s）" % (n, " ".join(JOBS)))
    if any(JOBS[n][1].get("eye") == "_eye_ref" for n in ns):
        eye_ref(o)
    if any(JOBS[n][1].get("eye") == "_eyec_ref" for n in ns):
        eyec_ref(o)
    # 見本の名前（brow・ear・head）ではなく、見本の絵（_brow_ref・_ear_ref・_head_ref）で見る。追加の絵（extras.jobs）の見本に "name": "ear" と書いたとき、
    # 人の耳の見本（face/11_ears.png が要る）まで作ろうとして、止まった（犬の耳を描かせる絵。人の耳の無いキャラ）
    if any(JOBS[n][1].get("brow") == "_brow_ref" for n in ns):
        brow_ref(o)
    if any(JOBS[n][1].get("ear") == "_ear_ref" for n in ns):
        ear_ref(o)
    if any(JOBS[n][1].get("head") == "_head_ref" for n in ns):
        head_ref(o)
    for n in ns:
        if n in o.extra:
            extra_ref(o, n)
    res = {"_ns": ns}
    th = [threading.Thread(target=draw_one, args=(o, exe, n, res)) for n in ns]
    for t in th: t.start()
    for t in th: t.join()
    for n in ns:
        print("%-3s %s" % (n, res.get(n)))
    print("緑の背景に重ねた確認画像: " + os.path.join(o.work, "_check"))


# ---------------------------------------------------------------- upscale / face / model
def upscale(o):
    files = [os.path.join(o.work, v[0] + ".png") for k, v in JOBS.items() if k not in SQUARE]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        sys.exit("拡大する絵がありません: " + o.work)
    sys.exit(subprocess.run(PY + [os.path.join(HERE, "upscale.py")] + files + (["--force"] if o.force else [])).returncode)


def place(o):
    """追加で描かせた絵（extras.jobs）を、もとの絵の中の位置へ置く（extras.py）。"upscale": true の絵は、先に Real-ESRGAN で 3 倍にする。
    番号を書かなければ、全部を置く。ただし、キーの形のシート（"sheet": true。keyshape.py が使う絵で、置く物ではない）は除く"""
    for n in o.args:
        if n not in o.extra:
            sys.exit("char.json の extras.jobs に、その番号がありません: %s（ある番号: %s）" % (n, " ".join(sorted(o.extra)) or "なし"))
    ns = [n for n in (o.args or sorted(n for n in o.extra if not o.extra[n].get("sheet")))
          if o.extra[n].get("mirror") or os.path.isfile(os.path.join(o.work, o.extra[n]["out"] + ".png"))]
    ns.sort(key=lambda n: 1 if o.extra[n].get("mirror") else 0)          # 左右を返して使う絵は、もとの絵を置いた後で
    if not ns:
        sys.exit("置く絵がありません（char.json の extras.jobs と、draw で描かせた絵）")
    ups = [os.path.join(o.work, o.extra[n]["out"] + ".png") for n in ns if o.extra[n].get("upscale") and not o.extra[n].get("mirror")]
    if ups:
        rc = subprocess.run(PY + [os.path.join(HERE, "upscale.py")] + ups + (["--force"] if o.force else [])).returncode
        if rc:
            sys.exit(rc)
    rc = subprocess.run(PY + [os.path.join(HERE, "extras.py"), o.work] + ["%s=%s" % (n, o.extra[n]["out"]) for n in ns]).returncode
    print("もとの絵と比べた確認画像: " + os.path.join(o.work, "_check", "p_<番号>.png"))
    sys.exit(rc)


# 起動用の bat（ダブルクリックで、このモデルを開く。中身は start.bat を呼ぶだけ）。
# 中身は英数字だけにする（日本語を入れると、コマンドプロンプトが読み違える）
START_BAT = '@echo off\r\nrem Open the model "{name}" (see start.bat)\r\ncall "%~dp0start.bat" --model {name} %*\r\n'


def need(o, stem):
    p = os.path.join(o.work, stem + "_3x.png")
    if not os.path.isfile(p):
        sys.exit("絵がありません（先に draw と upscale を）: " + p)
    return p


def face(o):
    base, nohair = need(o, "00_base"), need(o, "01_base_nohair")
    ed, fd = os.path.join(o.work, "eye"), os.path.join(o.work, "face")
    os.makedirs(ed, exist_ok=True); os.makedirs(fd, exist_ok=True)
    for s in "LR":
        c = o.conf.get("eye" + s)
        if not c:
            sys.exit("char.json に eye%s（box と polys）がありません。grid.py で拡大図を見て置いてください" % s)
        rc, out = run(PY + [os.path.join(HERE, "eye.py"), nohair, ed, s] + [str(v) for v in c["box"]] + [json.dumps(c.get("polys", []))])
        print(out.strip()[-400:])
        if rc:
            sys.exit("eye.py が失敗しました（%s）" % s)
    # 設定を変えて作られなくなったパーツ（唇の塗り 17_lip など）の古い絵が残っていると、書き出しがそれを拾う。作り直す前に消す
    for p in glob.glob(os.path.join(fd, "*.png")):
        os.remove(p)
    rc, out = run(PY + [os.path.join(HERE, "build.py"), base, nohair, ed, fd])
    print(out.strip()[-600:])
    if rc:
        sys.exit("build.py が失敗しました")
    print("確認: %s の eyeL_sheet.png・eyeR_sheet.png、%s の各パーツ" % (ed, fd))


def model(o):
    name = (o.args[0] if o.args else o.char)
    nohair, front, back = need(o, "01_base_nohair"), need(o, "03_front_hair"), need(o, "04_back_hair")
    opt = lambda stem: (os.path.join(o.work, stem + "_3x.png") if os.path.isfile(os.path.join(o.work, stem + "_3x.png")) else "none")
    env = dict(os.environ)
    used = []
    for k, stem in MODEL_ENV.items():
        p = os.path.join(o.work, stem + "_3x.png")
        if os.path.isfile(p):
            env[k] = p; used.append(stem)
    for k, stem in MODEL_ENV_RAW.items():
        p = os.path.join(o.work, stem + ".png")
        if os.path.isfile(p):
            env[k] = p; used.append(stem)
    env["EXTRAS_DIR"] = o.work
    # 前の作り方（コマを切り替える目と口。今の手順では使わない。コマを切り出す道具は、このリポジトリに入れていない）:
    # 作業フォルダの sheet/ にコマの絵があり、char.json に "eye_sheet": {"closed": 5, "smile": 9} があるときだけ、閉じた目・笑って閉じた目に使う
    es = o.conf.get("eye_sheet") or {}
    for key, envk in (("closed", "EYE_CLOSED"), ("smile", "EYE_SMILE")):
        cp = os.path.join(o.work, "sheet", "eye_c%s.png" % es.get(key)) if es.get(key) else ""
        if cp and os.path.isfile(cp):
            env[envk] = cp; used.append("sheet/eye_c%s" % es[key])
    for k in (es.get("frames") or []):                                   # まばたきの途中のコマ（"frames": [2, 3, 4]）
        cp = os.path.join(o.work, "sheet", "eye_c%s.png" % k)
        if str(k) in ("2", "3", "4", "6") and os.path.isfile(cp):
            env["EYE_FRAME_C%s" % k] = cp; used.append("sheet/eye_c%s" % k)
    ms = o.conf.get("mouth_sheet") or {}                                 # 口の差分シート（"mouth_sheet": {"ref": "62"}。見本の範囲は _ref_62.json）
    mref = os.path.join(o.work, "_ref_%s.json" % ms.get("ref")) if ms.get("ref") else ""
    if mref and os.path.isfile(mref):
        env["MOUTH_SHEET_REF"] = mref
        for k in "123456789":
            cp = os.path.join(o.work, "sheet", "mouth_c%s.png" % k)
            if os.path.isfile(cp):
                env["MOUTH_FRAME_C" + k] = cp
        used.append("sheet/mouth_c*")
    kd = os.path.join(o.work, "key")                                     # キーの形（keyshape.py の出力）があれば使う。使わないときは char.json に "key_shapes": false
    if os.path.isdir(kd) and o.conf.get("key_shapes", True):
        env["KEY_DIR"] = kd; used.append("key")
    hl = os.path.join(o.work, "hair", "locks", "hair_locks.json")          # 毛束に分けた髪（hairlocks.py の出力）があれば使う
    if os.path.isfile(hl) and (o.conf.get("hair_locks", True)):
        env["HAIR_LOCKS"] = hl; used.append("hair_locks")
    outd = os.path.join(o.work, "model_out")
    shutil.rmtree(outd, ignore_errors=True); os.makedirs(outd)
    rc, out = run(PY + ["-X", "utf8", os.path.join(HERE, "build2.py"), nohair, front, back, opt("05_twintails"), opt("06_mouth_open"), os.path.join(o.work, "face"), outd], env=env)
    open(os.path.join(o.work, "model_out.log"), "w", encoding="utf-8").write(out)
    if rc or not os.path.isfile(os.path.join(outd, "model.json")):
        print(out.strip()[-1500:])
        sys.exit("失敗しました（モデルは差し替えていません）")
    dst = os.path.join(ROOT, "models", name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".new"
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    shutil.copytree(os.path.join(outd, "parts"), os.path.join(tmp, "parts")); shutil.copy(os.path.join(outd, "model.json"), tmp)
    shutil.rmtree(dst, ignore_errors=True); os.rename(tmp, dst)
    bat = os.path.join(ROOT, "start_%s.bat" % name)
    if not os.path.isfile(bat):
        open(bat, "w", encoding="ascii", newline="").write(START_BAT.replace("{name}", name))
    print("OK -> %s（%d パーツ）  使った絵: %s" % (name, len(os.listdir(os.path.join(dst, "parts"))), " ".join(used)))
    for l in out.splitlines():
        if l.startswith(("head ratio", "scale", "face y0", "iris", "neckdown", "extras")):
            print("  " + l)
    print("重ねた絵: " + os.path.join(outd, "_composite.png"))


def shots(o):
    name = (o.args[0] if o.args else o.char)
    sys.exit(subprocess.run(PY + [os.path.join(HERE, "regress.py"), "shoot", name, os.path.join(o.work, "_shots")]).returncode)


def audit(o):
    name = (o.args[0] if o.args else o.char)
    sys.exit(subprocess.run(PY + ["-X", "utf8", os.path.join(HERE, "parts_audit.py"), os.path.join(ROOT, "models", name), os.path.join(o.work, "_audit")]).returncode)


def fidelity(o):
    """元の絵に似ているかを見るための、並べた絵を作る。モデルがまだ無ければ、元の絵と 00_base だけ並べる"""
    name = (o.args[0] if o.args else o.char)
    sys.exit(subprocess.run(PY + [os.path.join(HERE, "fidelity.py"), o.work, o.cfg, name]).returncode)


def status(o):
    print("作業フォルダ: " + o.work)
    for k, (stem, _) in JOBS.items():
        a = os.path.isfile(os.path.join(o.work, stem + ".png")); b = os.path.isfile(os.path.join(o.work, stem + "_3x.png"))
        pr = prompt_path(o, k)
        where = "－" if not pr else ("○" if os.path.dirname(pr) == os.path.join(o.chardir, "prompts") else "○（共通の %s）" % os.path.basename(pr))
        print("  %-3s %-22s 絵 %s  3倍 %s  指示文 %s" % (k, stem, "○" if a else "－", "○" if b else ("　" if k in SQUARE else "－"), where))
    for d in ("eye", "face", "model_out"):
        print("  %-10s %s" % (d, "○" if os.path.isdir(os.path.join(o.work, d)) else "－"))


def check(o):
    """キャラを作るのに要るものが、そろっているかを確かめる（足りない物と、入れ方を出す）"""
    bad = []
    say = lambda ok, text, need=True: (print(("ok   " if ok else ("NG   " if need else "--   ")) + text), (bad.append(text) if not ok and need else None))
    v = sys.version_info
    say(v >= (3, 10), "Python %d.%d.%d（%s。3.10 以上）" % (v[0], v[1], v[2], sys.executable))
    for mod, pip_name in (("numpy", "numpy"), ("cv2", "opencv-python"), ("PIL", "pillow")):
        try:
            m = __import__(mod)
            say(True, "%s %s" % (pip_name, getattr(m, "__version__", "")))
        except ImportError:
            say(False, "%s が入っていません → python -m pip install -r tools/requirements.txt" % pip_name)
    node = shutil.which("node")
    nv = ""
    if node:
        rc, nv = run([node, "--version"])
        nv = nv.strip()
    try:
        major = int(nv.lstrip("v").split(".")[0])
    except ValueError:
        major = 0
    say(major >= 22, "Node.js %s（確認の撮影に使う。22 以上）" % (nv or "が見つかりません → https://nodejs.org/"))
    rc, out = run([node, "-e", "import('./partsgen/tools/chromeclose.mjs').then((m) => console.log(m.CHROME || ''))"], cwd=ROOT) if node else (1, "")
    chrome = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""
    say(bool(chrome), "Chrome / Edge: " + (chrome or "見つかりません → 環境変数 AVATAR_CHROME に実行ファイルを指定"))
    exe = kenv.codex_exe()
    if exe:
        try:
            rc, out = run([exe, "--version"])
        except OSError as e:
            rc, out = 1, str(e)
        say(rc == 0, "Codex CLI: %s（%s）" % (exe, out.strip().splitlines()[-1] if out.strip() else "版が分かりません"))
    else:
        say(False, "Codex CLI が見つかりません → 環境変数 CODEX_EXE に codex の実行ファイルを指定（画像生成ができるもの）")
    work, why = kenv.work_base_info()
    say(bool(work), "作業フォルダの置き場所: %s（%s）" % (work, why) if work else why)
    try:
        import upscale
        root, exe = upscale.find_root()
        say(True, "Real-ESRGAN: " + exe)
    except SystemExit:
        say(False, "Real-ESRGAN が見つかりません → pipeline.py install-upscaler で取ってくる（約 50MB）か、partsgen/UPSCALER.md の手順で置く")
    print()
    print("足りない物: %d 個" % len(bad) if bad else "全部そろっています。")
    sys.exit(1 if bad else 0)


def install_upscaler(o):
    import upscale
    upscale.install()
    sys.exit(0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "install-upscaler", "draw", "upscale", "place", "face", "model", "shots", "audit", "fidelity", "status"])
    ap.add_argument("char", nargs="?")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--work", help="キャラ 1 体の作業フォルダ（英数字だけのパス）。置き場所ごと変えるのは、環境変数 KESHIN2D_WORK")
    ap.add_argument("--timeout", type=int, default=420, help="draw: 1 枚を打ち切るまでの秒数")
    ap.add_argument("--force", action="store_true", help="upscale: 拡大済みでも作り直す")
    o = ap.parse_args()
    if o.cmd == "check":
        check(o)
    if o.cmd == "install-upscaler":
        install_upscaler(o)
    if not o.char:
        ap.error("キャラ名を指定してください（例: pipeline.py %s mychara）" % o.cmd)
    setup(o)
    {"draw": draw, "upscale": upscale, "place": place, "face": face, "model": model, "shots": shots, "audit": audit, "fidelity": fidelity, "status": status}[o.cmd](o)
