# 拡大（3 倍）に使う Real-ESRGAN の用意

描かせた絵（1024×1536）を 3 倍（3072×4608）にする段階は、`partsgen/tools/upscale.py` が Real-ESRGAN を呼んで行う。
Photoshop は要らない。

## 何をしているか

1. Real-ESRGAN（`realesrgan-ncnn-vulkan`、モデル `realesrgan-x4plus-anime`）で 4 倍にする。
2. Lanczos で 3 倍の大きさへ縮める。
3. 透過のある絵は、色と不透明度を別々に拡大して合わせる。透明な画素の色は、先に近くの色で埋めておく（ふちに黒や白がにじまないように）。

タイルの大きさは 128（GPU のメモリが少なくても動くように）。

## 用意するもの

- Vulkan に対応した GPU（内蔵 GPU でも動く）。
- `realesrgan-ncnn-vulkan` の実行ファイルとモデル。

### 自動で取ってくる（勧める）

```bash
./.venv/Scripts/python -I partsgen/tools/pipeline.py install-upscaler      # Windows 以外は ./.venv/bin/python
```

- 配布元（GitHub の `xinntao/Real-ESRGAN` の v0.2.5.0）から、その OS 用の zip（約 45〜52MB）を取ってきて、チェックサム（SHA-256）を確かめ、使う物だけ（実行ファイル・その DLL・モデル `realesrgan-x4plus-anime`）を、作業フォルダの置き場所の `_tools/realesrgan-ncnn-vulkan` に置く（既定は `%LOCALAPPDATA%\keshin2d_work\_tools\…`。リポジトリの中には置かない）。
- チェックサムは、2026-11-24 に取ってきた物の値を `partsgen/tools/upscale.py` に控えてある。違っていたら、置かずに止まる（そのときは、下の「手で置く」）。
- **Windows 用で確かめた。macOS・Linux 用は、zip の中身とチェックサムまでは確かめたが、動かしてはいない。**

### 手で置く

次の形のフォルダにする。

```text
realesrgan-ncnn-vulkan/
  realesrgan-ncnn-vulkan.exe      （Windows 以外は realesrgan-ncnn-vulkan）
  models/
    realesrgan-x4plus-anime.bin
    realesrgan-x4plus-anime.param
```

入手先: <https://github.com/xinntao/Real-ESRGAN/releases> の v0.2.5.0 にある `realesrgan-ncnn-vulkan-20220424-<OS>.zip`。
展開して `models/realesrgan-x4plus-anime.bin`・`.param` が無ければ、`upscale.py` が「見つかりません」と止まるので、モデルを別に入手して置く。
**Windows 用で確かめた。ほかの OS 用は確かめていない。**

## 場所の教え方

`upscale.py` は次の順で探す。

1. 環境変数 `REALESRGAN_ROOT`
2. `partsgen/upscaler.json` の `"root"`（`upscaler.example.json` を写して、自分の PC の場所に書き換える。PC ごとの物なので、git には入れない。`.gitignore` 済み）
3. `partsgen/vendor/realesrgan-ncnn-vulkan`（ここに置いてもよい。`.gitignore` 済み）
4. 作業フォルダの置き場所の `_tools/realesrgan-ncnn-vulkan`（`install-upscaler` が置く場所）

手で置くときは、**英数字だけのパス**にする（日本語を含むパスでは、読めないことがある）。拡大のときの一時ファイルは、道具が、英数字だけのパスに作る。

置いたら、`./.venv/Scripts/python -I partsgen/tools/pipeline.py check` で「Real-ESRGAN: ...」の行が ok になることを確かめる（Windows 以外は `./.venv/bin/python`）。

## 使い方

```bash
./.venv/Scripts/python -I partsgen/tools/upscale.py <絵 or フォルダ>...   # <名前>_3x.png を同じ場所に書く
./.venv/Scripts/python -I partsgen/tools/pipeline.py upscale <キャラ名>    # 作業フォルダの絵をまとめて
```

10 枚で約 1 分半（作った PC での目安。透過のある絵は 2 回推論する）。

## ライセンス（同梱していない。各自で入手する）

このリポジトリには、Real-ESRGAN の実行ファイルもモデルも入れていない。入手したものは、それぞれのライセンスに従う。

| もの | 作者 | ライセンス |
|---|---|---|
| Real-ESRGAN（学習済みモデル `realesrgan-x4plus-anime` を含む） | Xintao Wang ほか | BSD 3-Clause |
| Real-ESRGAN-ncnn-vulkan（実行ファイル） | Xintao Wang ほか | MIT |
| ncnn（実行ファイルが使う推論ライブラリ） | Tencent | BSD 3-Clause |

- ライセンスの種類は、2026-11-20 に各リポジトリの `LICENSE` を読んで確かめた（Real-ESRGAN: "BSD 3-Clause License / Copyright (c) 2021, Xintao Wang"、Real-ESRGAN-ncnn-vulkan: "The MIT License (MIT) / Copyright (c) 2021 Xintao Wang"。後者には、もとになった realsr-ncnn-vulkan（Copyright (c) 2019 nihui、MIT）の文も入っている。ncnn は本体が BSD 3-Clause で、中に含む第三者の部品は zlib・BSD 2-Clause・BSD 3-Clause）。
- どれも、著作権表示とライセンス文を付ければ再配布できる種類。実行ファイルやモデルを同梱して配るときは、その 3 つのライセンス文を一緒に入れる。
- 拡大した絵そのものに、これらのライセンスは及ばない。

## 拡大方法を変えたとき

- Photoshop で拡大した絵と比べると、Real-ESRGAN は線がくっきり出る（髪・瞳の細部がはっきりする）。輪郭線の色が少し赤く、細くなる。まつげの先に細い赤い線が出ることがある。
- 色の条件（`char.json`）は、使った拡大方法の絵に合わせて置く。拡大方法を変えたら、段階 4 の確認（目の確認シート）をやり直す。
