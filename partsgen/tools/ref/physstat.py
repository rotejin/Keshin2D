# 揺れ物の揺れを、数字で数える（livecap.mjs --probe の記録 probe.json から）。
#   physstat.py <録画フォルダ> [揺れ物の id（省略で全部）] [--tol 度] [--trace 開始秒 終了秒 [何個おき]]
#
# 絵を時間順に並べて見ても、「何回揺れたか」「いつ止まったか」は、数えにくい。ここでは、台本の動き（move・glide・circle）ごとに、
#   - 根元と先の振れ角の山（止まった値から、向きが変わる所。tol 度より大きい物）の数と大きさ
#   - 止まるまでの秒（そのあとずっと、止まった値の ±tol 度に入るまで。頭が動いている時間も入る）
#   - 上下のはずみの幅
# を出す。--trace は、その間の値を、時間順にそのまま出す（頭の向き、振れ角、固い板の伸び縮みと回り）。
# 目安（上へ伸びる毛 sprout）: 一気に向きを変えたあと、山は 3〜4 個で、だんだん小さくなり、1.2 秒以内に止まる。
#   先の山が、根元の 2 倍を大きく超える・5 個以上つづく・小さくならないなら、薄い紙がぺらぺら動くように見える。
import sys, os, json, math, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
args = sys.argv[1:]


def opt(name, n):
    if name not in args:
        return None
    i = args.index(name)
    v = []
    while len(v) < n and i + 1 < len(args) and not args[i + 1].startswith('--'):
        v.append(args.pop(i + 1))
    args.pop(i)
    return v


tol = float((opt('--tol', 1) or ['1.0'])[0])
trace = opt('--trace', 3)
if not args:
    print('使い方: physstat.py <録画フォルダ> [揺れ物の id] [--tol 度] [--trace 開始秒 終了秒 [何個おき]]')
    sys.exit(1)
src = args[0]
pp = os.path.join(src, 'probe.json')
if not os.path.exists(pp):
    print('NG probe.json がありません。livecap.mjs に --probe を付けて録ってください: ' + src)
    sys.exit(1)
P = json.load(open(pp, encoding='utf-8'))
log = json.load(open(os.path.join(src, 'frames.json'), encoding='utf-8'))['log']
ids = []
for _, _, ph in P:
    for s in ph or []:
        if s['id'] not in ids:
            ids.append(s['id'])
if len(args) > 1:
    if args[1] not in ids:
        print('NG 揺れ物 %s は、このモデルにありません（ある物: %s）' % (args[1], '・'.join(ids) or 'なし'))
        sys.exit(1)
    ids = [args[1]]
if not ids:
    print('このモデルには、揺れ物がありません')
    sys.exit(0)


def rows_of(pid):
    out = []
    for t, st, ph in P:
        s = next((p for p in ph or [] if p['id'] == pid), None)
        if s:
            out.append((t, st or {}, s))
    return out


for pid in ids:
    R = rows_of(pid)
    print('== %s（%d 個の記録）' % (pid, len(R)))
    if trace:
        ta, tb = float(trace[0]), float(trace[1])
        every = int(trace[2]) if len(trace) > 2 else 1
        print('    秒   左右   上下   根元     先   上下のはずみ | 伸び縮み（大・小） 回り')
        for t, st, s in [r for r in R if ta <= r[0] <= tb][::every]:
            a, b, c, d = s['J'] or [1, 0, 0, 1]
            E, F, G, H = (a + d) / 2, (a - d) / 2, (c + b) / 2, (c - b) / 2
            Q, Rr = math.hypot(E, H), math.hypot(F, G)
            print('%6.2f %6.1f %6.1f %6.1f %6.1f %8.3f | %5.2f %5.2f %6.1f' % (
                t, st.get('yaw', 0), st.get('pitch', 0), math.degrees(s['phi']), math.degrees(s['phi2']), s['by'], Q + Rr, Q - Rr, math.degrees(math.atan2(H, E))))
        continue
    ev = [e for e in log if e[1] in ('move', 'glide', 'circle', 'end')]
    for i, e in enumerate(ev[:-1]):
        t0, t1 = e[0], ev[i + 1][0]
        seg = [r for r in R if t0 <= r[0] < t1]
        if len(seg) < 8:
            continue
        cols = []
        for key, name in (('phi', '根元'), ('phi2', '先')):
            v = [math.degrees(r[2][key]) for r in seg]
            end = sum(v[-5:]) / 5
            d = [x - end for x in v]
            peaks = [d[k] for k in range(1, len(d) - 1) if (d[k] - d[k - 1]) * (d[k + 1] - d[k]) <= 0 and abs(d[k]) > tol]
            merged = []
            for p in peaks:      # 同じ向きに続く山は、大きい方 1 つにまとめる
                if merged and (p > 0) == (merged[-1] > 0):
                    merged[-1] = p if abs(p) > abs(merged[-1]) else merged[-1]
                else:
                    merged.append(p)
            last = max([k for k in range(len(d)) if abs(d[k]) > tol], default=0)
            cols.append('%s 山 %d 個 [%s] 止まるまで %.2f 秒' % (name, len(merged), ' '.join('%+.1f' % p for p in merged[:8]), seg[last][0] - t0))
        by = [r[2]['by'] for r in seg]
        print('%6.2f 秒 %-6s | %s | %s | 上下 %+.3f〜%+.3f' % (t0, e[1], cols[0], cols[1], min(by), max(by)))
