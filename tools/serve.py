# -*- coding: utf-8 -*-
"""Keshin2D をブラウザで開く（start.bat・start.sh が使う。Python 3.8 以上の標準ライブラリだけで動く）。

  python tools/serve.py [--model 名前] [--port 番号] [--no-browser] [--query "URL に足す指定"]

- このフォルダを http://127.0.0.1:<番号>/ で配り、ブラウザで index.html?model=<名前> を開く。
- 番号（既定 8770）が使われていれば、空いている番号を探す（最大 20 個先まで）。
- ブラウザは Google Chrome があれば Chrome、無ければ既定のブラウザ。
- ブラウザにキャッシュさせない（Cache-Control: no-store）。python -m http.server のままだと、
  エンジンの js を直しても、ブラウザが前の版を使い続けることがある。
- 止めるとき: この窓で Ctrl+C を押すか、窓を閉じる。
"""
import argparse, errno, functools, http.server, os, shutil, subprocess, sys, threading, webbrowser

import socket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDR_IN_USE = {errno.EADDRINUSE, 10013, 10048}   # 10048 / 10013: Windows の「使われている」「使えない」


class Server(http.server.ThreadingHTTPServer):
    # Windows の SO_REUSEADDR は、ほかの処理が使っているポートにも重ねて結び付けてしまう（空いている番号へ移れない）。
    # Windows では、そのポートを 1 つの処理だけが使う指定（SO_EXCLUSIVEADDRUSE）にする
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class NoStore(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
                      ".wasm": "application/wasm", ".task": "application/octet-stream", ".map": "application/json"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):   # 1 回ごとの記録は出さない（失敗だけ出す）
        if len(args) > 1 and str(args[1])[:1] in "45":
            sys.stderr.write("  %s %s\n" % (args[1], args[0]))


def find_chrome():
    """Google Chrome の起動のしかた（見つからなければ None）"""
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                p = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
                if os.path.isfile(p):
                    return [p]
    elif sys.platform == "darwin":
        if os.path.isdir("/Applications/Google Chrome.app"):
            return ["open", "-a", "Google Chrome"]
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            p = shutil.which(name)
            if p:
                return [p]
    return None


def open_browser(url):
    chrome = find_chrome()
    if chrome:
        try:
            subprocess.Popen(chrome + [url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "Google Chrome"
        except OSError:
            pass
    webbrowser.open(url)
    return "既定のブラウザ"


def bind(port):
    handler = functools.partial(NoStore, directory=ROOT)
    for p in range(port, port + 21):
        try:
            return Server(("127.0.0.1", p), handler)
        except OSError as e:
            if e.errno not in ADDR_IN_USE and getattr(e, "winerror", None) not in ADDR_IN_USE:
                raise
    sys.exit("ポート %d〜%d が、どれも使われています。--port で別の番号を指定してください。" % (port, port + 20))


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8", line_buffering=True)   # 窓の外へ出したときも、すぐ・文字化けせずに出す
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Keshin2D をブラウザで開く")
    ap.add_argument("--model", default="kurage02", help="開くモデル（models/ の中のフォルダ名。既定 kurage02）")
    ap.add_argument("--port", type=int, default=8770, help="使うポートの番号（既定 8770。使われていれば次の番号）")
    ap.add_argument("--query", default="hair=1", help="URL に足す指定（既定 hair=1）")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを開かない")
    o = ap.parse_args()

    models = os.path.join(ROOT, "models")
    if not os.path.isfile(os.path.join(models, o.model, "model.json")):
        have = sorted(d for d in os.listdir(models) if os.path.isfile(os.path.join(models, d, "model.json"))) if os.path.isdir(models) else []
        sys.exit("モデル「%s」がありません（models/%s/model.json）。あるモデル: %s" % (o.model, o.model, ", ".join(have) or "なし"))

    srv = bind(o.port)
    port = srv.server_address[1]
    url = "http://127.0.0.1:%d/index.html?model=%s%s" % (port, o.model, ("&" + o.query) if o.query else "")
    print("Keshin2D を配っています: " + url)
    if not o.no_browser:
        threading.Timer(0.3, lambda: print("  " + open_browser(url) + " で開きました")).start()
    print("止めるとき: この窓で Ctrl+C を押すか、窓を閉じてください。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n止めました。")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
