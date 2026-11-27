# -*- coding: utf-8 -*-
"""リポジトリの中身が、そろっているかを確かめる（Python 3.8 以上の標準ライブラリだけで動く。ブラウザは使わない）。

  python tools/check_repo.py

確かめること:
  1. JSON が読める（models/index.json・同梱のモデルの model.json・partsgen/chars/*/char.json ほか）
  2. models/index.json に書いたモデルがあり、model.json が指す絵が、大文字小文字まで同じ名前で全部ある
     （Windows は大文字小文字を区別しないが、GitHub Pages などは区別する）。使われていない絵が残っていない
  3. 同梱の外部の物（vendor/mediapipe）が、SHASUMS256.txt のチェックサムと合う
  4. Python の道具が、構文エラーなく読める
  5. 文書（*.md）の中の、リポジトリ内へのリンクと絵が、実際にある
  6. .bat は英数字だけ・CRLF（cmd.exe が読み違えないように）。.ps1 は BOM 付き
  7. 表示用のサーバー（tools/serve.py）が起動して、ビューアとモデルを配れる

結果は 1 行ずつ出す（ok / NG）。NG が 1 つでもあれば、終了コード 1。
画面の動きは確かめない（それは partsgen/tools/uicheck.mjs。Node.js と Chrome が要る）。
"""
import glob, hashlib, json, os, re, socket, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0


def say(ok, text):
    global bad
    if not ok:
        bad += 1
    print(("ok " if ok else "NG ") + text)


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def exists_exact(path):
    """大文字小文字まで同じ名前で、あるか（ROOT からの相対パス。区切りは /）"""
    cur = ROOT
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            cur = os.path.dirname(cur)
            continue
        try:
            if part not in os.listdir(cur):
                return False
        except OSError:
            return False
        cur = os.path.join(cur, part)
    return True


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def png_refs(o):
    """model.json の中の、.png で終わる文字列を全部"""
    if isinstance(o, dict):
        for v in o.values():
            yield from png_refs(v)
    elif isinstance(o, list):
        for v in o:
            yield from png_refs(v)
    elif isinstance(o, str) and o.lower().endswith(".png"):
        yield o


def check_json_and_models():
    files = [os.path.join(ROOT, "models", "index.json"), os.path.join(ROOT, "partsgen", "upscaler.example.json")]
    files += sorted(glob.glob(os.path.join(ROOT, "partsgen", "chars", "*", "char.json")))
    broken = []
    for f in files:
        try:
            load_json(f)
        except (OSError, ValueError) as e:
            broken.append("%s（%s）" % (rel(f), e))
    say(not broken, "JSON が読める（%d ファイル）" % len(files) + (": " + " / ".join(broken) if broken else ""))

    try:
        models = load_json(os.path.join(ROOT, "models", "index.json")).get("models", [])
    except (OSError, ValueError, AttributeError):
        models = []
    names = [m.get("name", "") for m in models if isinstance(m, dict)]
    say(bool(names) and all(re.fullmatch(r"[A-Za-z0-9_\-]+", n) for n in names),
        "models/index.json に、モデルの名前が書いてある（%s）" % "・".join(names))
    for n in names:
        mj = "models/%s/model.json" % n
        if not exists_exact(mj):
            say(False, "%s がある" % mj)
            continue
        try:
            model = load_json(os.path.join(ROOT, mj))
        except (OSError, ValueError) as e:
            say(False, "%s が読める（%s）" % (mj, e))
            continue
        refs = sorted(set(png_refs(model)))
        missing = [r for r in refs if not exists_exact("models/%s/parts/%s" % (n, r))]
        say(not missing, "%s: model.json が指す絵 %d 枚が、大文字小文字まで同じ名前で全部ある" % (n, len(refs))
            + ("（無い: %s）" % ", ".join(missing[:5]) if missing else ""))
        have = sorted(os.listdir(os.path.join(ROOT, "models", n, "parts")))
        extra = [h for h in have if h not in refs]
        say(not extra, "%s: parts/ に、使われていないファイルが無い" % n + ("（%s）" % ", ".join(extra[:5]) if extra else ""))
        say(exists_exact("partsgen/chars/%s/char.json" % n), "%s: 設定（partsgen/chars/%s/char.json）がある" % (n, n))


def check_vendor():
    base = os.path.join(ROOT, "vendor", "mediapipe")
    wrong, n = [], 0
    try:
        with open(os.path.join(base, "SHASUMS256.txt"), encoding="utf-8") as f:
            lines = [ln.split(None, 1) for ln in f.read().splitlines() if ln.strip()]
    except OSError as e:
        say(False, "vendor/mediapipe/SHASUMS256.txt が読める（%s）" % e)
        return
    for digest, name in lines:
        n += 1
        try:
            with open(os.path.join(base, name.strip()), "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != digest:
                    wrong.append(name.strip())
        except OSError:
            wrong.append(name.strip() + "（無い）")
    say(n > 0 and not wrong, "同梱の MediaPipe（%d ファイル）が、チェックサムと合う" % n + ("（合わない: %s）" % ", ".join(wrong) if wrong else ""))


def check_python():
    files = sorted(glob.glob(os.path.join(ROOT, "tools", "**", "*.py"), recursive=True) + glob.glob(os.path.join(ROOT, "partsgen", "tools", "**", "*.py"), recursive=True))
    broken = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                compile(fh.read(), f, "exec")
        except (SyntaxError, ValueError, OSError) as e:
            broken.append("%s（%s）" % (rel(f), e))
    say(not broken, "Python の道具が、構文エラーなく読める（%d ファイル）" % len(files) + (": " + " / ".join(broken) if broken else ""))


LINK = re.compile(r"\]\(([^)\s]+)\)|(?:src|href)=\"([^\"]+)\"")


def check_links():
    docs = []
    for pat in ("*.md", ".github/*.md", "partsgen/*.md", "partsgen/chars/*/*.md"):
        docs += glob.glob(os.path.join(ROOT, pat))
    missing, n = [], 0
    for d in sorted(set(docs)):
        if not exists_exact(rel(d)) or rel(d) == "HANDOFF.md":
            continue
        with open(d, encoding="utf-8") as f:
            text = re.sub(r"```.*?```", "", f.read(), flags=re.S)   # コードの例の中は見ない
        for m in LINK.finditer(text):
            link = (m.group(1) or m.group(2)).split("#", 1)[0]
            if not link or re.match(r"[a-z][a-z0-9+.\-]*:", link):   # ページ内のリンク、http: などは見ない
                continue
            n += 1
            target = os.path.normpath(os.path.join(os.path.dirname(rel(d)), link)).replace("\\", "/")
            if target.startswith("..") or not exists_exact(target):
                missing.append("%s → %s" % (rel(d), link))
    say(not missing, "文書の中の、リポジトリ内へのリンクと絵（%d か所）が、実際にある" % n + ("（無い: %s）" % " / ".join(missing[:8]) if missing else ""))


def check_scripts():
    wrong = []
    for f in sorted(glob.glob(os.path.join(ROOT, "*.bat"))):
        if not exists_exact(rel(f)):
            continue
        data = open(f, "rb").read()
        if any(b > 0x7E for b in data) or b"\r\n" not in data or re.search(rb"(?<!\r)\n", data):
            wrong.append(rel(f) + "（英数字だけ・CRLF でない）")
    for f in sorted(glob.glob(os.path.join(ROOT, "partsgen", "tools", "*.ps1"))):
        if open(f, "rb").read(3) != b"\xef\xbb\xbf":
            wrong.append(rel(f) + "（BOM が無い）")
    say(not wrong, ".bat は英数字だけ・CRLF、.ps1 は BOM 付き" + ("（%s）" % " / ".join(wrong) if wrong else ""))


def check_server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "serve.py"), "--no-browser", "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d/" % port

    def get(path):
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, r.read()
    try:
        err, listed = "", []
        for _ in range(50):   # 起動を待つ（最大 5 秒）
            try:
                get("index.html")
                break
            except OSError:
                time.sleep(0.1)
        try:
            listed = [m["name"] for m in json.loads(get("models/index.json")[1])["models"]]
            for p in ["index.html", "js/avatar.js", "js/keyshape.js", "js/lipsync.js"] + ["models/%s/model.json" % n for n in listed]:
                st, body = get(p)
                if st != 200 or not body:
                    err = p
        except (OSError, ValueError, KeyError) as e:
            err = str(e)
        want = [m["name"] for m in load_json(os.path.join(ROOT, "models", "index.json"))["models"]]
        say(not err and listed[:len(want)] == want, "表示用のサーバーが起動して、ビューアとモデルを配る（一覧: %s）" % "・".join(listed) + ("（失敗: %s）" % err if err else ""))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    check_json_and_models()
    check_vendor()
    check_python()
    check_links()
    check_scripts()
    check_server()
    print("NG %d 件" % bad if bad else "全部 ok")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
