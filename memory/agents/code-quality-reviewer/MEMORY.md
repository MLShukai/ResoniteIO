# Code Quality Reviewer — Memory Index

- [Froox in-param lvalue](reference_froox_in_param_lvalue.md) — FrooxEngine の `in` API に float3.Up 等の static property を直接渡せず、ローカル変数経由が必須 (CS8156)。Bridge の world/slot ローカルは冗長でない
- [Modality client RPC dedup](project_modality_client_dedup.md) — resoio Python client の繰り返し unary-RPC body を public API を変えず `_dispatch` ヘルパで畳む方針
- [Dispatch factoring pattern](project_dispatch_factoring_pattern.md) — `_dispatch` が同一戻り型 (ContextMenu) と複数戻り型 (Dash) で責務が異なるのは正しい適応。consistency 目的で「修正」しない
- [Dash action-result factories](project_dash_action_result_factories.md) — Dash Bridge の操作系で重複していた snapshot 生成を NotFound/Rejected/Succeeded factory 三点に畳む。best-effort 操作 Bridge の定石
