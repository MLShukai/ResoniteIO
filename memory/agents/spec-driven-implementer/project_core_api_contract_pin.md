---
name: core-api-contract-pin
description: ResoniteIO.Core に新規型を足すと ApiContractTests の exported-types snapshot が落ちる。共有ヘルパは internal にする
metadata:
  type: project
---

`mod/tests/ResoniteIO.Core.Tests/ApiContractTests.cs` の
`ResoniteIOCore_ExportedTypes_MatchSnapshot` は `ResoniteIO.Core.*` 名前空間の
**public 型 FullName の完全一覧** を `Assert.Equal(expected, actual)` で固定している。

**Why:** Hyrum's law mitigation。外部利用者 (mod / 将来 SDK) が依存する public surface を
意図せずリネーム/追加/削除しないための人間 approve ゲート。

**How to apply:** Core 層に横断的な共有ヘルパ (例: `Rpc/BridgeGuard`, `Rpc/BridgeFault`) を
足すときは `internal static` にする。`public` にすると snapshot に載らず test が落ち、
test は spec-test-author 領域なので実装側では直せない。`GetExportedTypes()` ベースなので
`internal` 型は一切引っかからない。同一アセンブリ内の Service からは `internal` で十分。

関連: World/Inventory 等の modality 固有例外 (NotReady/NotFound/Conflict/Cloud 等) は
共通基底を持たず各々 `sealed : Exception`。共通 fault helper は型パラメータや
translate delegate で扱い、例外型の物理移動はしない (snapshot にも載っているため移動は破壊的)。
