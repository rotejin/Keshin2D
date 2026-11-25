# 開発への参加 / Contributing

> English follows the Japanese.

不具合の報告や改善の提案を歓迎します。個人で作っているプロジェクトのため、返事や取り込みは できる範囲で行います。

## Issue

- 不具合・キャラクター作りの相談・要望は、[Issue のテンプレート](https://github.com/rotejin/Keshin2D/issues/new/choose) から書いてください（書いてほしいことは [SUPPORT.md](SUPPORT.md)）。
- 脆弱性は公開の Issue に書かず、[SECURITY.md](SECURITY.md) の方法で報告してください。

## Pull Request

大きな変更は、先に Issue で相談してください。小さな修正（誤字、文書の改善、明らかな不具合の修正）はそのまま送ってかまいません。

送る前に確かめてほしいこと:

- `python tools/check_repo.py` が全項目合格する（ファイルのそろい方・JSON・リンクなどの検査。標準ライブラリだけで動きます）。
- ビューアやエンジン（`index.html`・`js/`）を変えたら、`node partsgen/tools/uicheck.mjs kurage02 <出力フォルダ>` と `node partsgen/tools/uicheck.mjs chiwa <出力フォルダ>` が全部 ok になる（Node.js 22 以上と、Chrome か Edge が要ります）。
- エンジンの動きを変えたら、同梱の 2 体の見え方が変わっていないことを、変える前とあとで撮って比べる（`partsgen/tools/regress.py` の `shoot` と `compare`。くわしくは `partsgen/WORKFLOW.md` の「回帰テスト」）。**新しい動きは、モデルの設定に書いたときだけ効く項目にして、書かなければ前と同じ動きになるようにします。**
- `vendor/` の中は変えない（同梱した外部の物。チェックサムと合わなくなります）。
- 文書を変えたら、`README.md` と `README.en.md` の両方をそろえる。英語が難しければ、日本語だけで送ってもかまいません。

細かい決まりと落とし穴は [AGENTS.md](../AGENTS.md) にあります。キャラを作る道具（`partsgen/tools/`）の変更は、作者の手元で、同梱のモデルを書き出し直して確かめます（元の絵と、描かせた絵が要るため）。

## モデルと画像について

- **新しいキャラクター（モデル）を足す Pull Request は、受け付けていません。** 自分のキャラクターは、自分の手元や、自分のリポジトリで楽しんでください。
- **同梱のモデル（クラゲちゃん・チワちゃん）の絵を変える Pull Request も、受け付けていません。**
- 不具合の説明のためにスクリーンショットを添えるのはかまいません。他人のキャラクターや、使ってよいか分からない画像は含めないでください。

## ライセンス

送ってもらったコード・スクリプト・文書は、このリポジトリと同じ [MIT License](../LICENSE) で公開されます。

---

## English

Bug reports and suggestions are welcome. This is a personal project, so replies and merges are best-effort.

### Issues

- Use the [issue templates](https://github.com/rotejin/Keshin2D/issues/new/choose) for bugs, character-creation questions and feature requests ([SUPPORT.md](SUPPORT.md) lists what to include).
- Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md), not in public issues.

### Pull requests

Please open an issue first for larger changes. Small fixes (typos, documentation, obvious bugs) can be sent directly.

Before sending:

- `python tools/check_repo.py` passes every check (file layout, JSON, links; standard library only).
- If you changed the viewer or the engine (`index.html`, `js/`), `node partsgen/tools/uicheck.mjs kurage02 <output folder>` and the same for `chiwa` report all ok (needs Node.js 22+ and Chrome or Edge).
- If you changed how the engine moves things, shoot the two bundled models before and after and compare them (`shoot` and `compare` in `partsgen/tools/regress.py`). **New behaviour must be an opt-in setting in the model, so that models that do not set it look the same as before.**
- Nothing under `vendor/` is changed (bundled third-party files with checksums).
- Documentation changes keep `README.md` and `README.en.md` in step. If you cannot write Japanese, English only is fine.

Detailed rules and pitfalls are in [AGENTS.md](../AGENTS.md) (Japanese). Changes to the character tools in `partsgen/tools/` are verified by the author, who re-exports the bundled models (that needs the source images, which are not in the repository).

### Models and images

- **Pull requests that add new characters (models) are not accepted.** Enjoy your own characters locally or in your own repository.
- **Pull requests that change the artwork of the bundled models (kurage02, chiwa) are not accepted either.**
- Screenshots that explain a bug are fine. Do not include other people's characters or images you may not share.

### License

Code, scripts and documents you contribute are published under the same [MIT License](../LICENSE) as this repository.
