---
name: engine-dispatch-helper
description: Mod 層の RunOnEngineAsync ボイラープレートは EngineDispatch (World 拡張メソッド) に集約済み。統一ポリシーと例外。
metadata:
  type: project
---

各 `FrooxEngine<Modality>Bridge` が個別に持っていた `RunOnEngineAsync`
(TCS/RunSynchronously/ct.Register) は `mod/src/ResoniteIO/Bridge/EngineDispatch.cs`
の `World` 拡張メソッド 2 本 (`Func<T>` 版 / `Action` 版) に集約済み。

**統一ポリシー (新規 Bridge もこれに従う):**

- `TaskCreationOptions.RunContinuationsAsynchronously` を必ず付ける。TCS 完了は
  engine update thread 上で起きるので、無指定だと continuation が engine thread に
  inline 実行され tick を塞ぐ。
- 完了は `TrySetResult`/`TrySetException`/`TrySetCanceled` で統一。`SetResult` 系
  (Try なし) は ct cancel で `TrySetCanceled` 成立後に deferred engine action が走ると
  engine thread 上で `InvalidOperationException` を投げる latent race を持つ。

**移行済み:** ContextMenu / Manipulation (static helper 削除 → `ResolveWorld().RunOnEngineAsync(...)`)、
Dash / Cursor / World (instance wrapper を `=> ResolveWorld().RunOnEngineAsync(fn, ct)` 1 行へ)。
Action 版を使うと engine ブロックのダミー `return true;` を除去できる
(`FocusWorld` のような void engine API)。

**スコープ外 (別形状なので畳まない):** Inventory Bridge (Slot.StartTask + 専用 TCS)、
Locomotion の per-frame repeater、Cursor の Dispose (fire-and-forget)。

**How to apply:** 新規モダリティ Bridge では自前 `RunOnEngineAsync` を書かず
`world.RunOnEngineAsync(fn, ct)` を呼ぶ。class-level XML doc の cref は
`<see cref="EngineDispatch.RunOnEngineAsync{T}"/>` を指す (自前 method 削除時に
dangling cref CS1574 で warnings-as-errors が落ちるので注意)。
