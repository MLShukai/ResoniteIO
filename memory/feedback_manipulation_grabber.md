---
name: manipulation-grabber
description: Manipulation modality の engine 経路 — Grab はカーソルレイ hit 点中心の radius grab (point 指定は廃止)、Grabber API、hand-pose 注入が不可な理由、unary RPC 採用、home に grabbable が無い e2e 制約。
metadata:
  type: feedback
---

# Manipulation modality (Grabber) の engine 経路と設計判断

Step 6 (2026-06-06 完了)。Resonite 内オブジェクトの **Grab / Release** を engine 経由で行う。
先行モダリティ (\[\[feedback_locomotion_external_input\]\] / \[\[feedback_speaker_engine_tap\]\] /
\[\[feedback_microphone_engine_tap\]\]) と同様、本ファイルが Manipulation 固有の engine 知見の一次正典。

## Grab / Release の engine 経路 (FEASIBLE)

各手の `InteractionHandler` が public `Grabber` を持つ:

- 到達経路: `world.LocalUser.GetInteractionHandler(Chirality side).Grabber`
  (ContextMenu の `ResolveHandler` と同じ。`InteractionHandler.Grabber` は public、
  `decompiled/.../InteractionHandler.cs:1554`)。
- `Grabber.Grab(float3 point, float radius)` → bool: `point` 周辺 `radius` の grabbable を近接 grab
  (`decompiled/.../Grabber.cs:224`)。**唯一の public proximity grab**。掴めなければ false (エラーではない)。

## Grab 中心はカーソルレイの hit 点 (2026-06-10 breaking change で point 指定を廃止)

`ManipulationGrabRequest.point` (`WorldPoint`) は削除 (field 2 は reserved)。Grab は常に
**現在のデスクトップカーソルレイが当たった点** を中心に radius 内を掴む:

- レイ起点: `world.LocalUserViewPosition`。方向: `world.LocalUserViewRotation * MathX.UVToPerspectiveCameraDirection(Mouse.NormalizedWindowPosition, InputInterface.WindowAspectRatio, world.LocalUserDesktopFOV)` — desktop の targeting と同式 (`decompiled/.../TargettingControllerBase.cs:114`)。
- raycast: `world.Physics.RaycastAll(origin, dir, float.MaxValue, hits, c => !c.IsUnderLocalUser, hitTriggers: false)` (`RaycastDriver.cs:62` パターン、自己 collider は `IsUnderLocalUser` で除外) →
  先頭 hit の `hit.Point` を `Grabber.Grab(point, radius)` へ。レイ miss は Grab を呼ばず `grabbed=false`。
- **`InteractionLaser.LastInteractionTargetPoint` は使わない**: hit 点ではなく `origin + dir * distance`
  の未スムージング目標点で miss でも値が入る。本当の hit (`LastHitPoint`) は laser が active/visible
  (ActiveTool あり or 直近 2 秒の activity) の時しか更新されず、agent 操作では stale になる。
- VR モード (`InputInterface.ScreenActive == false`) は `ManipulationNotReadyException` →
  gRPC `FailedPrecondition` (message に "desktop" を含む)。
- Cursor モダリティの永続保持 (\[\[feedback-cursor-lock-mechanism\]\]) と連動:
  `cursor.set_position` で照準 → `manipulate grab` の流れが cross-RPC で成立する。

## Hold 位置: grab 直後に object を手へ寄せる (頭上に飛ぶ問題の修正、2026-06-10)

grab 時 object は world 位置を保ったまま HolderSlot 下に reparent されるが、desktop では
**HandSimulator が grab 直後に手を rest pose (腰 y≈0.76) から保持ポーズ (胸 y≈1.31) へ
動かす**。レイで遠くを掴むと holder-local offset (実測 ≈1m) が lever arm として手の
移動・回転に振り回され、object が頭の高さ・体の背後 (z+0.8) へ飛ぶ (実機計測)。

- engine 自身の laser grab は「grab 前に HolderSlot を laser 点へ移動」で回避しているが、
  **HolderSlot.Position_Field は InteractionHandler の FieldDrive に駆動されており外部から
  書けない** (`GlobalPosition` への書き込みは読み戻しでは見えるが SetParent の local 計算には
  効かない — 実機で確認した罠)。
- 採用した修正 (desktop 仕様、ユーザー確定 2026-06-10): grab 直後から **手の遷移が settle
  するまで (実測 ~30 update、margin 2 倍で 60) 毎 update object の grab 時 world pose を
  書き戻してピン留め** する (`PinGrabbedAtGrabPose` / `PinStep`、`world.RunInUpdates(1, ...)`
  の自己再スケジュール)。object は移動量ゼロでカーソル位置に留まり、settle 後は確定した
  holder-local offset で手 (= 体) に追従する。release / 削除 / 他 grabber への移動で打ち切り。
  実機 screenshot で「掴んでも皿の上の DragonFruit が動かない」ことを確認。
- **VR モード対応時は別解が良い**: 手で直接掴む UX なので object を手の中へ寄せる
  `slot.Position_Field.TweenTo(float3.Zero, 0.1f, CurvePreset.Sine, onlyUnderParent: slot.Parent)`
  (engine の TryAlignGrabbed と同じ演出、decompiled InteractionHandler.cs:3935) が自然
  (実機確認済みの良挙動)。Bridge の XML doc コメントにも残してある。現状 GrabAsync は VR を
  FailedPrecondition で拒否するため desktop 経路のみ実装。

## e2e の positive grab は Inventory spawn で自動化可能 (2026-06-10 制約解消)

`InventoryClient.spawn("/Inventory/Resonite Essentials/Mirror")` で grabbable な Mirror を
決定的に spawn できる (視界正面に出る)。spawn → `cursor.set_position(0.5, 0.45)` →
`grab(radius=0.5)` で `grabbed=True` + `object_names=("Mirror",)` が実機 green。
注意: 起動直後すぎる spawn は想定位置に出ないことがある (ready 待ち必須) ため、照準点を
数点 retry する。world から削除する API は無く release して放置 (local home は再起動で
リセット)。これにより下記の旧制約は解消済み。

- `Grabber.Release(bool supressEvents = false)`: 保持物を全 release (`Grabber.cs:358`)。
- `Grabber.IsHoldingObjects` / `GrabbedObjects` (`IReadOnlyList<IGrabbable>`) で状態取得。
  object 名は `grabbable.Slot.Name` (best-effort、null guard)。
- **掴んだ object は HolderSlot に reparent され以後は手に自動追従** (`Grabbable.Grab` →
  `Slot.SetParent(holdSlot)`)。よって **per-frame repeater 不要** (Locomotion と対照的)。
  Grab/Release は離散の **edge-triggered one-shot**。

これらは component graph 変更なので engine thread dispatch 必須
(\[\[feedback_bridge_engine_thread_dispatch\]\])。ContextMenu bridge と同じ one-shot
`RunOnEngineAsync` (`World.RunSynchronously` + TCS) を使い、bridge は engine 状態を
持たず **非 IDisposable**。`ResolveChirality` も ContextMenu からコピー
(Primary/Unspecified → `world.InputInterface?.PrimaryHand ?? Chirality.Right`)。

## Hand pose 注入は不可 (INFEASIBLE) → スコープ外

当初 plan は "Hand Slot Pose 制御" を含めていたが除外した:

- `TrackedDevicePositioner.BeforeInputUpdate` が `[DefaultUpdateOrder(-1000000)]` で
  **毎 input update に hand slot を tracked-device pose で上書き**する
  (`decompiled/.../TrackedDevicePositioner.cs`)。直接 slot に書いても次フレームで消える。
- Locomotion の `Analog3DAction.ExternalInput` のような注入 slot が hand pose 経路には無い。
- desktop では hand は `HandSimulator` が laser/IK で駆動 (`InteractionTargetPoint` =
  laser の指す先)。任意 pose を押し込む input source が無い。
- 代替: `Grab(point, radius)` は任意 world point を取れるので、**手を動かさずカーソルレイの
  hit 点で掴める** (pose 制御の代用。2026-06-10 以降、中心点は常にレイ hit 点で API からの直接指定は不可)。

## RPC 形は unary (plan の client-streaming から変更)

pose を外し grab/release のみになったことで操作は離散 edge-triggered。連続 state も無いので
**ContextMenu と同じ unary** (`Grab` / `Release` / `GetState`) を採用。client-streaming repeater は不要。
proto は `ManipulationHand` enum (ContextMenuHand 同規約)、radius `<=0` は **Service 側で 0.1m default**
(Core でテスト可能にするため)。旧 `WorldPoint point` field は 2026-06-10 に削除 (field 2 reserved)。

## e2e の制約: home に grabbable が無い

実機 e2e (`python/tests/e2e/manipulation.py`) は get_state/grab/release の **RPC 契約**
(mod ロード・実 Grabber 到達・例外なし・hand 解決・release で is_holding False) を検証し green。
ただし **default local home world に掴める object が spawn 付近に無く、API で grabbable を
決定的に生成する手段も無い**ため `grabbed=True` の positive grab は自動化不可。object が手に追従する
目視確認は `mod/tests/manual/manipulation-verification.md` の人手手順に残した。
今後 positive grab を自動化するなら「grabbable を含む決定的な test world / record」か
「spawn 手段」の確立が前提。
