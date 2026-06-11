---
name: bridgefault-translate-helper
description: Core 層 Service の例外翻訳 case は BridgeFault.Translate ヘルパ 1 行に畳む。IOException 素通しは InvokeAsync が共通担当。
metadata:
  type: project
---

`mod/src/ResoniteIO.Core/Rpc/BridgeFault.cs` に集約済み:

- `InvokeAsync` の catch tail: `OperationCanceledException` 素通し →
  `IOException when ct.IsCancellationRequested` 素通し (Kestrel UDS の client cancel が
  IOException で表面化する経路を吸収、\[\[grpc-client-cancel-exception-surface\]\]) →
  共通 `Internal` 翻訳 (`LogError` + `"{modality} bridge faulted: {ex.Message}"`)。
- `Translate(log, modality, rpc, code, label, ex)` ヘルパ:
  `LogInfo($"{modality}.{rpc}: {label}: {ex.Message}")` + `RpcException(Status(code, ex.Message))`。
  **`Status.Detail = ex.Message` を必ず保つ** (各 Service テストが
  `Assert.Contains(..., ex.Status.Detail)` で substring pin)。

**各 Service の translate delegate は nullable 戻り** で、固有 case を
`BridgeFault.Translate(...)` 1 行に畳み、未処理は `null` を返して `InvokeAsync` の
共通 Internal 経路に委ねる。全 Service (World/Dash/ContextMenu/Cursor/Display/
Inventory/Grabber) がこの形に統一済み。label 文言は既存ログと一致させる
("bridge not ready" / "not found" / "invalid argument" / "invalid index" /
"recursion required" / "conflict")。

**手書き維持の例外:** Inventory の `InventoryCloudException` だけは `LogError` +
全例外ダンプ (`{cloud}`、`{cloud.Message}` でない) で原因追跡するので畳まない。

**WorldService 移行時の挙動差 (1 点、テスト未 pin):** 旧 WorldService は
exception filter で「OperationCanceledException が ct 未 cancel なら Internal 翻訳」していたが、
`InvokeAsync` は OperationCanceledException を常に rethrow する。他 Service と同じ統一方向なので採用。

**Grabber 注意:** RequireBridge/InvokeBridge の 2 分割は house style
(\[\[grabber-service-no-handleasync\]\])。translate の 1 case を helper に畳むのは
2 分割構造を崩さないので OK だが、HandleAsync への統合はしない。
