---
name: grabber-service-state-rpc-dedup
description: GrabberService の state-返す RPC は RunStateRpc に畳んでよいが Grab は別型なので畳まない
metadata:
  type: feedback
---

> 2026-06-11 にモダリティ名を Manipulation から **Grabber** へ rename。
> 2026-06-22 (PR #55) に Use/Unuse/Equip/Dequip を追加し RPC が 7 本になったので方針を更新。

`GrabberService` の RPC dedup 方針:

- **`GrabberGrabState` を返す 6 RPC** (Release / GetState / Use / Unuse / Equip /
  Dequip) は共通尾部 `RequireBridge → InvokeBridge → MapToProtoState` を private
  `RunStateRpc(rpc, Func<IGrabberBridge, ct, Task<GrabSnapshot>>, ctx)` に畳む。
  per-RPC の引数 parse (radius/button/strength) は各 override にインライン維持。
- **`Grab` は畳まない**: 別 proto 型 `GrabberGrabResult` (Grabbed フィールド付き) を
  返すため。無理に共通 helper へ押し込むと over-abstraction になる。

**Why:** 当初 (3 RPC 時点) は state-返す RPC が Release/GetState の 2 本だけで
「2 回まで OK、3 回目で抽象化」閾値の内側だったので畳まなかった。PR #55 で
同形 RPC が 6 本に増え閾値を明確に超えたため `RunStateRpc` 集約が house style に
合致する。`MapToProtoState` / `ToSelector` / `ToButton` 等の map helper はそのまま。

**How to apply:** Grabber service を触るとき、state-返す RPC は `RunStateRpc` 経由を
維持する。Grab を `RunStateRpc` に統合しろという指摘が来ても戻り型が違うので実施しない。
ContextMenu の単一 HandleAsync とは違い、Grab の存在ゆえ完全な単一化はできない。
