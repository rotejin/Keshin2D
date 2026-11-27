# 使わせてもらっている物 / Third-Party Notices

このリポジトリの物は、下に挙げた物のほかは、どれも MIT License（[LICENSE](LICENSE)）です。同梱のモデル `kurage02`・`chiwa`（`models/kurage02/`・`models/chiwa/` の絵と `model.json`）と、`docs/images/` の絵も含みます。

Everything in this repository other than the items listed below is under the MIT License ([LICENSE](LICENSE)), including the bundled `kurage02` and `chiwa` models (the images and `model.json` in `models/kurage02/` and `models/chiwa/`) and the images in `docs/images/`.

## このリポジトリに入っている物 / Included in this repository

### PuruPuru PNGTuber（瞳のぷるん）

- 元: https://github.com/rotejin/PuruPuruPNGTuber （Copyright 2026 masa）
- ライセンス: Apache License 2.0（全文は [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt)）
- 使った所: `js/avatar.js` の「瞳のぷるん」（まばたきのあとの伸び縮みの時間曲線、左右の目のずれ、うるみのゆらめき、まばたきの時間）。
  元の `app.js` の式と定数（`computeBounceXY`・`updateHighlightPulse`・`tearLensWarpPoint` の考え方）を、このエンジン向けに書き直して使っています。画像は使っていません。

The "iris bounce" in `js/avatar.js` (the post-blink squash-and-stretch curve, left/right eye offset, wet shimmer, and blink timing) is adapted from the formulas and constants in `app.js` of PuruPuru PNGTuber (Apache License 2.0). The code was rewritten for this engine; no images are used.

### MediaPipe Tasks Vision（Web カメラの顔の追跡）

- 提供: Google（https://github.com/google-ai-edge/mediapipe）
- ライセンス: Apache License 2.0（全文は [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt)。配布物の `package.json` の `"license": "Apache-2.0"`）
- 同梱した物（`vendor/mediapipe/`。手を加えていない。チェックサムは `vendor/mediapipe/SHASUMS256.txt`）:
  - `tasks-vision/0.10.14/`: npm の `@mediapipe/tasks-vision@0.10.14` の `vision_bundle.mjs`（と `.map`）、`wasm/`
  - `face_landmarker/float16/1/face_landmarker.task`: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
- 画面で「Web カメラ」を押したときだけ読み込みます。顔の追跡はブラウザの中で行い、カメラの映像は送りません。

MediaPipe Tasks Vision 0.10.14 (Apache License 2.0, by Google) and the Face Landmarker model are bundled unmodified in `vendor/mediapipe/` (checksums in `SHASUMS256.txt`). They are loaded only when the "Web camera" mode is selected. Tracking runs in the browser; camera frames are not uploaded.

## 商標 / Trademarks

文書の中で、説明のために、ほかの製品の名前（Live2D・Photoshop・OBS など）を出しています。それぞれ、その権利者の商標または登録商標で、このプロジェクトは、どの権利者とも関係がありません。

Product names mentioned in the documents (such as Live2D, Photoshop, and OBS) are trademarks or registered trademarks of their respective owners. This project is not affiliated with any of them.

### Mochi2D（`.moc3` 形式の仕様参考 / `.moc3` format reference）

- 参考: https://github.com/waifucave/mochi2d （MIT License）
- `tools/cubism/moc3_writer.py` は、Mochi2D がクリーンルームで文書化した `.moc3` のバイナリ仕様を参考に、Python で一から実装した書き出し処理です。Mochi2D や Live2D Cubism SDK のコード・バイナリは同梱していません。

`tools/cubism/moc3_writer.py` is an independent Python writer implemented from scratch using the clean-room `.moc3` binary format specification documented by Mochi2D (MIT License). No code or binaries from Mochi2D or Live2D Cubism SDK are bundled.

## キャラを作る道具が使う物（同梱していません） / Used by the character tools (not bundled)

各自で入手して、それぞれのライセンス・利用規約に従って使ってください。

| もの | 用途 | 入手・ライセンス |
|---|---|---|
| Codex CLI（OpenAI） | 絵を描かせる（画像生成） | OpenAI の利用規約に従います |
| Real-ESRGAN（`realesrgan-ncnn-vulkan` とモデル `realesrgan-x4plus-anime`） | 絵を拡大する | [partsgen/UPSCALER.md](partsgen/UPSCALER.md)（`pipeline.py install-upscaler` が、使う人の PC へ、配布元から取ってくる。このリポジトリには入っていない） |
| NumPy・OpenCV（`opencv-python`）・Pillow | 絵の処理 | `pip` で入れます（それぞれ BSD・Apache 2.0・MIT-CMU 系のライセンス） |
| Node.js、Google Chrome / Microsoft Edge | 確認の撮影 | それぞれの配布元 |
