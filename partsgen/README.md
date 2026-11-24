# 新しいキャラを作る（partsgen）

キャラクターの絵 1 枚から、Keshin2D で動かせるモデル（`models/<キャラ名>/`）を作る道具と手順書です。

画像生成（Codex CLI）に、パーツごとに清書した絵を描かせます。描かせる絵は、基準の絵、髪なしの絵、髪の房、目と口の差分シートなどです。
それを同梱の道具で切り出し、位置を合わせ、キーの形（目と口の変形）にして、モデルとして書き出します。
作業の数が多い（描かせる絵が 40〜50 枚、確認の撮影が何十回も）ので、**AI のコーディングエージェントに、指示文（`MASTER_PROMPT.md`）を渡して進めさせる**前提です。

| 文書 | 中身 |
|---|---|
| この文書 | 要るもの・準備・流れ・人が決めること |
| `MASTER_PROMPT.md` | エージェントに渡す指示文 |
| `WORKFLOW.md` | 手順の全部（段階 0〜8、`char.json` の項目、章ごとの落とし穴） |
| `KNOWHOW.md` | 品質の基準、確認のしかた、失敗と直し方 |
| `UPSCALER.md` | 拡大に使う Real-ESRGAN の用意 |
| `chars/kurage02/` | 手本のキャラの設定（`char.json`）と、画像生成への指示文（`prompts/`） |
| `chars/_template/` | 新しいキャラの出発点 |

## 要るもの

| もの | 用途 | 入手 |
|---|---|---|
| Python 3.10 以上 | 切り出し・書き出し | <https://www.python.org/downloads/>（3.10・3.12 で確かめた） |
| Node.js 22 以上 | 確認の撮影（ヘッドレスのブラウザを動かす） | <https://nodejs.org/> |
| Google Chrome か Microsoft Edge | 確認の撮影と、動かして見る画面 | 見つからなければ、環境変数 `AVATAR_CHROME` に実行ファイルを指定 |
| Codex CLI（画像生成ができるもの） | 絵を描かせる | 下の「Codex CLI の用意」 |
| Real-ESRGAN（`realesrgan-ncnn-vulkan`） | 絵を 3 倍に拡大 | 下の「準備」のコマンドで、自動で取ってこられる（約 50MB）。Vulkan に対応した GPU が要る。くわしくは `UPSCALER.md` |
| AI のコーディングエージェント | 作業を進めさせる | ファイルの読み書き・コマンドの実行・画像を見ることができるもの（Claude Code など） |

**道具は Windows で作り、確かめています。** ほかの OS では確かめていません。

### Codex CLI の用意

- OpenAI の Codex を入れて、ログインします（入れ方とログインは、OpenAI の Codex の案内に従ってください）。利用には OpenAI の契約が要り、描かせた枚数に応じて使用量がかかります。
- 道具は、`codex exec` に、絵と指示文を渡して「画像生成ツールで描いて、作業フォルダに保存して」と頼みます。**画像生成が使える Codex が要ります。**
- 作った時点（2026 年 11 月）で動いたのは、**Windows の Codex アプリに同梱の `codex.exe`**（`%LOCALAPPDATA%\OpenAI\Codex\bin\<ハッシュ>\codex.exe`。道具が自動で探します）。npm で入れた版と `~/.local/bin` の版は、画像生成が動きませんでした（Codex の版によって変わりえます）。macOS・Linux で描けるかは、確かめていません。
- 別の場所の Codex を使うときは、環境変数 `CODEX_EXE` に実行ファイルを指定します。
- `pipeline.py check` は、Codex が起動できるか（`codex --version`）までしか確かめません。**画像生成が使えるかは、最初に描かせる段階（段階 1 の `draw … 00`）で分かります。** 描けずに止まったら、作業フォルダの `_jobs/j00/out.txt`（Codex の記録）を見てください。

### 作業フォルダ

- 描かせた絵・拡大した絵・確認の撮影は、リポジトリの外の「作業フォルダ」に置きます。既定は `%LOCALAPPDATA%\keshin2d_work\<キャラ名>`（Windows 以外は `~/keshin2d_work/<キャラ名>`）。キャラ 1 体で、数百 MB〜数 GB になります。
- 絵を読む部品（OpenCV）と Real-ESRGAN が、日本語を含むパスを読めないので、作業フォルダは英数字だけのパスにします。**Windows のユーザー名が日本語の PC では、道具が、英数字だけの別の場所（`C:\Users\Public\keshin2d_work` など）を自動で選びます。** どこが使われるかは、`pipeline.py check` に出ます。
- 自分で場所を決めるときは、環境変数 `KESHIN2D_WORK` に、英数字だけのパスのフォルダを指定します。
- リポジトリそのものは、日本語や空白を含むパスに置いてもかまいません。

## 準備

リポジトリのいちばん上のフォルダで、次の 3 つを行います（Python・Node.js・Chrome か Edge・Codex CLI は、先に入れておきます）。

1. Python の仮の環境（`.venv`）を作って、ライブラリを入れる
2. Real-ESRGAN を取ってくる（配布元の GitHub から約 50MB。作業フォルダの置き場所に置かれます。手で置くときは `UPSCALER.md`）
3. そろっているかを確かめる（足りない物と、入れ方が出ます）

Windows（コマンドプロンプト・PowerShell）:

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r tools\requirements.txt
.venv\Scripts\python -I partsgen\tools\pipeline.py install-upscaler
.venv\Scripts\python -I partsgen\tools\pipeline.py check
```

macOS・Linux（と、Windows の Git Bash）:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r tools/requirements.txt          # Git Bash では ./.venv/Scripts/python
./.venv/bin/python -I partsgen/tools/pipeline.py install-upscaler
./.venv/bin/python -I partsgen/tools/pipeline.py check
```

手順書（`WORKFLOW.md`）のコマンドは、`./.venv/Scripts/python.exe …` の形で、bash（Windows では Git Bash）の書き方で書いてあります（PowerShell では、変数の書き方が違います）。

`check` が全部 ok になったら、エージェントを、リポジトリのいちばん上のフォルダで開き、`MASTER_PROMPT.md` の「ここから」〜「ここまで」を貼って、**画像の場所とキャラ名の 2 行だけ**を書き換えて渡します。あとは、エージェントが、止まる所（下の表）で確かめながら進めます。

## 流れと、人が決めること

| 段階 | 内容 | 人がすること |
|---|---|---|
| 0〜1 | 元の絵を観察し、基準の絵（正面・腰から上）と、髪なしの絵を描かせる | **【止まる所 1】** 基準の絵が、そのキャラに見えるかを確かめる |
| 2 | 髪・体の絵と、髪のキービジュアル 2 案 | **【止まる所 1b】** 髪の案を選ぶ |
| 3〜6 | 拡大、顔の位置出し、顔のパーツの清書、目と口のキーの形、髪の房、モデルの書き出し、揺れ物 | （待つ間に進む） |
| 7 | 動かして確認（9 方向・表情・目と口の拡大・動きの段・実際の時間の録画・揺れ物の揺れ・付いている物の付け根） | **【止まる所 2】** 自分で動かして見る。気になる所を伝える |
| 8 | 仕上げ | 画面の「キャラを作る人向け」→「今の調整値を書き出す」で出した値を渡すと、モデルの初期値になる |

止まる所 2 では、`start_<キャラ名>.bat`（または `start.bat --model <キャラ名>`）で開いて、次を見てください:
「おまかせ」（ひとり芝居）、表情のボタン、口パクデモ、「好みに合わせる」の中（動きの好みと飾りの揺れ、向きの上限 = 9 方向のボタン、母音の口の大きさ、マイクの口パク）。
顔を大きく振ったとき・うなずいたときの、頭の上の毛や耳の飾りの揺れ方、飾りの付け根、上下いっぱいを向いたときの目のまわりも、見てください。
止めた絵では分からない崩れは、どのキャラでも、ここで見つかりました。気になった所は、感じたままの言葉で伝えれば足ります（「紙のようにぺらぺらしている」「耳に通っていない感じがする」のような言葉から、エージェントが、原因を調べて直します）。

## できたもの

- モデル: `models/<キャラ名>/`（`model.json` と `parts/*.png`）。このフォルダを、ほかの Keshin2D の `models/` に置けば動きます。
- 自分で作ったモデル・設定・起動用の bat（`models/<キャラ名>/`・`partsgen/chars/<キャラ名>/`・`start_<キャラ名>.bat`）は、`.gitignore` で git に入らないようにしてあります（このリポジトリを fork して公開しても、うっかり入らないように）。入れるときは `git add -f`。
- 起動: `start_<キャラ名>.bat`（Windows）。どの OS でも `python tools/serve.py --model <キャラ名>`。
- 設定と指示文: `partsgen/chars/<キャラ名>/`。作業フォルダ（既定 `%LOCALAPPDATA%\keshin2d_work\<キャラ名>`。上の「作業フォルダ」）は、作り直しに使うので消さずに残してください。
- 同梱の `kurage02` は、モデル（`models/kurage02/`）と設定・指示文（`chars/kurage02/`）だけを入れてあります。元の絵と、描かせた絵（作業フォルダの中身）は入れていないので、`kurage02` を、このリポジトリだけから作り直すことはできません（設定と指示文の書き方の手本として使います）。

## 絵の権利について

- 元にする絵は、自分が権利を持つ絵か、使う許可を得た絵にしてください。
- 画像生成で描かせた絵の扱いは、使ったサービスの利用規約に従います。
- 同梱の `kurage02`（モデル・設定・指示文）は、プログラムと同じ MIT です。手本にしても、そのまま使ってもかまいません。
