# -*- coding: utf-8 -*-
"""eyeedge.py <probe の出力.jsonl> <モデルのフォルダ（model.json のある所）>

横・斜めを向いたとき、**奥の目の目尻（白目の外の端）が、顔の輪郭より、どれだけ内側にあるか**を、姿勢ごとに出す。
  余裕 = 輪郭 − 目尻（モデルの座標の画素）。**− は、目尻が輪郭の外**（白目が輪郭で切れ、下まぶたの線・目尻の影が、輪郭の外の髪の上に描かれる）。
  瞳の高さと、下まぶたの高さ（瞳の中心から 40 画素下）の 2 か所で測る。

使い方（Keshin2D で）:
  node partsgen/tools/ref/probe.mjs kurage02 "yaw=0" "yaw=30" "yaw=30&pitch=-25" "yaw=-30&pitch=-25" … > p.jsonl
  ./.venv/Scripts/python.exe -I partsgen/tools/ref/eyeedge.py p.jsonl models/kurage02

目安: 左右いっぱいでも斜めでも、奥の目が、輪郭のすぐ内側に収まる（越えるのは、まつげの先だけ。
瞳の外の端から輪郭まで: 真横で 0.14〜0.15E、斜め下で 0.06〜0.09E。E = 正面の両目の間隔）。顔の幅に対して目が大きいキャラでは、越える。
kurage02: 左右 30°だけなら +8〜25、左右 30°+ 下 25°で −36〜−58（斜め下で、奥の目が輪郭をまたぐ。分かっている課題）。

目の幅の縮み方（エンジンの makeGroup の zx。目は 0.55）は、ここにも書いてある。エンジンを変えたら、合わせる。
URL の yaw・pitch は、エンジンと同じに、モデルの向きの上限（model.json の tune の yawMax・upMax・downMax）で、実際の角度に直して使う
（yaw=30 が左右の上限いっぱい、pitch=25 が上、pitch=-25 が下の上限いっぱい）。
"""
import sys, json, math, os

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
m = json.load(open(os.path.join(sys.argv[2], "model.json"), encoding="utf-8"))
C = m["curves"]
ZX = 0.55                                   # js/avatar.js の makeEye: makeGroup(…, 0.65 * R0, 0.55, …)
E = C["eyeL"]["iris"][0] - C["eyeR"]["iris"][0]
T = m.get("tune") or {}
YAW_MAX, UP_MAX, DOWN_MAX = float(T.get("yawMax", 20)), float(T.get("upMax", 5)), float(T.get("downMax", 5))   # 無いときの値は、エンジン（js/avatar.js の TUNE）の既定


def edge_x(pts, y, right):
    """輪郭（画面の座標）の、高さ y での x。pts = [xl, yl, xr, yr] の列"""
    P = [(p[3], p[2]) if right else (p[1], p[0]) for p in pts]
    best = None
    for (y0, x0), (y1, x1) in zip(P, P[1:]):
        if (y0 - y) * (y1 - y) <= 0 and y0 != y1:
            x = x0 + (x1 - x0) * (y - y0) / (y1 - y0)
            if best is None or (right and x > best) or (not right and x < best):
                best = x
    return best


print("E（正面の両目の間隔）= %.1f 画素" % E)
print("%-34s %8s %8s %8s   %s" % ("姿勢", "目尻", "輪郭", "幅の倍率", "余裕（輪郭 − 目尻。− は、目尻が輪郭の外）"))
for r in rows:
    q = dict(kv.split("=") for kv in r["q"].split("&") if "=" in kv)
    yaw = float(q.get("yaw", 0)); pit = float(q.get("pitch", 0))
    if yaw == 0:
        continue
    # URL の値 → 実際の角度（js/avatar.js: yaw = F.yaw / 30 × yawMax、pitch = F.pitch / 25 ×（上は upMax、下は downMax））
    yaw = yaw / 30.0 * YAW_MAX; pit = pit / 25.0 * (UP_MAX if pit > 0 else DOWN_MAX)
    right = yaw > 0                         # 画面右を向く → 奥の目は L（画面右）
    k = "L" if right else "R"
    c = C["eye" + k]; side = 1 if right else -1
    s = math.sin(math.radians(abs(yaw))); co = math.cos(math.radians(yaw))
    sx = max(0.35, co - ZX * s)
    outer = c["xb"] if right else c["xa"]
    ex, ey = r["e"][k]
    xo = ex + sx * (outer - c["iris"][0])
    out = []
    for dy, nm in ((0, "瞳の高さ"), (40, "下まぶた")):
        cx = edge_x(r["pts"], ey + dy * math.cos(math.radians(pit)), right)
        if cx is not None:
            out.append((nm, cx, (cx - xo) * side))
    if not out:
        print("%-34s （輪郭が読めない）" % r["q"]); continue
    print("%-34s %8.1f %8.1f %8.3f   %s" % (r["q"], xo, out[0][1], sx, "  ".join("%s %+.1f（%+.2fE）" % (n, g, g / E) for n, _, g in out)))
