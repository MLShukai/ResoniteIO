---
name: feedback-cursor-lock-mechanism
description: Cursor set は one-shot warp (SetMousePosition + 一時 cursor lock → 即 release) で位置を保持しない。Wine の menu-at-cursor は同一操作内のみ有効
type: project
---

Cursor モダリティ (`FrooxEngineCursorBridge`) の `SetPosition` は **one-shot warp** で実装する: engine thread 上で (a) `InputInterface.SetMousePosition` による OS カーソル warp (native では実カーソルが移動し位置が残る、Wine/Proton では `IsInputInjectionSupported=False` で no-op) と (b) `InputBindingManager.RegisterCursorLock` による一時 lock を併用し、settle (反映) を確認したら **RPC が戻る前に必ず `UnregisterCursorLock`** する。**RPC を跨いで lock を保持しない** (「カーソルをその位置に保持する」副作用は廃止)。

**Why:** 旧実装は lock を永続保持していた (解放 API なし) ため、`Mouse.Update` が毎フレーム `WindowPosition` を `CursorLockPosition` へ強制し (decompiled/.../Mouse.cs:67-71)、Resonite フォーカス中はマウスが掴まれ他アプリを操作できなかった。一時 lock を残すのは、laser / pointer / context menu が参照する `Mouse.WindowPosition` は OS injection の round-trip でしか動かず Wine では `SetMousePosition` が no-op のため、engine 内で確実に反映させる経路が lock しかないから。Locomotion が SendInput でなく ExternalInput を使うのと同じ思想。

**How to apply:**

- warp: `world.InputInterface.SetMousePosition(in pixel)`。native では実 OS カーソルが動くので call 後も位置が残る。Wine/Proton では no-op (2026-06-06 実機検証: `IsInputInjectionSupported=False`)。
- 一時 lock: `world.Input.RegisterCursorLock(world.RootSlot, pixelInt2, priority)`。同一 element 二重登録は例外を投げる → 登録前に `UnregisterCursorLock(element)` (idempotent) を一度呼ぶ。priority は最大の locker が勝つ (`LockCursor` getter) ので mouse-look 等に勝てるよう高めにする (実装では 1_000_000)。settle 確認 (16ms × 最大 20 回 poll) 後、timeout / cancel を含むあらゆる経路で `finally` から `world.RunSynchronously(UnregisterCursorLock)` を queue して解放する (完了は await しない。engine 終了時は world ごと破棄され leak は無害)。
- **位置は保持されない**: Wine では lock 解放後の次フレームで `WindowPosition` が実 OS カーソル位置へ戻るため、別 RPC の後続 `get_position` が set 値を返すとは限らない。menu-at-cursor (中央表示のための `set_position(0.5, 0.5)` → `context_menu.open()`) は **同一操作内 (warp が効いている間) でのみ有効** — このリスクはユーザー許容済み (2026-06-10、マウストラップ解消を優先)。
- auto-close は従来どおり agent では発火しない: `ContextMenu` の exit-lerp (live cursor 距離で閉じる) は実 OS カーソル (active screen pointer) を要求し、lock の forced position は active pointer と見なされない。agent は `close()` で明示的に閉じる。
- 読み取り: `world.InputInterface.Mouse.NormalizedWindowPosition` (= `WindowPosition.Value / WindowResolution`)。proto/Client では正規化 \[0,1\] (中央 0.5,0.5)、bridge が `pixel = clamp(round(norm * resolution), 0, resolution-1)` で変換。範囲チェックは Service 層 (`InvalidArgument`)。
- 座標系の原点 (上下左右) は engine ネイティブ window 座標に従う。実機の正確な対応は e2e (`python/tests/e2e/cursor.py`) で context menu の出現位置を observable proxy にして確認する。
- bridge は跨 RPC 状態を持たないため `Dispose` は実質 no-op (plugin の SafeDispose 対称性のため `IDisposable` は維持)。

関連: [froox_contextmenu_reflection.md](agents/spec-driven-implementer/froox_contextmenu_reflection.md) (ContextMenu は engine-native 配置へ移行、中央表示は事前 `cursor.set_position(0.5,0.5)`、auto-close は agent では発火しない)。
