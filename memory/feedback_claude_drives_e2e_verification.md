---
name: claude-drives-e2e-verification
description: e2e 検証の実行主体は Claude。host-agent 経由で Resonite を自動駆動するのが基本で、manual 手順書はユーザが読まない前提で書き起こさない。
metadata:
  type: feedback
---

e2e 検証は **Claude 自身が `scripts/resonite_cli.py` (host-agent bridge) を使って実行する** のが基本路線。`just resonite-start` / `resonite-stop` / `resonite-status` / `resonite-screenshot` で container 内から host の Resonite を起動・停止・撮影できるので、Claude が `python/tests/e2e/` 配下の harness を回しきって検証を完結させる。

**Why:** 当初は「manual テストはユーザが Resonite UI を見て確認する手順書」として `mod/tests/manual/*.md` を各モダリティ実装時に量産していたが、ユーザは実際にはそれらを読んでも実行してもいない。書いた本人が読まない手順書は「verify した既成事実だけ残る最悪の状態」で、価値が逆にマイナス。ユーザ自身からも 2026-05-27 のセッションで「Claude が e2e で検証まで通すのが基本」「manual テストを実行すること自体を最小化していく」と明示的にフィードバックがあった。

**How to apply:**

- 新規モダリティ / 新規機能の検証は、まず Claude が host-agent 経由で回せる自動 e2e (`python/tests/e2e/<modality>.py` 形式) として書く
- `mod/tests/manual/*.md` を新規追加するのは **本質的に人間しかできない確認** (例: Resonite Settings UI でデバイス手動切替、複数ユーザ間の voice 通話受信確認、視覚/聴覚的な品質判断) に限定する
- 既存の manual 手順書も同じ基準で取捨選択。Claude が自動化可能な内容なら e2e に巻き取って manual md は削除、参照側 (README / resonite_io_plan / memory / skill / agent doc / e2e test docstring) もまとめてクリーンアップする
- [/testing-strategy skill](../.claude/skills/testing-strategy/SKILL.md) の "manual / e2e" 区分の説明も、この方針 (manual は最後の手段) を反映するよう更新候補

関連: \[\[reference-load-bearing-whys\]\] (load-bearing why コメント), \[\[feedback-microphone-engine-tap\]\] (mic UI 手動切替が manual に残った例)
