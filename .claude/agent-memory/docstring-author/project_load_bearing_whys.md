---
name: load-bearing-whys
description: Non-obvious WHY comments under mod/ and Core tests that must survive future docstring trim passes (Step 2 + Step 3 + Camera v2 surface)
metadata:
  type: project
---

When trimming docstrings/comments under `mod/src/ResoniteIO{,.Core,.Renderer,.RendererShared}/` and
`mod/tests/ResoniteIO.Core.Tests/`, these WHY notes are load-bearing and
must NOT be cut. Items 1–5 originate from Step 2 (Session / loader);
items 6–9 originate from Step 3 (Camera v1, since removed at `ff44bf8`
but the WHY patterns recurred in v2); items 10–14 originate from
Camera v2 (renderer process bridge, `mod/src/ResoniteIO.Renderer/` +
`mod/src/ResoniteIO.RendererShared/` + `PushedFrameCameraBridge` +
`RendererFrameInterprocessReceiver` + `FrooxEngineDisplayBridge`).

01. **Google.Protobuf early-resolution hazard**
    - `ResoniteIOPlugin.Load`: must not touch any `ResoniteIO.Core` type
      before `PluginAssemblyResolver` is attached, or Resonite's bundled
      old Google.Protobuf wins resolution and SessionHost fails with
      `TypeLoadException: Could not load type 'Google.Protobuf.IBufferMessage'`.
    - `PluginAssemblyResolver`: takes `ManualLogSource` directly instead
      of `ILogSink` for the same reason (Core dll must not preload).
02. **Sync<string> tearing tolerance** in `FrooxEngineSessionBridge`:
    getters can be read from any thread because the underlying values are
    reference-typed publishes via `Sync<string>` — tearing yields a stale
    ref, never a crash.
03. **`[Collection("SessionHostEnv")]`** on RoundTrip / Lifecycle /
    BridgeWiring **and CameraRoundTrip** tests: `SessionHostHarness`
    mutates the `RESONITE_IO_SOCKET` env var, so any test using the
    harness must serialize via this collection (extended in Step 3 to
    cover Camera tests too).
04. **`csproj` `CopyLocalLockFileAssemblies` + explicit `Microsoft.AspNetCore.*`
    copy + `CopyAspNetCoreSharedFrameworkRuntime` Target** in
    `ResoniteIO.csproj`: required to ship the adjacent DLLs that
    `PluginAssemblyResolver` then probes. The shared-framework copy
    Target is the canonical workaround for AspNetCore framework
    references and must stay paired with the PluginFiles glob — see
    \[\[bepinex-mod-transitive-dlls\]\]. Comments there are out of scope
    for the docstring agent — leave them entirely.
05. **`betterproto2_compiler` separate distribution** in Python deps:
    not a `[compiler]` extra — keep any comment explaining that.
06. **`ICameraBridge` optional DI** in `CameraService`: a `null` bridge
    returns `Status.Unavailable` so Core can be tested without a Bridge
    and camera-less engine configs still load. Keep the remark.
07. **Engine-thread dispatch in `FrooxEngineCameraBridge`**: component
    graph mutations (`AttachComponent`, `Slot.AddSlot` etc.) MUST go
    through `World.RunSynchronously` + `TaskCompletionSource`; pure reads
    (volatile snapshots) do not. Don't strip the comment explaining this
    asymmetry — see \[\[bridge-engine-thread-dispatch\]\].
08. **ProcessExit swallowing in Camera bridge** (`FrooxEngineCameraBridge.cs`
    `OnProcessExit`): `RunSynchronously` becomes a no-op after engine
    shutdown, so exceptions are intentionally drunk. Keep that note —
    it documents an intentional best-effort path tied to
    \[\[engine-onshutdown-deferred\]\].
09. **BGRA8 → RGBA8 conversion rationale** in the Camera bridge: the
    swap was made because raw BGRA8 readback caused a blue tint
    (commit `5129bb6`). Any comment near the conversion site that
    explains this must stay. (NOTE: Camera v1 was removed at
    `ff44bf8`; this item now applies to v2 `FrameCapture` which
    already uses `TextureFormat.RGBA32` directly, so no conversion
    site remains — keep the item here for archival reference.)
10. **`FrameHeader` magic / layout byte-for-byte** (`mod/src/ResoniteIO.RendererShared/FrameHeader.cs`):
    the `byte layout` table in the class XML doc is the canonical
    binary contract between renderer (Wine Mono, net472) and engine
    (.NET 10). Any change to the offset/size table here is a
    breaking IPC schema change — keep the layout block intact and
    update offsets atomically with `Read`/`Write` if ever modified.
11. **`IpcSocketPaths.QueueCapacityBytes = 32 MiB`** rationale: the
    default InterprocessLib capacity is 1 MiB, which cannot hold a
    single 1118×651 RGBA8 frame (~2.9 MiB). The const comment in
    `IpcSocketPaths.cs` and the `FrameSender` constructor comment
    are tied — preserve both. See \[\[camera-v2-constraints\]\] §6.
12. **`PushedFrameCameraBridge` cap=1 + DropOldest** (`mod/src/ResoniteIO.Core/Bridge/PushedFrameCameraBridge.cs`):
    "silent drop is intentional, do not log per frame" + "the
    width/height args are ignored, renderer dictates resolution"
    are both load-bearing. Stripping either invites future callers
    to add logging that floods at 60 fps or to mistake the args for
    a request that actually constrains output.
13. **Static event leak hazard** (`RendererFrameInterprocessReceiver` +
    `FrameSender`): `Messenger.OnFailure` / `OnWarning` are static
    events; the `-=` in Dispose is the only way to let the
    Messenger instance GC. Both sites carry a comment pointing at
    "knowledge §7 / camera-v2-constraints §6" — keep them. Removing
    the comment will let a future refactor merge the subscribe and
    `new Messenger` lines and lose the unsubscribe entirely.
14. **`FrooxEngineDisplayBridge` MaximumBackgroundFramerate caveat**
    (`mod/src/ResoniteIO/Bridge/FrooxEngineDisplayBridge.cs`):
    the long XML remarks explain that engine public API does NOT
    expose foreground fps and that `MaxFps` therefore maps to the
    *background* cap. This is a footgun for callers who expect
    `DisplayClient.apply(max_fps=120)` to raise foreground fps —
    keep the entire remarks block; see \[\[camera-v2-constraints\]\] §9.

**Why:** these WHYs explain non-local behaviour: changing one site
(removing the resolver, dropping the collection, swapping the channel
order back, etc.) silently breaks another. The codebase is still young
(Steps 2-3) so the bug stories aren't in git blame depth yet.

**How to apply:** if a future docstring/comment pass touches these
files, preserve these notes — compress wording, never drop the
substance. When Step 4+ adds new bridges, append a new section here
rather than rewriting earlier entries.
