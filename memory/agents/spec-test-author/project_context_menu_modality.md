---
name: context-menu-modality
description: ContextMenu modality (radial T-key menu) added to resonite-io — unary RPC modality mirrored on Display
type: project
---

ContextMenu modality (Resonite の T キー radial メニュー操作) が resonite-io に追加された。Display と同じ unary request/response 形のモダリティ。

**Why:** AI エージェントから「メニュー開閉 / 項目列挙 / Highlight / Invoke」を gRPC over UDS で操作するため。Highlight (選択のみ) と Invoke (実行) は別 RPC。

**How to apply:**

- Core contract: `namespace ResoniteIO.Core.ContextMenu` に `ContextMenuHandSelector` enum / `ContextMenuItemSnapshot` / `ContextMenuStateSnapshot` records / `IContextMenuBridge` / `ContextMenuNotReadyException` / `ContextMenuService`。
- Service 例外翻訳: bridge null → Unavailable、`ContextMenuNotReadyException` → FailedPrecondition、`ArgumentOutOfRangeException` → InvalidArgument、その他 → Internal。
- proto hand enum: UNSPECIFIED(0)/PRIMARY(1) → Primary, LEFT(2) → Left, RIGHT(3) → Right。生成 C# enum 名は prefix 剥がれて `ContextMenuHand.{Unspecified,Primary,Left,Right}`。
- `ContextMenuService` は `SessionHost.Start` に mount 済 (`contextMenuBridge` が Start の最後の optional 引数)。Display と違い別 host helper は不要 — `SessionHostHarness` で end-to-end に流せる。
- tests: `mod/tests/ResoniteIO.Core.Tests/ContextMenu/ContextMenuServiceTests.cs` (integration-real)、fake は `Common/Fakes/ContextMenuBridgeFake.cs`。`[Collection("SessionHostEnv")]` 必須 (harness が env var を触る)。
