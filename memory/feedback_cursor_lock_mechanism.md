---
name: feedback-cursor-lock-mechanism
description: Cursor set は永続 cursor lock + Harmony OutputState 偽装で engine 内カーソルを保持する (OS ポインタは奪わない)。release で OS 追従に戻す。lockCursorPosition だけ null 化すると中央 pin になる罠
type: project
---

Cursor モダリティ (`FrooxEngineCursorBridge`) の `SetPosition` は **永続保持** で実装する (2026-06-10、one-shot warp から変更): engine thread 上で `InputBindingManager.RegisterCursorLock(world.RootSlot, pixel, priority=1_000_000)` の lock を **RPC を跨いで保持** し、`Release` RPC で解放して OS マウス追従へ戻す。OS ポインタを奪わないために `InputInterface.CollectOutputState` を Harmony Postfix で patch し、renderer へ渡る `OutputState` を「自分の lock が無かった世界線」に偽装する。`SetMousePosition` (OS warp) は廃止 (OS ポインタに触れない契約)。

**Why:** engine 内カーソル保持と OS ポインタ拘束は engine 内では同じ lock 機構に束ねられている:

- `Mouse.Update` (decompiled/.../Mouse.cs:67-71) は `CursorLockPosition.HasValue` なら毎フレーム `WindowPosition` を lock 位置へ強制 — これが engine 内保持の仕組みで、デスクトップのレイ方向 (`TargettingControllerBase.cs:114`、`Mouse.NormalizedWindowPosition` から計算) もこれに追従する。
- 一方 `InputInterface.CollectOutputState` (InputInterface.cs:325-333) が `lockCursor` / `lockCursorPosition` を renderer 側 `OutputState` に渡し、**renderer の `MouseDriver.HandleStateUpdate` (decompiled/Assembly-CSharp/MouseDriver.cs:62-100) が OS ポインタを拘束する**: `lockCursorPosition` あり → 毎フレーム OS warp + `Confined` (旧永続 lock 実装でマウスが奪われた直接原因)。`lockCursor=true` かつ position なし → `CursorLockMode.Locked` (**中央 pin**)。
- ⇒ **patch で `lockCursorPosition` だけ null にすると Locked 化して改悪**。`lockCursor` も再計算が必要。`InputInterface.Update` (615-632) は lock が 1 つでもあると unlocker チェックをスキップして `IsCursorLocked = IsWindowFocused` に化けるため、「自 lock 抜きの世界線」の `lockCursor` は `!anyUnlocker && IsWindowFocused` で再計算する。自 world の unlocker は `UnlockCursor` getter (InputBindingManager.cs:54-64) が自 lock の存在で false に化けるので、`AccessTools.FieldRefAccess` で `_cursorUnlockers` / `_cursorLockers` を直接読む。

**How to apply:**

- 保持: `RegisterCursorLock` は mutable な `CursorLock` (public `position`/`priority`) を**返す** (InputBindingManager.cs:182-192)。保持中の再 set は `_lock.position = pixel` の直接書き換えで次フレーム反映 (re-register 不要)。**`RegisterCursorLock` は priority 引数を無視する**ため、戻り値の `cursorLock.priority` に明示書き込みする。
- world 切替: `IsRemoved` な locker は engine が毎フレーム自動 prune (world dispose で lock は自然消滅)。lock 選択は `Running && Focus != Background` の world のみ対象なので、focus が別 world に移ると lock は不活性化 → bridge は「focused world ≠ lockWorld なら held=false 報告」で観測と一致させる (自動マイグレーションはしない)。
- Harmony Postfix のロジック: `!_held` なら即 return → 自分以外の非 IsRemoved locker が居れば触らない (他者の lock 尊重) → 自分が唯一なら `lockCursorPosition=null` + `lockCursor` 再計算。postfix 内は no-log・例外握りつぶし (Speaker と同方針)。reflection / patch 失敗時は **patch 不適用 + Set/Release を fail-loud** (CursorNotReadyException → FailedPrecondition) に degrade — 偽装なしで lock を張ると OS を奪う退行になるため。
- settle-poll (16ms × 最大 20 回) は維持 (lock 反映は次の `Mouse.Update` までずれるため、「反映後の state を返す」契約に必要)。
- Dispose (plugin SafeShutdown、GrpcHost 停止前): `_held=false` → lock 解除 queue → `UnpatchSelf` → singleton クリア。
- 保持中の副作用: 実マウス移動は `WindowPosition` に反映されないがクリック等のボタンは生きる → **保持中に人間がクリックすると保持位置でクリックされる** (docstring に明記済み)。
- menu-at-cursor は保持により **cross-RPC でも成立** (`set_position(0.5,0.5)` → 別 RPC の `context_menu.open()` が中央に開く)。auto-close (exit-lerp) は従来どおり agent では発火しない (実 OS active pointer 要求)。agent は `close()` で明示的に閉じる。
- 読み取り・座標系: `Mouse.NormalizedWindowPosition`、proto は正規化 \[0,1\] (中央 0.5,0.5)、範囲チェックは Service 層 (`InvalidArgument`)。`Release` は冪等 (未保持でも成功し現 state を返す)。
- 実機検証 (2026-06-10 Wine): set → cross-RPC get で位置維持 (held=True)、release で OS 追従へ復帰、context-menu が保持位置に開く、e2e green。

関連: [froox_contextmenu_reflection.md](agents/spec-driven-implementer/froox_contextmenu_reflection.md)、[engine_cursor_lock_quirks.md](agents/spec-driven-implementer/engine_cursor_lock_quirks.md)。
