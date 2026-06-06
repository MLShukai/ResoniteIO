---
name: froox-contextmenu-reflection
description: FrooxEngine ContextMenu / InteractionHandler reflection signatures and gotchas for the ContextMenu modality bridge
type: project
---

ContextMenu modality bridge (`FrooxEngineContextMenuBridge`) relies on private FrooxEngine internals — verify against `decompiled/FrooxEngine/FrooxEngine/InteractionHandler.cs` after any Resonite update.

**Why:** opening a *populated* radial menu (T-key standard items) is only possible via the private `InteractionHandler.OpenContextMenu(MenuOptions.Default)`; public `OpenMenu` opens an empty ring.

**How to apply:**

- `InteractionHandler.MenuOptions` is a `private` **nested enum**: resolve with `typeof(InteractionHandler).GetNestedType("MenuOptions", BindingFlags.NonPublic)`. Values: `{ Default, Locomotion, Grabbing, LaserGrab, HandGrab }`, so `Default == 0`.
- Method: `private void OpenContextMenu(MenuOptions options, float? speedOverride = null)`. Resolve with `BindingFlags.Instance|NonPublic`, param types `[menuOptionsType, typeof(float?)]`. Invoke with `new object?[] { defaultValue, null }`.
- All other ops are public: `handler.IsContextMenuOpen`, `handler.ContextMenu.Target` (`SyncRef<ContextMenu>`), `handler.CloseContextMenu()`, `ContextMenu.MenuState` (enum `State { Closed, Opening, Opened }`), `ContextMenu.Close()`, `ContextMenu.Canvas` (public).
- Items: `menu.Slot.GetComponentsInChildren<ContextMenuItem>()` returns `List<T>` in arc/child order. Per item: `LabelText` (string, may be null), `Color` (`Sync<colorX>`; `.Value.r/.g/.b/.a`), `Button` (may be null), `HasSprite` (bool), `Button.Enabled`, `Highlight` (`Sync<bool>`), `SetHighlighted()`/`ClearHighlighted()`.
- Invoke = press like `ContextMenu.PressMenuItem`: `button.SimulatePress(0.1f, new ButtonEventData(menu, in globalPoint, in localPress, in localPress))` where `globalPoint = menu.Canvas.Slot.LocalPointToGlobal(in localZero)`.
- `ButtonEventData` ctor: `(Component pressSource, in float3 globalPressPoint, in float2 localPressPoint, in float2 normalizedPressPoint)`. The `in` params at a call site need lvalues — store `float3.Zero`/`float2.Zero` in locals first (passing a property/rvalue with explicit `in` is a compile error).
- Hand → `Renderite.Shared.Chirality { Left, Right }` (sbyte enum). Primary = `world.InputInterface.PrimaryHand` (fallback `Chirality.Right`). `world.LocalUser.GetInteractionHandler(side)` (extension in `InteractionHandlerExtensions`).
- Open is async (Opening→Opened + item generation): trigger once on engine thread, then poll `IsContextMenuOpen && menu.MenuState == State.Opened` with real `Task.Delay` between `World.RunSynchronously` checks (do not busy-spin engine thread). Bridge holds no per-instance resources (reflection cached static) → not IDisposable.

Namespace collision: Core namespace `ResoniteIO.Core.ContextMenu` vs FrooxEngine type `FrooxEngine.ContextMenu` — alias `using FrooxContextMenu = FrooxEngine.ContextMenu;` and `using FrooxContextMenuItem = FrooxEngine.ContextMenuItem;`.

**配置は engine-native (2026-06-06 更新):** 旧実装はメニューを手動で view-forward へ再配置し `menu.Pointer.Target = null!` で exit-lerp を無効化していた。現在は `OpenAsync` / `InvokeAsync` とも open → `WaitForOpenedAsync` → `ReadState` のみで、配置 (`InteractionHandler.PositionContextMenu` の desktop 分岐 = laser のヒット点) を engine に委ねる。`open` は **現カーソル位置** に開く。中央に出したいときは事前に Cursor モダリティ (`cursor.set_position(0.5,0.5)`) でカーソルを中央へ寄せる — カーソルが起動直後に左下 (正規化 0.0,1.0) にあるのが「メニューが中央に出ない」根本原因だった。

**auto-close (視点移動で閉じる) は agent では発火しない (2026-06-06 実機検証):** `Pointer.Target` を戻したので exit-lerp 経路自体は active (`pointerTargetNull=False` / `screenActive=True` を実機確認)。だが exit-lerp は **実 OS カーソル (active screen pointer)** の距離で閉じる。Wine では OS injection 不可 (`IsInputInjectionSupported=False` を実機確認) で、Cursor モダリティの cursor lock が forced する WindowPosition は active pointer と扱われないため、視点を回しても (menu は world-anchored で画面端までスライドするが) 閉じない。agent は `close()` で明示的に閉じる。機構詳細は [feedback_cursor_lock_mechanism.md](../../feedback_cursor_lock_mechanism.md)。
