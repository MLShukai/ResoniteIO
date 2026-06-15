---
name: core-tests-grpc-gen-split
description: ResoniteIO.Core.Tests assembly generates client-only grpc stubs; ResoniteIO.Core src generates server XxxBase. ApiContract pins Core asm.
metadata:
  type: feedback
---

grpc 生成物は assembly ごとに mode が違う。

- **`ResoniteIO.Core` src** (`typeof(GrpcHost).Assembly`): server stub を生成 → `ResoniteIO.V1.<Svc>+<Svc>Base` (abstract) + BindService。`ApiContractTests` の V1 snapshot はこの assembly を見るので、snapshot には `+<Svc>Base` を必ず含める。
- **`ResoniteIO.Core.Tests` assembly**: client-only 生成 → `V1.<Svc>.<Svc>Client` (ClientBase)。round-trip テストはこの Client を `new V1.Contact.ContactClient(channel)` のように使う。

**Why:** ContactGrpc.cs を見ると test asm 側に `ContactBase` が無く、Core src 側にだけ `ContactBase` がある。混同すると ApiContract snapshot の `+XxxBase` を取りこぼす / Client 名を間違える。

**How to apply:** 新規モダリティの Core テストを書くとき、ServiceHost は `KestrelServiceHost<XxxService>` 継承で `V1.<Svc>.<Svc>Client` を使う。ApiContract V1 snapshot を更新するときは Core src の `obj/.../resonite_io/v1/<Svc>Grpc.cs` を読んで `+<Svc>Base` を確認する。テンプレートは `Common/SessionServiceHost.cs` / `Session/SessionServiceTests.cs`。
