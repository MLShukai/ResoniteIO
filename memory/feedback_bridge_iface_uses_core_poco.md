---
name: bridge-iface-uses-core-poco
description: Mod 側 Bridge IF が返す型は proto 生成型ではなく Core 層 POCO にする (CS0436 で test 側 Fake bridge が interface を実装できなくなる罠を避ける)
metadata:
  type: feedback
---

Mod 側 Bridge IF (`I<Modality>Bridge`) が返す frame 型は **proto 生成型 (`V1.<X>Frame`) ではなく Core 層 POCO (`record struct <X>Frame`)** で定義する。Service 層で `MapToProto` してから wire に乗せる。

**Why:** Core プロジェクト (Server stub 生成) と Tests プロジェクト (Client stub 生成) で proto 由来の message 型が **二重定義** され CS0436 が出る (\[\[grpc-tools-message-duplication-in-test-projects\]\] で抑止済み)。message を直接 *データ* として使う限り「ProjectReference 優先解決」で C# コンパイラが Core 側を選ぶので問題にならないが、**Fake bridge が `IAsyncEnumerable<V1.AudioFrame>` を return する interface を実装しようとすると CS0738** (return type mismatch) で fail する: テストアセンブリ自身が同名の `V1.AudioFrame` を持つため type identity が衝突し、`extern alias` や `global::` 修飾でも解決できない。

**How to apply:** Camera が既に踏襲しているパターン (`Camera/ICameraBridge.cs` の `CameraFrame` POCO + `CameraService.MapToProto`) を新規モダリティで踏襲する。**proto 型を直接 interface signature に出さない** (戻り値 / 引数のどちらでも)。Bridge 側でフィールドを Core POCO に詰める → Service が `MapToProto` で proto 化する 2 段にする。これにより Fake bridge は Core POCO だけを参照すれば実装できる。実例: `mod/src/ResoniteIO.Core/Speaker/ISpeakerBridge.cs` (record struct `AudioFrame` を返す)。
