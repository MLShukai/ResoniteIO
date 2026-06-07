---
name: test-only-service-host
description: Mod 化前の新規 modality を GrpcHost に mount しない wave で in-process gRPC round-trip テストを書く時は test 専用の最小 Kestrel host を分離して立てる
metadata:
  type: feedback
---

新規 modality (e.g. `DisplayService`) を Core に追加するが、Plan 同期点の
制約で当 wave では `GrpcHost.cs` に <c>MapGrpcService\<NewService>()</c>
を入れられないケースがある (`GrpcHost` 編集者は別 commit に固定されているなど)。

このとき in-process gRPC round-trip テストを書くには:

- **NOT recommended**: `Grpc.Core.Testing.TestServerCallContext` で
  `ServerCallContext` を fake して service method を直叩きする。
  新規 NuGet (`Grpc.Core.Testing`) 追加が必要 + 実 gRPC pipeline を通らない。
- **Recommended**: test 専用の最小 Kestrel + UDS gRPC host を別途 helper として
  追加する (e.g. `DisplayServiceHost`)。`GrpcHostHarness` を真似た
  パターンで、`MapGrpcService<NewService>()` だけを行う。GrpcHost.cs を
  一切触らずに gRPC round-trip テストが書ける。

**Why:** 実 gRPC pipeline (proto serialization、Status code 翻訳、Cancellation
propagation) を通したテストは Service の挙動を最も信頼できる形で検証する。
Service 単体のロジックは domain method を直接呼べばよいが、Service 層の
本質的価値は proto ↔ domain 変換 + 例外翻訳なので gRPC round-trip まで通すと
回帰検知が強くなる。

**How to apply:** Wave 跨ぎで段階導入する modality (Display、Locomotion、
Manipulation 等) の Core 側 commit では、`<Modality>ServiceHost` を test
helper として作って round-trip テストを書く。後続 wave で `GrpcHost` に
mount された後も、当該 helper は残しても OK (modality 単独テストの隔離環境)。
