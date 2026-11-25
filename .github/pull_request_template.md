## 変更の内容 / Summary

<!-- 何を、なぜ変えたか / What changed and why -->

関連する Issue / Related issue: #

## 確認したこと / Checklist

- [ ] `python tools/check_repo.py` が全項目合格した / `python tools/check_repo.py` passes every check
- [ ] ビューアやエンジンを変えた場合、`uicheck.mjs` が kurage02・chiwa とも全部 ok だった / For viewer or engine changes, `uicheck.mjs` is all ok for both kurage02 and chiwa
- [ ] エンジンの動きを変えた場合、同梱の 2 体を、変える前とあとで撮って比べた / For motion changes, shot the bundled models before and after and compared them
- [ ] `vendor/` の中を変えていない / Nothing under `vendor/` is changed
- [ ] 文書を変えた場合、日本語版と英語版をそろえた（どちらか一方でも可） / Kept Japanese and English docs in step (one language is fine)
- [ ] 新しいキャラクター（モデル）の追加・同梱モデルの絵の変更を含まない / No new characters and no changes to the bundled artwork
- [ ] 送った内容が MIT License で公開されることに同意する / I agree that this contribution is published under the MIT License
