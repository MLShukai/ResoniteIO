---
name: project-dash-tabs-controls-modality
description: Dash modality rewritten from screens to tab-bar + controls (wire-breaking). New proto/Core/Python surface; old ListScreens/SetScreen/GetTree/DashTree/DashScreen/DashRect/DashElement all removed.
metadata:
  type: project
---

The Dash modality was **rewritten wire-breaking** (plan
`claude-resoio-dash-snug-lemur.md`, branch `refactor/20260613/dash-overhaul`,
~2026-06-13). Alpha, no users, so the whole modality changed shape.

**Removed (do NOT pin these any more):** `GetTree`/`DashTree`/`DashElement`/
`DashRect` (the canvas-space rect, depth-over-all-slots, screen_width/height,
interactable_only/root_ref_id filters) AND `ListScreens`/`SetScreen`/
`DashScreen`/`DashScreenList`. The earlier "screens" iteration this memory used
to describe is gone.

**New proto contract — service `Dash`, 9 unary RPCs:**
`Open/Close/GetState -> DashState{is_open,open_lerp}`,
`ListTabs -> DashTabList{repeated DashTab}`,
`SetTab(DashSetTabRequest{ref_id,locale_key}) -> DashActionResult` (ref_id first,
else locale_key, **both-empty -> InvalidArgument** at the Service layer),
`ListControls(DashListControlsRequest{include_disabled}) -> DashControlList`
(always the CURRENT tab),
`Invoke/Scroll/Highlight(... {ref_id [,delta_x,delta_y]}) -> DashActionResult`.

- `DashTab{ref_id,locale_key,name,label,is_current,enabled}`
- `DashControl{ref_id,control_type("button"|"scroll"),label,locale_key,enabled,parent_ref_id,depth}`
- `DashActionResult{ok,found,ref_id,detail}` (unchanged soft-fail shape).

`ListControls` `include_disabled` toggles whether disabled controls are
returned (default lists only enabled; so `find_control`/`*_by_label` only see
enabled controls).

**Python client surface** (`resoio.dash`, all in `__all__`): dataclasses
`DashState/DashTab/DashControl/DashActionResult`; errors `DashNoMatchError` &
`DashAmbiguousMatchError` (both `ValueError`); `DashClient` with the 9 RPC methods

- client-side helpers `find_tab/set_tab_by_label/find_control/invoke_by_label/ scroll_by_label/highlight_by_label`; module-level `_resolve_one(items,query,keys)`
  and key extractors `_tab_keys`(ref_id,locale_key,name,label) /
  `_control_keys`(ref_id,locale_key,label). `set_tab` is the only client-side
  both-empty `ValueError` (raised BEFORE any RPC).

**How to apply (test scope):**

- Python client tests live in `python/tests/resoio/test_dash.py` — rewritten to
  the new contract (real grpclib+UDS via `uds_server`, inline `_FakeDash(DashBase)`,
  37 tests). Pattern: distinct field values per row, button+scroll control rows
  with locale_key set/empty + non-trivial parent_ref_id/depth, mutating fakes echo
  the arrived selector back as result `ref_id` to prove wire forwarding.
- C# Core tests `Dash/DashServiceTests.cs` + `Common/Fakes/DashBridgeFake.cs` and
  the `ApiContractTests.cs` Dash pins must be rewritten to the new type set
  (tabs/controls). The old Ordinal-placement notes for DashScreen\*/DashRect\* are
  obsolete.
- See \[\[resolver-substring-ambiguity-tests\]\] before writing `_resolve_one` tests.
- Related: \[\[project-context-menu-modality\]\] (same unary-RPC modality shape).
