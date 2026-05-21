---
name: core-mod-layering
description: ResoniteIO は Core/Mod 二層構成。コアは Resonite 非依存ライブラリ、mod は engine bridging のみの薄いアダプタ。
metadata:
  type: feedback
---

ResoniteIO の実装は **コア層** と **mod 層** に分離する。新しいモダリティを追加する際は必ずこの二層構成に従う。

- **コア層** (`ResoniteIO.Core` / `resoio`)
  - BepInEx / FrooxEngine / Renderite を一切参照しない (`Microsoft.NET.Sdk` + Grpc 系のみ)
  - gRPC server (Kestrel + UDS)、Service 実装、proto handler、各モダリティのドメインロジックを置く
  - mod 側が注入する callback interface (`ISessionBridge`, `ICameraBridge`, ...) を公開
  - Kestrel ラウンドトリップを含む統合テストを **実機 Resonite なしで** 書ける (xunit + Grpc.Net.Client)
- **mod 層** (`ResoniteIO`)
  - BepInEx Plugin。`ResoniteIO.Core` を `ProjectReference` する
  - 責務は engine bridging のみ: コアが要求する Bridge IF を FrooxEngine API で実装、`OnEngineReady` でコアを起動、shutdown で停止
  - ドメインロジックは持たない (純粋アダプタ)
- **Python 層** (`resoio`): すでにピュア Python なので追加要件なし

**Why:** ユーザー指示「コア機能は Resonite に依存しないピュアな C# / Python で作り、Resonite Modding 側はインターフェイスを叩くだけ」(2026-05-14 セッション、Step 2 着手前の方針決定)。利点: (1) Kestrel ラウンドトリップを実機なしで xunit 検証できる、(2) 将来 Crystite 方式の独自ホスト / 軽量レンダラへ Core 層をそのまま転用できる、(3) モダリティ実装を Core 側で先行し mod 側 bridging を後追いさせる並列化が効く。

**How to apply:** 新しいモダリティ Service を追加するときは必ず **(a) Core 側に Service + Bridge IF**、**(b) Mod 側に Bridge 実装** の 2 ペアを作る。proto の `<Protobuf GrpcServices="Server" />` は Core csproj に置き、mod csproj は Core を ProjectReference するだけ。BepInEx 依存・FrooxEngine 依存のコードが Core に紛れ込んでいたら設計違反として差し戻す。Python 側の新規 client (`CameraClient` 等) は `resoio.session.SessionClient` と同じ async context manager パターンに揃える。
