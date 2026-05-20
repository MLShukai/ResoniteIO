# Memory Index — spec-driven-implementer

implementer 固有の作業ノウハウ。project-wide 価値のある feedback は
[.claude/memory/](../../memory/) に昇格済みなのでそちらを参照。

## Feedback

- [check HEAD before implementing](feedback_check_head_before_implementing.md) — On a feature branch matching the task name, verify prior commits haven't already landed the work before re-implementing.
- [pre-commit stash で staged 内容が消える事象](feedback_precommit_stash_silent_unstage.md) — 並列 worktree で pre-commit 経路が "Skipped" 連発 + exit 1 を返した場合、`git status` で再 stage して再 commit する。
- [Engine.OnShutdown subscription deferred to Step 3](feedback_engine_onshutdown_deferred.md) — mod 停止は AppDomain.ProcessExit best-effort。Engine.OnShutdown 経由のより早い hook 調査は Step 3 で再評価。
- [uv tool install resoio version skew](feedback_uv_tool_install_resoio.md) — `uv tool install --editable` ignores uv.lock; isolated env picks betterproto2 0.10 against compiler 0.9 stubs and ImportErrors.
- [asyncio add_reader テストの key pacing](feedback_asyncio_add_reader_test_pacing.md) — os.pipe stdin + add_reader 駆動 CLI の round-trip テストは keystroke を `asyncio.sleep` で pace しないと exit key が drain される。
