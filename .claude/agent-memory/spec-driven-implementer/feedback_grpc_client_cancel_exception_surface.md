---
name: grpc-client-cancel-exception-surface
description: Grpc.AspNetCore on Kestrel UDS may surface client-side stream cancellation as IOException rather than OperationCanceledException; catch broadly and check ct.IsCancellationRequested.
metadata:
  type: feedback
---

Grpc.AspNetCore (Kestrel) backed gRPC server で client-streaming RPC を受けている際、client 側が `CancellationTokenSource.Cancel()` で stream を中断すると、サーバ側の `await requestStream.MoveNext(ct)` は **必ずしも `OperationCanceledException` を throw しない**。

**Why:** UDS 切断 / Http/2 RST_STREAM が cancel token の signaling より早く Kestrel に到達するケースがあり、その経路では `IOException` (またはその派生 `ConnectionResetException` 等) が表面化する。`ct.IsCancellationRequested == true` でも例外型が `OperationCanceledException` でない場合があり、単純な `catch (OperationCanceledException)` だけでは「cancelled」と判定できない。

**How to apply:** client-streaming / bidi-streaming RPC で client cancel を確実に検出したい場合は、以下の 3 段階で catch する:

```csharp
catch (OperationCanceledException) { /* cancelled */ }
catch (IOException) { /* cancelled (UDS / Http/2 abort) */ }
catch (Exception) when (ct.IsCancellationRequested) { /* cancelled (lib 実装差吸収) */ }
catch (Exception) { /* genuine error */ }
```

この pattern は `mod/src/ResoniteIO.Core/Locomotion/LocomotionService.cs` で採用。`Drive_ClientCancellation_NotifiesCancelledDisconnect` テストが `OperationCanceledException` だけの単純 catch だと `Errored` が観測されて failing になることで発覚した。
