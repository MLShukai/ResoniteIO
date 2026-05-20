---
name: grpc-tools-message-duplication
description: Core で Server stub と Tests で Client stub を別生成すると message 型が重複し CS0436 が出る。テスト csproj 限定で NoWarn 抑制する。
metadata:
  type: feedback
---

`Grpc.Tools` の `<Protobuf>` を Core 側 (`GrpcServices="Server"`) と Tests 側 (`GrpcServices="Client"`) で別々に走らせると、同一 namespace に message 型 (`PingRequest` / `PingResponse` 等) が二重定義される。C# コンパイラは ProjectReference された Core 側を優先解決するので実行時には支障ないが、`CS0436` 警告が出る。`Directory.Build.props` で `TreatWarningsAsErrors=true` なのでビルドが落ちる。

**Why:** Step 2 の Core/Tests 分離で初発見。proto は単一ソースで Both stub を生成しないとビルドできない、または NoWarn を入れるかの二択。前者は Core が Client stub も export してしまい設計的に汚いので、後者を採用した。

**How to apply:** 新しいモダリティ proto を追加するとき、テスト側でも Client stub を生成するなら csproj に `<NoWarn>$(NoWarn);CS0436</NoWarn>` を入れる。テスト以外のプロジェクト (mod 側) で同じ衝突が起きた場合は設計を見直すこと (mod 側は Core を ProjectReference するだけで proto 直参照しない方針)。
