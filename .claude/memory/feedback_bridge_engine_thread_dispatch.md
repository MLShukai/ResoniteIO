---
name: bridge-engine-thread-dispatch
description: FrooxEngine Mod Bridge でコンポーネントグラフを変更する際の engine thread ディスパッチパターン。
metadata:
  type: feedback
---

Bridge 実装側で **FrooxEngine のコンポーネントグラフを変更する操作** (Slot.AddSlot,
AttachComponent, Slot.Destroy 等) は必ず engine update tick 上で行う必要がある。
任意スレッドから直叩きすると world snapshot 不整合や race を引き起こす可能性が高い。

**Why:** Step 3 Camera Bridge 実装で確認 (decompiled World.cs:2763 RunSynchronously
docstring + 既存 FrameworkEngineSessionBridge の volatile snapshot パターンの分析)。
`Camera.RenderToBitmap` は内部で `_scheduledRenderTasks` キュー経由になるので
任意スレッドから await 安全だが、Camera コンポーネントの生成・設定はそうではない。

**How to apply:** Mod 側 Bridge で engine state を変更する処理は以下のパターン:

```csharp
var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
world.RunSynchronously(() => {
    try { /* engine API 呼び出し */; tcs.TrySetResult(result); }
    catch (Exception ex) { tcs.TrySetException(ex); }
});
// CancellationToken と timeout を `using ct.Register(() => tcs.TrySetCanceled(...))` で組む。
return await tcs.Task;
```

- 純粋な読み出し (volatile スナップショット参照) は engine thread 不要。
- ProcessExit / Dispose 経路では `World.IsDisposed` の場合 RunSynchronously は no-op
  になるため安全。例外は飲んで best-effort で進める。
- 関連: \[\[engine-onshutdown-deferred\]\], \[\[core-mod-layering\]\]
