# Keshin2D（化身 2D）

キャラクターの絵を、ブラウザで動かす 2D アバターです。名前の「化身（けしん）」は、英語の avatar（アバター）の、もとの意味の訳語です。
パーツに分けた絵を WebGL2 でメッシュ変形して、顔の向き・視線・まばたき・表情・口・髪と飾りの揺れを、毎フレーム描きます。
専用のモデリングソフトは要りません。動かすのに要るのは、Python とブラウザだけです。

![kurage02 の表情と向き](docs/images/kurage02.jpg)

同梱のモデルは `kurage02`（クラゲちゃん）の 1 体です。
新しいキャラは、キャラクターの絵 1 枚から、画像生成と同梱の道具で作れます（[キャラを作る](#新しいキャラを作る)）。

## 動かす

要るもの:

- Python 3.8 以上（標準のライブラリだけで動きます。追加のインストールは要りません。3.10・3.12 で確かめています）
- WebGL2 が使えるブラウザ（Google Chrome・Microsoft Edge で確かめています。Firefox・Safari は確かめていません）

| OS | 起動のしかた |
|---|---|
| Windows | `start.bat` をダブルクリック |
| macOS・Linux | ターミナルで `./start.sh`（実行できないときは `sh start.sh`。ZIP で取ると、実行の権限が外れることがあります） |
| どれでも | `python tools/serve.py`（`python3` の環境もあります） |

ブラウザが開いて、kurage02 が表示されます。Google Chrome があれば Chrome、無ければ既定のブラウザで開きます。
開いた窓（黒い画面）が、表示用の小さなサーバーです。止めるときは、その窓で Ctrl+C を押すか、窓を閉じます。

- 番号 8770 のポートを使います。使われていれば、空いている番号を探します（最大 20 個先まで）。`--port 番号` でも指定できます。
- `index.html` をダブルクリックして直接開くと、動きません（ブラウザが、ファイルからの読み込みを止めるため）。必ず上の方法で開いてください。

![画面](docs/images/viewer.jpg)

### 画面の操作

| 操作 | 内容 |
|---|---|
| 動かし方 | マウス（カーソルの方を向く）・デモ（約 14 秒のひとり芝居）・Web カメラ（顔の動きに合わせる）・手動（スライダー） |
| マイクで口パク | 声に合わせて口を動かします。声の母音（あいうえお）で口の形も変わります |
| 口のデモ | 音を出さずに、話している口・あいうえおを見せます |
| 表情 | 通常のほかに 21 個（にこ・笑顔・怒り・困り・ジト目・びっくり・ウインク・キラキラ・ハートなど） |
| 背景 | 明るい色・暗い色・白・緑（クロマキー）・透過 |
| 配置 | 画面をドラッグで位置、ホイールで大きさ、ダブルクリックで元に戻す |
| H キー | 操作パネルを隠す・出す |
| 細かい調整 | 向きの上限、髪や飾りの揺れ、瞳の動き、母音の口の形、マイクの調整など。「今の調整値を書き出す」で、モデルの初期値にする値を書き出せます |

調整した値と配置は、ブラウザに保存されます（モデルごと。ポートの番号が変わると、別の保存になります）。各項目の「初期値に戻す」で戻せます。

- **Web カメラ**: 顔の追跡に MediaPipe（Google）を使います。同梱してあるので（`vendor/mediapipe/`）、インターネットにつながっていなくても使えます。カメラの映像は、ブラウザの外へは送りません。
- **マイク**: ブラウザの中で音の大きさと母音を調べるだけで、音は送りません。

### OBS で使う

OBS の「ブラウザ」ソースに、次の URL を入れます（サーバーは起動したままにします。`model=` は、使うモデルの名前）。

```text
http://127.0.0.1:8770/index.html?model=kurage02&ui=0&bg=transparent
```

`ui=0` で操作パネルを出さず、`bg=transparent` で背景を透過にします。幅と高さは、配信の画面に合わせてください。

**OBS の上での動きは、まだ確かめていません**（マウス追従・Web カメラ・マイクが、OBS のブラウザソースの中で使えるかを含めて）。
うまく動かないときは、ふつうのブラウザで `bg=green`（緑の背景）にして開き、その窓をウィンドウキャプチャして、クロマキーで抜く方法もあります。

### URL の指定

`index.html?` のあとに `&` でつなげて書きます。

| 指定 | 例 | 内容 |
|---|---|---|
| `model` | `model=kurage02` | 開くモデル（`models/` の中のフォルダ名） |
| `hair` | `hair=0` | 髪を出さない（顔の確認用。指定しなければ髪を出す） |
| `ui` | `ui=0` | 操作パネルを出さない |
| `bg` | `bg=transparent` | 背景（`room`・`dark`・`white`・`green`・`transparent`） |
| `mode` | `mode=demo` | 動かし方（`mouse`・`demo`・`camera`・`manual`） |
| `exp` | `exp=笑顔` | 表情。指定すると、その表情で止めて表示します |
| `yaw`・`pitch`・`roll` | `yaw=20` | 顔の左右・上下・かしげ（度）。指定すると、その向きで止めて表示します |
| `cx`・`cy`・`zoom` | `zoom=2&cy=800` | 表示の中心と大きさ（指定すると、保存した配置を使いません） |

ほかに、調整パネルのスライダーの項目も、名前で指定できます（例: `yawMax=25`。名前は `js/avatar.js` の `PARAMS`・`TUNE`）。

## 新しいキャラを作る

キャラクターの絵 1 枚から、画像生成（Codex CLI）で、パーツを清書した絵を描かせ、同梱の道具で切り出し・配置して、モデルを書き出します。
作業は、AI のコーディングエージェント（Claude Code など）に、指示文（`partsgen/MASTER_PROMPT.md`）を渡して進めさせる前提です。人が見て決める所（基準の絵がそのキャラに見えるか、髪のデザインの案、動かしたときの感触）では、エージェントが止まって確かめます。

要るもの（くわしくは [partsgen/README.md](partsgen/README.md)）:

- Python 3.10 以上（`numpy`・`opencv-python`・`pillow`）、Node.js 22 以上、Google Chrome か Microsoft Edge
- 画像生成ができる Codex CLI（OpenAI。利用には、OpenAI の契約が要ります。Windows の Codex アプリ同梱の物で確かめています）
- Real-ESRGAN（拡大に使う。Vulkan に対応した GPU が要ります。同梱はしていませんが、準備のコマンド 1 つで、配布元から取ってこられます。[partsgen/UPSCALER.md](partsgen/UPSCALER.md)）
- AI のコーディングエージェント（作業を進めさせる）

準備ができたら、エージェントに、キャラクターの絵の場所と、付けたい名前（英数字）の 2 つを書いた指示文を渡します。できたモデルは `models/<名前>/` に入り、`start.bat --model <名前>` で開けます。

道具は Windows で作り、確かめています。ほかの OS では確かめていません（とくに、画像生成ができる Codex CLI が用意できるかは、OS と Codex の版によります）。
Windows のユーザー名が日本語の PC でも使えます（絵を置く作業フォルダは、道具が、英数字だけのパスの場所を選びます）。

## フォルダの構成

| 場所 | 内容 |
|---|---|
| `index.html`、`js/avatar.js` | ビューアとエンジン |
| `js/keyshape.js` | 目と口を、描いた絵（キーの形）の変形で動かす |
| `js/lipsync.js` | マイクの口パク（音の大きさと母音） |
| `models/<名前>/` | モデル（`model.json` と `parts/*.png`） |
| `tools/serve.py` | 表示用のサーバー（`start.bat`・`start.sh` が使う） |
| `vendor/mediapipe/` | Web カメラの顔の追跡（MediaPipe Tasks Vision 0.10.14 と Face Landmarker のモデル。`SHASUMS256.txt` に、取ってきたときのチェックサム） |
| `partsgen/` | 新しいキャラを作る道具と手順書 |
| `docs/images/` | この説明に使っている絵 |

## 分かっている課題

- kurage02 は、斜め下いっぱいを向くと、奥の目が顔の輪郭を少しまたぎます。
- Web カメラの追跡と、マイクの口パクは、テスト用の映像と音で動くことまでは確かめています。実際の顔と声での当たり具合は、まだ十分に確かめていません。

## ライセンス

- [MIT License](LICENSE)。プログラム（`js/`・`tools/`・`partsgen/` ほか）も、同梱のモデル `kurage02`（`models/kurage02/` の絵と `model.json`）と `docs/images/` の絵も、同じ MIT です（`vendor/mediapipe/` に同梱した MediaPipe だけは、Apache License 2.0）。自分のアバターとして使う・改変する・配信や営利に使うことも、MIT の条件（著作権表示とライセンス文を残す）で自由です。
- 使わせてもらっている物と、そのライセンス: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

---

## English (summary)

Keshin2D ("keshin", 化身, is the Japanese word for avatar) is a 2D avatar that runs in the browser. It deforms a character's layered artwork with WebGL2 meshes every frame (head turn, gaze, blinks, 21 expressions plus neutral, mouth shapes and lip sync, hair and accessory physics). No dedicated modeling software is needed.

- **Run**: Python 3.8+ and Chrome or Edge. Double-click `start.bat` (Windows), or run `./start.sh` / `python tools/serve.py`. The bundled model is `kurage02`.
- **OBS**: add a Browser source with `http://127.0.0.1:8770/index.html?model=kurage02&ui=0&bg=transparent` while the server is running.
- **Make your own character**: `partsgen/` builds a model from a single character image and a name, using an image-generating Codex CLI, Real-ESRGAN (fetched by one setup command) and an AI coding agent driven by `partsgen/MASTER_PROMPT.md`. Documentation is in Japanese. Tested on Windows only.
- **License**: MIT, including the bundled `kurage02` model and its images. The bundled MediaPipe files in `vendor/mediapipe/` are Apache License 2.0. Third-party notices are in `THIRD_PARTY_NOTICES.md`.
