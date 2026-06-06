---
name: reference-dash-uix-engine-api
description: FrooxEngine dash (UserspaceRadiantDash) + UIX engine API call shapes verified from decompiled/, for Mod bridge work
metadata:
  type: reference
---

Verified engine-API shapes for the Dash modality Mod bridge (`FrooxEngineDashBridge`), sourced from gitignored `decompiled/` (ILSpy output). Re-grep `decompiled/` before relying on these — they can drift across Resonite versions.

**Dash resolution (userspace overlay):**

- `FrooxEngine.Userspace.UserspaceWorld` — static `World`, `=> thisobj?.World` (can be null).
- `world.GetGloballyRegisteredComponent<UserspaceRadiantDash>()` — may be null pre-init.
- `UserspaceRadiantDash.Open` — `bool` get/set; setter is a no-op when `BlockOpenClose.Value` is true.
- `UserspaceRadiantDash.OpenLerp` — `float` (`=> _dash.Target.LocalShowLerp`).
- `UserspaceRadiantDash.Dash` — the `RadiantDash`.
- `RadiantDash.CurrentScreen.Target` → `RadiantDashScreen`; `.ScreenRoot` is a `Slot`. Fallback enumerate root: `RadiantDash.VisualsRoot` (`Slot`).

**UIX tree walk:**

- Element = `Slot` with `slot.GetComponent<FrooxEngine.UIX.RectTransform>()`.
- `RectTransform.ComputeGlobalComputeRect()` → `Elements.Core.Rect`; use `rect.position.x/.y`, `rect.size.x/.y` (also `rect.x/y/width/height`).
- Type probe order: `Button` → `ScrollRect` → `Text` → `Image` → else "RectTransform" (all `FrooxEngine.UIX`).
- Label: `Button.Label` returns `Text` (`GetComponentInChildren<Text>()`); else `slot.GetComponentInChildren<Text>()`. `Text.Content` is `Sync<string>` (implements `IField<string>`).
- Locale key: `FrooxEngine.LocaleHelper.GetLocalizedDriver(text.Content)` → `LocaleStringDriver`; `.Key` is `Sync<string>`. NOTE: `LocaleHelper` is ambiguous between `Elements.Core` and `FrooxEngine` when both namespaces are imported — fully-qualify `FrooxEngine.LocaleHelper`. Only the FrooxEngine one has `GetLocalizedDriver`.
- Interactable: `slot.GetComponent<IUIInteractable>()` non-null AND `.Enabled` true. `IUIInteractable : IComponent : IComponentBase` so `.Enabled` is on the interface directly (no cast needed).
- `world.InputInterface?.WindowResolution` → `Elements.Core.int2` (`.x/.y`, readonly fields; `int2.Zero` exists). `World.InputInterface => Engine.InputInterface`.

**RefID resolution (no exceptions):** `Elements.Core.RefID.TryParse(string, out RefID)` (avoid `Parse`, which throws). Then `world.ReferenceController.GetObjectOrNull(in refid)` → `IWorldElement?`; cast `is Slot`. (`World.ReferenceController` is a public property.)

**Invoke (button press):** `Button.SimulatePress(float duration, ButtonEventData)`. `ButtonEventData(Component pressSource, in float3 globalPressPoint, in float2 localPressPoint, in float2 normalizedPressPoint)` (readonly struct). Center point: `button.RectTransform.Canvas.Slot.LocalPointToGlobal(in float3.Zero)`.

**Highlight (hover):** `slot.GetComponent<InteractionElement>()` (Button's base); set `element.IsHovering.Value = true` (`Sync<bool>`).

**Scroll:** `slot.GetComponent<ScrollRect>() ?? slot.GetComponentInParents<ScrollRect>()`; `scroll.NormalizedPosition` is `Sync<float2>`; clamp with `Elements.Core.MathX.Clamp01(in float2)`.

Behavioral verification (real Resonite) was NOT possible in the build container — this is compile-correct best-effort. Rect screen-pixel reprojection is unimplemented (returns canvas space, `IsScreenSpace=false`).
