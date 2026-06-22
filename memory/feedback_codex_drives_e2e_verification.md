---
name: codex-drives-e2e-verification
description: e2e 検証は agent (Codex/Claude) が container 内で Resonite を自動駆動して完結させる。可否を問う前に pgrep で起動状態を確認する。manual 手順書はユーザが読まない前提で量産しない。
metadata:
  type: feedback
---

e2e 検証は **agent 自身が container 内の Resonite を起動して実行する** のが基本路線。`just resonite-launch` / `resonite-stop` (= `resoio launch` / `resoio terminate`、`python/src/resoio/launcher.py`) で devcontainer 内の mod 込み Resonite を起動・停止でき、起動状態は `pgrep -af Renderite.Renderer.exe` で確認できる。Resonite 画面の screenshot は in-engine Camera v2 (`resoio screenshot -o foo.png` = `CameraClient.shot()`) で取れる (host-agent 経由の desktop 全体 pyscreenshot bridge は撤去済み)。agent が `python/tests/e2e/` 配下の harness を回しきって検証を完結させる。

**Why:** 当初は「manual テストはユーザが Resonite UI を見て確認する手順書」として `mod/tests/manual/*.md` を各モダリティ実装時に量産していたが、ユーザは実際にはそれらを読んでも実行してもいない。書いた本人が読まない手順書は「verify した既成事実だけ残る最悪の状態」で価値が逆にマイナス。ユーザからも「agent が e2e で検証まで通すのが基本」「manual テストを実行すること自体を最小化していく」と明示フィードバックがあった (2026-05-27)。「Resonite 起動してますか?」「立ち上げてくれますか?」と毎回問うのも冗長 — 起動状態は機械的に判定できる。

**How to apply:**

- e2e の可否をユーザーに問う前に、まず `pgrep -af Renderite.Renderer.exe` で起動状態を確認する。動いていれば既存インスタンスで進め、無ければ `just deploy-mod` → `just resonite-launch` で起動して進める (起動可否を問い直さない、container 内で完結する)。
- 新規モダリティ / 新規機能の検証は、まず agent が container 内で回せる自動 e2e (`python/tests/e2e/<modality>.py` 形式) として書く。
- `mod/tests/manual/*.md` を新規追加するのは **本質的に人間しかできない確認** (Resonite Settings UI のデバイス手動切替、複数ユーザ間の voice 通話受信確認、視覚/聴覚的な品質判断) に限定する。
- 既存の manual 手順書も同じ基準で取捨選択。自動化可能なら e2e に巻き取って manual md は削除し、参照側 (README / memory / skill / agent doc / e2e test docstring) もまとめてクリーンアップする。
- [/testing-strategy skill](../.claude/skills/testing-strategy/SKILL.md) の "manual / e2e" 区分の説明もこの方針 (manual は最後の手段) を反映する。

関連: \[\[reference-load-bearing-whys\]\] (load-bearing why コメント), \[\[feedback-microphone-engine-tap\]\] (mic UI 手動切替が manual に残った例), \[\[feedback_e2e_single_signin_per_boot\]\] (e2e safety 制約)
