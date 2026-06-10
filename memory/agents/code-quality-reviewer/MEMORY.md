# Code Quality Reviewer — Memory Index

- [Froox in-param lvalue](reference_froox_in_param_lvalue.md) — FrooxEngine の `in` API に float3.Up 等の static property を直接渡せず、ローカル変数経由が必須 (CS8156)。Bridge の world/slot ローカルは冗長でない
- [Modality client RPC dedup](project_modality_client_dedup.md) — resoio Python client の繰り返し unary-RPC body を public API を変えず `_dispatch` ヘルパで畳む方針
- [Dispatch factoring pattern](project_dispatch_factoring_pattern.md) — `_dispatch` が同一戻り型 (ContextMenu) と複数戻り型 (Dash) で責務が異なるのは正しい適応。consistency 目的で「修正」しない
- [Dash action-result factories](project_dash_action_result_factories.md) — Dash Bridge の操作系で重複していた snapshot 生成を NotFound/Rejected/Succeeded factory 三点に畳む。best-effort 操作 Bridge の定石
- [World/modality Service translate pattern](feedback_world_service_translate_pattern.md) — per-RPC try/catch→Translate を private CallBridgeAsync で畳む。bridge の engine-dispatch helper も dedup。GrpcHost は触らない
- [World CLI surface pins](feedback_world_cli_surface_pins.md) — world.py/cli/world.py の pinned 表面 (Thumbnail/fetch_thumbnail/CLI flags/列/footer) と自由に触れる内部 helper の線引き
- [Manipulation: HandleAsync に統合しない](feedback_manipulation_service_no_handleasync.md) — RPC 形が違い Release/GetState は 2 回のみで dedup 閾値内。無理に共通化しない
- [muxed-pipeline review checklist](reference_muxed_pipeline_review_checklist.md) — PyAV muxed (video+audio) 実装をレビューするときに必ず通す観点 7 つ
- [private-module cross-import の命名規約](reference_private_module_all_for_cross_import.md) — `_foo.py` から cross-import されるシンボルは `_` prefix を付けない (privacy はモジュール名が担う)。__all__ で表面明示、テスト pin の旧名は import alias で互換
- [pytest -k filter discoverability](reference_pytest_k_filter_discoverability.md) — テスト関数名に共通プレフィックスがないと `pytest -k <feature>` で全 case が collect されない
- [skew-tolerance needs evidence](feedback_skew_tolerance_needs_evidence.md) — A/V sync などの quantitative threshold を spec から広げる場合、実測値を 1 行残す
- [verify regression test actually fails](feedback_verify_regression_test_actually_fails.md) — implementer の「stash で fail 確認した」報告を信じず、修正を 1 行 disable して再現する
