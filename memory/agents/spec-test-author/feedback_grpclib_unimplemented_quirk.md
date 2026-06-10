---
name: grpclib-unimplemented-quirk
description: grpclib fake server から「サービス未実装の mod」を演じる正しい方法 — service を載せず omit すると client 側で UNKNOWN に化ける
metadata:
  type: feedback
---

「古い mod が RPC に UNIMPLEMENTED を返す」シナリオを grpclib fake server で演じるときは、**service を Server(\[...\]) から omit してはいけない**。un-overridden の生成 `<Modality>Base` を載せる (生成 base のメソッドが `GRPCError(Status.UNIMPLEMENTED)` を raise する)。

**Why:** grpclib server は unknown service への応答で content-type ヘッダを落とす (`grpc-status: 12` 自体は付く)。grpclib **client** は content-type 欠落で `GRPCError(Status.UNKNOWN, 'Missing content-type header')` を raise するため、テストには UNIMPLEMENTED が届かない。本物の C# Kestrel (Grpc.AspNetCore) server は content-type 付き trailers-only UNIMPLEMENTED を返すので、この化けは fake 側だけの quirk。PR C (Info モダリティ, 2026-06-10) の `test_version_check.py` / `test_info.py` で実際に踏んだ。

**How to apply:** 「mod が古くて RPC が無い」「modality 未実装 server」系のテスト (version probe の "mod too old"、UNIMPLEMENTED 素通し検証等) では `class _PreInfoMod(InfoBase): """..."""` のように生成 base をそのまま (docstring だけの body で) 継承・hosting する。実例: `python/tests/resoio/test_version_check.py` の `_PreInfoMod`、`python/tests/resoio/test_info.py` の `_UnimplementedInfo`。\[\[uds-server-fixture\]\] と組み合わせて使う。
