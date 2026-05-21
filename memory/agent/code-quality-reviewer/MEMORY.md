# Memory Index — code-quality-reviewer

レビュー観点で繰り返し確認している論点・プロジェクト固有のチェック方針。
project-wide な規約は `memory/` 側を参照し、ここには「レビュー時に
具体的に何を確認すべきか」「過去に発見した欠陥パターン」だけを残す。

## Reference

- [muxed-pipeline-review-checklist](reference_muxed_pipeline_review_checklist.md) — PyAV muxed (video+audio) 実装をレビューするときに必ず通す観点 7 つ。
- [pytest-k-filter-discoverability](reference_pytest_k_filter_discoverability.md) — テスト関数名に共通プレフィックスがないと `pytest -k <feature>` で全 case が collect されない問題。

## Feedback

- [skew-tolerance-needs-evidence](feedback_skew_tolerance_needs_evidence.md) — A/V sync などの quantitative threshold を spec から広げる場合、実測値を 1 行残す。
- [verify-regression-test-actually-fails](feedback_verify_regression_test_actually_fails.md) — implementer の「stash で fail 確認した」報告を信じず、修正を 1 行 disable して再現する。
