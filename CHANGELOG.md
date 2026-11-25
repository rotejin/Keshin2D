# 変更履歴 / Changelog

このプロジェクトの主な変更を記録します。
All notable changes to this project are recorded here.

## [0.1.0] - 2026-11-25

最初の公開版です。 / First public release.

### ビューア

- キャラクターの絵を、ブラウザ（WebGL2）で動かす 2D アバター。顔の向き・視線・まばたき・表情 22 個・口・髪と飾りの揺れ。
- 動かし方は 3 つ: マウス、Web カメラ（同梱の MediaPipe。インターネットなしで動く）、おまかせ（約 14 秒のひとり芝居）。
- マイクの口パク（声の母音で、口の形が変わる）と、口パクデモ。
- 操作パネルは 3 層（ふだんの画面・好みに合わせる・キャラを作る人向け）。パネルの上の欄で、モデルを切り替える。
- OBS のブラウザソース用の URL（透過・パネルなし・調整した値つき）。
- 外への通信なし。調整した値は、ブラウザに保存する。
- 起動は `start.bat`・`start.sh`・`python tools/serve.py`（Python の標準ライブラリだけ）。ファイルを置くだけの場所（GitHub Pages など）でも動く。

### 同梱のモデル

- クラゲちゃん（`kurage02`）と、チワちゃん（`chiwa`）。どちらも MIT License。
- チワちゃんは、絵 1 枚から、このリポジトリの道具と手順で、最後まで通して作ったモデル（記録は `partsgen/chars/chiwa/NOTES.md`）。

### キャラを作る道具（partsgen）

- キャラクターの絵 1 枚から、画像生成（Codex CLI）と道具で、モデルを作る手順書・指示文・道具（Windows で確かめた）。
- 目と口を、描かせた差分シートから「キーの形」にして動かす作り。髪を、大きな房のパーツで揺らす作り。飾り・帽子・動物の耳などの揺れ物。
- 確かめる道具: 画面の操作の自動確認（40 項目）、決まった姿勢の撮影と画素での比較、実際の時間の録画、揺れの回数を数える道具。

### 文書と検証

- README（日本語・英語）、新しいキャラを作る手順書（日本語）、AI のコーディングエージェント向けの手引き（`AGENTS.md`）。
- セキュリティポリシー、サポート、開発への参加の案内、Issue と Pull Request のテンプレート。
- リポジトリの検査（`tools/check_repo.py`）と、GitHub Actions での自動検査。

### English

- A 2D avatar that runs in the browser (WebGL2): head turn, gaze, blinks, 22 expressions, mouth shapes, hair and accessory physics.
- Three ways to drive it: the mouse, a webcam (bundled MediaPipe, works offline) and a scripted idle act. Microphone lip sync that picks mouth shapes from vowels.
- A three-level control panel, a model selector, and a URL for an OBS browser source. No outside network access; tuning values stay in the browser.
- Starts with `start.bat`, `start.sh` or `python tools/serve.py` (Python standard library only), and also runs from static hosting such as GitHub Pages.
- Bundled models: kurage02 and chiwa, both under the MIT License. chiwa was built end to end from a single character image with the tools in this repository.
- `partsgen/`: tools, a workflow and an agent prompt for building a model from a single character image with an image-generating Codex CLI (documentation in Japanese; tested on Windows).
- Japanese and English READMEs, a guide for coding agents (`AGENTS.md`), security, support and contributing guides, issue and pull request templates.
- Repository checks (`tools/check_repo.py`) and CI on GitHub Actions.

[0.1.0]: https://github.com/rotejin/Keshin2D/releases/tag/v0.1.0
