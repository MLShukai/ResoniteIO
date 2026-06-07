# Agent Memory Index — spec-driven-implementer

- [ContextMenu modality](project_context_menu_modality.md) — unary modality mirroring Display; reflection-driven Open
- [FrooxEngine ContextMenu reflection](froox_contextmenu_reflection.md) — private OpenContextMenu/MenuOptions signatures + ContextMenuItem API gotchas
- [GrpcHost modality wiring](feedback_sessionhost_modality_wiring.md) — the 4-5 edit points to register a new modality in GrpcHost.cs
- [API contract test pins __all__](feedback_api_contract_test.md) — new Python export breaks test_api_contract.py until spec-test-author updates expected tuple
- [Core API contract pin](project_core_api_contract_pin.md) — new public type in ResoniteIO.Core.\* breaks ApiContractTests exported-types snapshot; make shared helpers internal
- [Dash + UIX engine API shapes](reference_dash_uix_engine_api.md) — verified FrooxEngine call shapes for the Dash Mod bridge (UserspaceRadiantDash, RectTransform, Button/ScrollRect, RefID resolution, LocaleStringDriver.Key)
- [check HEAD before implementing](feedback_check_head_before_implementing.md) — On a feature branch matching the task name, verify prior commits haven't already landed the work before re-implementing
- [pre-commit stash で staged 内容が消える](feedback_precommit_stash_silent_unstage.md) — 並列 worktree で pre-commit が "Skipped" 連発 + exit 1 を返したら `git status` で再 stage して再 commit する
- [Engine.OnShutdown subscription deferred](feedback_engine_onshutdown_deferred.md) — mod 停止は AppDomain.ProcessExit best-effort。より早い hook 調査は Step 3 で再評価 (歴史的メモ、Step 3 は完了済み)
- [uv tool install resoio version skew](feedback_uv_tool_install_resoio.md) — `uv tool install --editable` は uv.lock を無視し、betterproto2 0.10 を compiler 0.9 stub に当てて ImportError
- [asyncio add_reader テストの key pacing](feedback_asyncio_add_reader_test_pacing.md) — os.pipe stdin + add_reader 駆動 CLI の round-trip テストは keystroke を `asyncio.sleep` で pace する
- [PyAV mp4 video dims before audio mux](feedback_pyav_mp4_video_dims_before_audio_mux.md) — muxed mp4 (H.264+AAC) では audio pump が video pump の width/height 設定を待つ必要がある
- [World modality (Python)](project_world_modality_python.md) — world.py/cli shape + wire/public enum offset-mapping gotcha
- [SkyFrost cloud bridge refs](project_skyfrost_cloud_bridge_refs.md) — cloud/record を触る Mod Bridge は SkyFrost.Base / SkyFrost.Base.Models / FrooxEngine.Store を csproj に明示参照
