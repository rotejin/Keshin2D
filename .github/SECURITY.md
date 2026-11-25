# セキュリティポリシー / Security Policy

## 対象のバージョン

最新のリリースと `main` ブランチを対象に修正します。

## 脆弱性の報告

**脆弱性の詳しい内容を、公開の Issue に書かないでください。**

このリポジトリの **Security** タブ → **Report a vulnerability** から、非公開で報告してください（GitHub の Private vulnerability reporting）。

この方法が使えない場合は、作者の X（[@rotejin](https://x.com/rotejin)）に DM で連絡してください。

書いてほしいこと:

- 影響のあるファイルや機能
- 再現の手順
- 期待した動作と、実際の動作
- OS と、ブラウザのバージョン
- 安全に共有できるなら、再現に使うファイル

## この仕組みの作り（安全面）

### ビューア（`index.html`・`js/`）

- **外へ通信しません。** 読み込むのは、同じ場所に置いたファイル（`js/`・`models/`・`vendor/`）だけです。外の CDN は使いません。
- **Web カメラ**の映像は、ブラウザの中で、同梱の MediaPipe（`vendor/mediapipe/`。手を加えていない物。チェックサムは `vendor/mediapipe/SHASUMS256.txt`）が顔の向きを調べるためだけに使います。録画・保存・送信はしません。「カメラ」を押したときだけ、ブラウザが許可を求めます。
- **マイク**の音は、ブラウザの中で、音の大きさと母音を調べるためだけに使います。録音・保存・送信はしません。
- 保存するのは、ブラウザの保存領域（localStorage）に入る、調整した値と配置だけです。
- URL の `model=` に使えるのは、英数字・`_`・`-` だけです（`models/` の外のフォルダは開けません）。

### 表示用のサーバー（`tools/serve.py`）

- Python の標準ライブラリだけで動きます。**この PC の中（127.0.0.1）からだけ**つながります。ほかの PC からは開けません。
- リポジトリのフォルダの中のファイルを、読み出すだけです（書き込み・実行はしません）。
- 実行ファイルは同梱していません。`start.bat`・`start.sh` は、PC に入っている Python で `tools/serve.py` を起動するだけです。

### キャラを作る道具（`partsgen/`）

ビューアを使うだけなら、動きません。新しいキャラを作るときに、手元で実行する道具です。

- `pipeline.py install-upscaler` は、Real-ESRGAN を、配布元（GitHub の `xinntao/Real-ESRGAN` のリリース）から取ってきます。
- 絵を描かせるときは、PC に入っている Codex CLI を起動して、元の絵と指示文を渡します（通信するのは Codex CLI で、OpenAI の利用規約に従います）。
- 確認の撮影は、PC に入っている Chrome か Edge を、専用のプロファイル（作業フォルダの中）で、画面を出さずに起動します。ふだん使っているブラウザのプロファイルは使いません。
- 描かせた絵や確認の撮影は、リポジトリの外の作業フォルダに置きます。

## English

Please do not post vulnerability details in public issues. Use **Security → Report a vulnerability** (GitHub private vulnerability reporting) in this repository. If that is not possible, send a direct message to [@rotejin](https://x.com/rotejin) on X.

The viewer makes no outside network connections: it loads only files served from the same place (`js/`, `models/`, `vendor/`), and uses no CDN. Webcam frames are used only inside the browser, by the bundled, unmodified MediaPipe files, to estimate head pose; microphone audio is used only inside the browser for volume and vowel detection. Neither is recorded, stored or uploaded. Only tuning values and the view position are saved, in the browser's localStorage. `tools/serve.py` uses only the Python standard library, listens on 127.0.0.1 only and serves the repository folder read-only. No executables are bundled. The character tools in `partsgen/` run only when you make a new character: they can download Real-ESRGAN from its GitHub releases, start the Codex CLI installed on your PC, and start headless Chrome or Edge with a dedicated profile.
