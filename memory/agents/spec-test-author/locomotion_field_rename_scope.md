---
name: locomotion-field-rename-scope
description: proto field の rename/renumber 時にどのテストが追従し、どれが追従しないか (C# ApiContract と Python proto_contract の役割分担)
metadata:
  type: feedback
---

proto の field 名 rename + field 番号 renumber を伴うモダリティ拡張 (例:
LocomotionCommand の move_x/move_y → move_forward/move_right/move_up 化 +
renumber) のテスト追従範囲。

**追従が必要 (field 名 / 番号を直接触っているテスト)**:

- C# `mod/tests/ResoniteIO.Core.Tests/Locomotion/*.cs` — POCO `LocomotionInput`
  の field 名 (`MoveForward` 等) と proto-generated message の setter 名
  (`new V1.LocomotionCommand { MoveForward = ... }`) を直接使うので全箇所追従。
- Python `python/tests/resoio/test_proto_contract.py` — `_EXPECTED_FIELDS` の
  field-name→wire-number マップ。**これが wire 番号の唯一の pin** (renumber は
  ここでしか検出されない。protobuf wire は番号 keyed なので名前 rename だけなら
  source break、renumber は silent wire corruption)。
- Python `python/tests/resoio/test_locomotion.py` / `cli/test_locomotion.py` /
  `e2e/locomotion.py` — `LocomotionCmd(move_forward=...)` / `_DriveState.forward`
  等を直接使うので追従。

**追従が不要 (field 名で pin していないテスト)**:

- C# `mod/tests/ResoniteIO.Core.Tests/ApiContractTests.cs` —
  `ResoniteIOV1_GeneratedProtoTypes_MatchSnapshot` は **型 FullName** のみ列挙
  (message 型名 `ResoniteIO.V1.LocomotionCommand` は rename で変わらない)。
  `ILocomotionBridge_MethodSignatures` も `SetState(LocomotionInput)` と **型** で
  pin (field 名は含まない)。よって field rename/renumber では一切編集不要。
- C# `Common/Fakes/FakeLocomotionBridge.cs` — `LocomotionInput` を verbatim
  記録するだけなので POCO 側の field 追加/rename が自動で通る。

**手順上の罠**: proto を変えたら **`just gen-proto` を流してから** Python test を
回す (betterproto2 生成物 = `python/src/resoio/_generated/` が古いと
test_proto_contract が旧番号で pass してしまう)。C# は `dotnet test` が
build-time に proto 再生成するが、`obj/Debug/.../*.cs` の旧生成物は build まで
残る (grep で古い名前がヒットしても build で消えるので無視してよい)。

**e2e の wire-only phase**: 視覚的に動かない軸 (move_up は既定 Walk module だと
垂直移動しない) を e2e scenario に足す場合は「送信されること」だけ確認し、視覚
assert は付けない。docstring に "wire-only / no visible motion" を明記する。
