---
name: kestrel-servicehost-base
description: Common/KestrelServiceHost<TService> 基底に各モダリティ単機能 gRPC host のボイラープレートを集約済み。新規 XxxServiceHost はこれを継承する
metadata:
  type: feedback
---

C# Core.Tests の単機能 gRPC round-trip 用 host (`Common/XxxServiceHost.cs`) は
`Common/KestrelServiceHost<TService>` を継承する。

**Why:** Display/World/Inventory の各 ServiceHost が Kestrel(`CreateSlimBuilder`+
`ListenUnixSocket`+`MapGrpcService<T>`+socket 出現待ち) / `CreateChannel`(UDS
SocketsHttpHandler) / `DisposeAsync`(StopAsync→DisposeAsync→File.Delete) を完全に
複製していた (各 ~100 行)。基底に寄せて各サブクラスは ~40 行に縮小。

**How to apply:** 新規モダリティの単体 round-trip host を足すときは
`internal sealed class XxxServiceHost : KestrelServiceHost<XxxService>` とし、
private ctor で `: base(app, socketPath)`、`StartAsync` 内で
`StartCoreAsync("<label>", services => services.AddSingleton(bridge))` を呼ぶだけ。
bridge が optional (null 経路で Unavailable を検証する) なら delegate 内で
`if (bridge is not null) services.AddSingleton(bridge)`。
呼び出し側 API (`await XxxServiceHost.StartAsync(bridge)` + `SocketPath` /
`CreateChannel()` / `await using`) は基底が public 提供するので不変に保てる。

複数 Service を mount し env var (`RESONITE_IO_SOCKET`) で socket 解決する統合経路は
別物 (`GrpcHostHarness`)。これは Kestrel を直接立てず `GrpcHost.Start` を使うので
基底には寄せない。
