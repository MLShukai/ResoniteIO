---
name: feedback-cursor-lock-mechanism
description: Cursor モダリティが desktop カーソルを動かす機構 (cursor lock) と、OS injection を使わない理由
type: project
---

Cursor モダリティ (`FrooxEngineCursorBridge`) は desktop カーソル位置を **cursor lock** で設定する。OS レベルのマウス injection (`InputInterface.SetMousePosition` → `WindowsInputInjector`) は使わない。

**Why:** laser / pointer / context menu が参照するのは `Mouse.WindowPosition`。これは `Mouse.Update` が毎フレーム OS のマウス状態で上書きするため、`SetMousePosition` の効果は OS injection が round-trip して初めて反映される (Wine/Proton で効くか不確実)。対して `InputBindingManager.RegisterCursorLock(element, pixel, priority)` で lock を張ると、`Mouse.Update` が `CursorLockPosition.HasValue` のとき毎フレーム `WindowPosition` をその値へ強制する (decompiled/.../Mouse.cs:67-71) ので、OS 往復なしに engine 内で完結する。Locomotion が SendInput でなく ExternalInput を使うのと同じ思想。

**How to apply:**

- 位置設定: `world.Input.RegisterCursorLock(world.RootSlot, pixelInt2, priority)`。返る `CursorLock { int priority; int2 position; }` の `position` は public mutable なので、同一 world での更新は再登録せず `cursorLock.position = newPixel` で足りる。world 切替時は旧 element を `UnregisterCursorLock` してから張り直す。
- `RegisterCursorLock` は同一 element 二重登録で例外を投げる → 登録前に `UnregisterCursorLock(element)` (idempotent) を一度呼ぶ。element が `IsRemoved` になると `InputBindingManager.Update` が自動で外す。
- priority は最大の locker が勝つ (`LockCursor` getter) ので、mouse-look 等に勝てるよう高めにする (実装では 1_000_000)。
- lock は「カーソルをそこに保持する」副作用を持つが、これは context menu を開いたまま視点移動で exit-lerp 自動クローズを arming させるのに必要な性質でもある。bridge は `IDisposable` にして Dispose で `world.RunSynchronously(UnregisterCursorLock)` を best-effort 実行 (engine 終了時は world ごと破棄され leak は無害)。
- 読み取り: `world.InputInterface.Mouse.NormalizedWindowPosition` (= `WindowPosition.Value / WindowResolution`)。proto/Client では正規化 \[0,1\] (中央 0.5,0.5)、bridge が `pixel = clamp(round(norm * resolution), 0, resolution-1)` で変換。範囲チェックは Service 層 (`InvalidArgument`)。
- 座標系の原点 (上下左右) は engine ネイティブ window 座標に従う。実機の正確な対応は e2e (`python/tests/e2e/cursor.py`) で context menu の出現位置を observable proxy にして確認する。

関連: \[\[froox-contextmenu-reflection\]\] (ContextMenu は engine-native 配置へ移行し、中央表示は事前 `cursor.set_position(0.5,0.5)`)。
