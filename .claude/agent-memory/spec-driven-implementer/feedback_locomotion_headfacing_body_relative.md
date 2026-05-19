---
name: locomotion-headfacing-body-relative
description: Locomotion Move ExternalInput を userRoot.HeadFacingRotation で回転すると body-relative 移動が定量的に成立する (2026-05-19 実機検証)。
metadata:
  type: feedback
---

`FrooxEngineLocomotionBridge.ApplyToEngine` で `Move.ExternalInput` を
**`userRoot.HeadFacingRotation`** から作った slotForward/slotRight に基づき
書く実装が body-relative 移動として正しい。

**Why**:
2026-05-19 実機 4-stage position diagnostic で検証 (前進 → 90度 yaw → 前進、
\[LocomotionPos\] log で `Slot.GlobalPosition` 計測):

- V_B (turn 前 前進ベクトル) ≈ (0, 0, 7.88) → +Z 方向
- V_D (turn 後 前進ベクトル) ≈ (7.99, 0, 0.40) → +X 方向
- 角度差 = arccos(0.050) ≈ **87.1°** (頭の最終 yaw 88.6° と整合、tolerance 内)

decompile の `ScreenLocomotionDirection.Evaluate` は `World.LocalUserViewRotation`
を使うが、`HeadFacingRotation` と `LocalUserViewRotation` は screen mode で
ほぼ一致する (検証中 viewEuler vs headFacingEuler の差は \< 2°)。前者を採用
している理由は、pitch を含まない水平投影 rotation で move が水平面に乗ること。

**How to apply**:

- 新規の locomotion 系修正で「移動が world-fixed になっている疑い」が出たら、
  まず Bridge の `HeadFacingRotation` 経路が消えていないかを確認する。
- `LocalUserViewRotation` への切替を検討する場合、view が pitch を含むため
  Move が下向きに sink する可能性に注意。実機検証 (2-stage 前進テスト) を
  必ず行うこと。
- 検証スクリプトの prototype は会話の `/tmp/verify_locomotion_position.py`
  に置いた (commit はしない)。state-change pulse + 60-tick periodic の
  position log を Bridge に一時注入する手順は本会話の Step 1-4 に集約。

関連: \[\[locomotion-external-input\]\]
