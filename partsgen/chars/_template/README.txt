新しいキャラの出発点。このフォルダを chars/<キャラ名>/ へ写して使う（キャラ名は英数字。モデル名にもなる）。
char.json の _todo に、置き直す項目と、どの段階で決めるかが書いてある。置き直したら _todo から消す。

prompts/（このフォルダには無い。chars/<キャラ名>/prompts/ を作って書く）:
  - 自分で書く物: prompt_00・01・03・03b・04・11（あるキャラは 05・12・13）、hair_key.txt、hair_design_front.txt・hair_design_back.txt。
    chars/kurage02/prompts の同じ名前の物を手本に、このキャラの髪型・服・飾りの言葉で書く（WORKFLOW.md の「絵の番号」と「髪」の章）。
  - prompt_00（元の絵 1 枚 → 正面の基準画像）の手本は、chars/kurage02/prompts/prompt_00_example.txt。
    kurage02 の prompt_00.txt は、承認済みの正面の絵（front.png）も渡す特別な形（char.json の job_inputs）なので、そのまま手本にしない。
  - hair_key.txt・hair_design_*.txt は、保存する名前を {OUT}.png と書く（道具が、key_1・design_front などに置き換える）。
  - 書かなくてよい物: 20〜36（顔のパーツ・表情差分）と 61〜68（キーの形のシート）は、partsgen/tools/codex の共通の指示文が自動で使われる。
    キャラ特有の事情（眼帯、ケモ耳、顔の印など）を書き足すときだけ、同じ番号の prompt_<番号>.txt を置く（そちらが優先される）。

中身は、今の作り方（kurage02 と同じ。目と口はキーの形、向きの上限は広く）の値:
  - tune: 向きの上限 30・16・28・25、lash・browBounce・faceFit・mouthFit・eyeFit・headTilt が 1
  - params.browShow、browAmp、lashOver 0、lidShadow
  - extras.jobs の 61〜68（キーの形のシート。範囲 box は kurage02 の値なので、段階 5c で必ず置き直す）
  - hair（box・whorl・center_x などは kurage02 の値。back の box は段階 2、ほかは段階 5b で置き直す）
値は kurage02 の char.json から写した。このひな形と MASTER_PROMPT.md で、開発中に 2 体を通している。
