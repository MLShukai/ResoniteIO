---
name: manipulation-grabber
description: Manipulation modality の engine 経路 — Grabber API での Grab/Release、hand-pose 注入が不可な理由、unary RPC 採用、home に grabbable が無い e2e 制約。
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
- 代替: `Grab(point, radius)` が任意 world point を取るので、**手を動かさず任意座標で掴める**
  (pose 制御の代用)。

## RPC 形は unary (plan の client-streaming から変更)

pose を外し grab/release のみになったことで操作は離散 edge-triggered。連続 state も無いので
**ContextMenu と同じ unary** (`Grab` / `Release` / `GetState`) を採用。client-streaming repeater は不要。
proto は `ManipulationHand` enum (ContextMenuHand 同規約) + `WorldPoint` (message 不在 = 手の現在位置)、
radius `<=0` は **Service 側で 0.1m default** (Core でテスト可能にするため)。

## e2e の制約: home に grabbable が無い

実機 e2e (`python/tests/e2e/manipulation.py`) は get_state/grab/release の **RPC 契約**
(mod ロード・実 Grabber 到達・例外なし・hand 解決・release で is_holding False) を検証し green。
ただし **default local home world に掴める object が spawn 付近に無く、API で grabbable を
決定的に生成する手段も無い**ため `grabbed=True` の positive grab は自動化不可。object が手に追従する
目視確認は `mod/tests/manual/manipulation-verification.md` の人手手順に残した。
今後 positive grab を自動化するなら「grabbable を含む決定的な test world / record」か
「spawn 手段」の確立が前提。
