# -*- coding: utf-8 -*-
"""PC ごとに違う場所の決め方（作業フォルダ・一時フォルダ・Codex CLI）。pipeline.py・hairdraw.py ほかが、同じ決め方を使う。

作業フォルダの置き場所（キャラごとのフォルダの親）は、次の順で決める:
  1. 環境変数 KESHIN2D_WORK（英数字だけのパスにする）
  2. Windows: %LOCALAPPDATA%\\keshin2d_work    ほかの OS: ~/keshin2d_work
  3. 2 のパスに日本語などの文字が入るとき（Windows のユーザー名が日本語、など）:
     Windows: %PUBLIC%\\keshin2d_work（ふつうは C:\\Users\\Public\\keshin2d_work）→ %SystemDrive%\\keshin2d_work
     ほかの OS: /var/tmp/keshin2d_work
英数字だけにするのは、OpenCV（cv2.imread・imwrite）と Real-ESRGAN が、日本語のパスを読めないため。
リポジトリそのものは、日本語や空白を含むパスに置いてよい（道具は、絵を作業フォルダで読み書きする）。

道具は -I（ほかの設定や、今いるフォルダのファイルを読まない）で動かすので、使う側は
sys.path.insert(0, <このフォルダ>) をしてから import kenv する。
"""
import glob, os, shutil, sys, tempfile

NAME = "keshin2d_work"


def is_ascii(p):
    try:
        p.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _usable(p):
    try:
        os.makedirs(p, exist_ok=True)
        return os.access(p, os.W_OK)
    except OSError:
        return False


def work_base_info():
    """(置き場所, どう決まったかの一言) を返す。使える場所が無ければ (None, 理由)"""
    env = os.environ.get("KESHIN2D_WORK")
    if env:
        p = os.path.abspath(env)
        if not is_ascii(p):
            return None, "環境変数 KESHIN2D_WORK のパスに、日本語などの文字が入っています（英数字だけのパスにしてください）: " + p
        return (p, "環境変数 KESHIN2D_WORK") if _usable(p) else (None, "環境変数 KESHIN2D_WORK のフォルダを作れません: " + p)
    if sys.platform == "win32":
        first = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), NAME)
        rest = [os.path.join(b, NAME) for b in (os.environ.get("PUBLIC"), (os.environ.get("SystemDrive") or "C:") + os.sep) if b]
    else:
        first = os.path.join(os.path.expanduser("~"), NAME)
        rest = [os.path.join("/var/tmp", NAME)]
    first = os.path.abspath(first)
    if is_ascii(first) and _usable(first):
        return first, "既定の場所"
    for p in rest:
        p = os.path.abspath(p)
        if is_ascii(p) and _usable(p):
            return p, "既定の場所（%s）は、日本語などの文字が入るか、書き込めないので、こちらを使う" % first
    return None, "英数字だけのパスで、書き込める作業フォルダが見つかりません。環境変数 KESHIN2D_WORK に、英数字だけのパスのフォルダを指定してください（既定の場所: %s）" % first


def work_base():
    p, why = work_base_info()
    if not p:
        sys.exit(why)
    return p


def char_work(char):
    """そのキャラの作業フォルダ（<置き場所>/<キャラ名>）"""
    return os.path.join(work_base(), char)


def tmp_dir(prefix):
    """英数字だけのパスの一時フォルダを作って返す（使い終わったら、呼んだ側が消す）。
    ふつうは OS の一時フォルダ。そのパスに日本語などが入るとき（Windows のユーザー名が日本語、など）は、作業フォルダの置き場所の _tmp の中"""
    if is_ascii(tempfile.gettempdir()):
        return tempfile.mkdtemp(prefix=prefix)
    d = os.path.join(work_base(), "_tmp")
    os.makedirs(d, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=d)


def codex_exe():
    """Codex CLI の実行ファイル（見つからなければ None）。
    環境変数 CODEX_EXE → Codex アプリ（Windows）に同梱の物 → PATH の codex の順に探す"""
    if os.environ.get("CODEX_EXE"):
        return os.environ["CODEX_EXE"]
    c = glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "OpenAI", "Codex", "bin", "*", "codex.exe")) if os.environ.get("LOCALAPPDATA") else []
    if c:
        return max(c, key=os.path.getmtime)          # 作った時点では、npm で入れた版は画像生成が動かなかった
    return shutil.which("codex")
