---
name: project-dash-screens-modality
description: Dash screen enumerate/navigate (ListScreens/SetScreen) C# Core test scope — round-trip pins, both-empty InvalidArgument, ApiContract Ordinal placement
metadata:
  type: project
---

Dash modality gained screen enumeration/navigation: proto `ListScreens(DashListScreensRequest)->DashScreenList` and `SetScreen(DashSetScreenRequest)->DashActionResult` (reuses existing `DashActionResult`). Core POCOs `DashScreenSnapshot(RefId,Key,Name,Label,IsCurrent,Enabled)` + `DashScreenListSnapshot(IReadOnlyList<DashScreenSnapshot>)`. IF methods `ListScreensAsync(ct)` / `SetScreenAsync(refId,key,ct)`.

**Why:** language-independent screen IDs (LocaleStringDriver key e.g. `Dash.Screens.Worlds` + RefId) so agents enumerate/navigate dash tabs without localized text.

**How to apply (test scope already written in `Dash/DashServiceTests.cs`, `Common/Fakes/DashBridgeFake.cs`, `ApiContractTests.cs`):**

- Frozen behavior contracts (spec `/tmp/dash_screens_spec.md` §8.5): SetScreen ref_id/key **both-empty → InvalidArgument** at Service layer (D1, bridge NOT called — assert `bridge.Calls` empty). disabled screen → `ok=true, detail="screen disabled"` (D2). not-found → `ok=false,found=false,ref_id="",detail="screen not found"`. ref_id-priority resolution. ListScreens works even when dash closed.
- `DashBridgeFake.Call` record: added `Key` as **trailing `string? Key = null`** so all existing `Call(...)` constructions (named-arg style) still compile. `NextScreenList` property + `ListScreensAsync`/`SetScreenAsync` implemented mirroring existing record/record-result helpers.
- ApiContract Ordinal subtlety (StringComparer.Ordinal, char-by-char): for `ResoniteIO.V1.*` snapshot, `DashScreen` \< `DashScreenList` \< `DashScrollRequest` ("Screen" vs "Scroll": 'e'\<'o'), `DashSetScreenRequest` after `DashScrollRequest` ("Se">"Sc") before `DashState` ("Set"\<"Sta"), `DashListScreensRequest` between `DashInvokeRequest` and `DashOpenRequest`. Core types: `DashScreenListSnapshot` \< `DashScreenSnapshot` (prefix rule), both between `DashRectSnapshot` and `DashService`.
- Implementer completed IF+Service+proto in parallel, so all 24 Dash tests + 17 ApiContract + full 131 Core.Tests went green immediately. Related: \[\[project-context-menu-modality\]\].
