---
name: engine-cursor-lock-quirks
description: FrooxEngine cursor-lock / CollectOutputState の API 癖 (Harmony postfix 実装時の落とし穴)
type: project
---

FrooxEngine cursor-lock 周りの decompiled で裏取り済みの癖 (2026-06 時点):

- `InputBindingManager.RegisterCursorLock(element, position, priority)` は **priority 引数を CursorLock に反映しない** (position のみ設定、decompiled InputBindingManager.cs:182-192)。priority を効かせたいときは戻り値の public field `cursorLock.priority` へ明示的に書き込む。
- `InputInterface.CollectOutputState` の戻り値 `Renderite.Shared.OutputState` は **class** (IMemoryPackable)。Harmony Postfix は `OutputState __result` で受けて field (`lockCursor` / `lockCursorPosition`) を直接 mutate できる。`ref` 受け不要。
- `Renderite.Shared.dll` は `mod/src/ResoniteIO/ResoniteIO.csproj` で参照済み — Bridge 層から OutputState を直接触れる。
- `lockCursorPosition` だけ null 化すると renderer 側 `MouseDriver.HandleStateUpdate` が `CursorLockMode.Locked` (中央 pin) に落ちる。`lockCursor` も「自 lock 抜きの世界線」で再計算する必要がある (式: `!anyUnlocker && IsWindowFocused`、InputInterface.cs:627-632)。
- `InputBindingManager._cursorUnlockers` (HashSet) / `_cursorLockers` (Dictionary\<IWorldElement, CursorLock>) は private。`AccessTools.FieldRefAccess` で読む。public getter `UnlockCursor` は自 lock の存在で false に化けるため偽装再計算には使えない。

**Why:** Cursor 持続保持 (Part A) 実装時にこれらを decompiled で確認した。priority 無視は既存コードのコメントと食い違う罠。

**How to apply:** cursor lock / Harmony postfix / OutputState を触る実装の前に decompiled で再確認しつつ、ここを出発点にする。
