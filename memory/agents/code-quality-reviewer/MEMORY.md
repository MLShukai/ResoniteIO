# Code Quality Reviewer — Memory Index

- [Froox in-param lvalue](reference_froox_in_param_lvalue.md) — FrooxEngine の `in` API に float3.Up 等の static property を直接渡せず、ローカル変数経由が必須 (CS8156)。Bridge の world/slot ローカルは冗長でない
- [Modality client RPC dedup](project_modality_client_dedup.md) — resoio Python client の繰り返し unary-RPC body を public API を変えず `_dispatch` ヘルパで畳む方針
