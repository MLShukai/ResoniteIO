---
name: load-bearing-whys
description: Non-obvious WHY comments under mod/ + python/ and Core tests that must survive future docstring trim passes (Step 2 + Step 3 + Camera v2 + Step 4 Locomotion + Step 5 Speaker + Step 7 Microphone surface)
metadata:
  type: project
---

When trimming docstrings/comments under `mod/src/ResoniteIO{,.Core,.Renderer,.RendererShared}/`,
`mod/tests/ResoniteIO.Core.Tests/`, and `python/src/resoio/`, these WHY notes
are load-bearing and must NOT be cut.

- Items 1–5 originate from Step 2 (Session / loader).
- Items 6–9 originate from Step 3 (Camera v1, since removed at `ff44bf8`
  but the WHY patterns recurred in v2).
- Items 10–14 originate from Camera v2 (renderer process bridge under
  `mod/src/ResoniteIO.Renderer/` and `mod/src/ResoniteIO.RendererShared/`,
  plus `PushedFrameCameraBridge`, `RendererFrameInterprocessReceiver`,
  and `FrooxEngineDisplayBridge`).
- Items 15–18 originate from Step 4 (Locomotion: proto velocity
  semantics, Bridge sign-flip, Service round-trip assertion, Move
  body-local rotation via HeadFacingRotation).
- Items 19–24 originate from Step 5 (Speaker:
  PushedAudioFrameSpeakerBridge DropWrite policy, HarmonyLib Postfix
  on `AudioOutputDriver.AudioFrameRendered`, WASAPI thread hot path,
  Dispose / SafeShutdown ordering, WAV writer stdlib-rejection
  rationale).
- Items 25–29 originate from Step 7 (Microphone: virtual AudioInput
  Unregister-API-missing decompile finding, must-not-throw contract
  on `NotifyDisconnect`, RL-safety ring-buffer clear policy, `wave`
  sampwidth=4-is-float32 commitment, fixed-mono-wire rationale).

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
12. **`PushedFrameCameraBridge` cap=1 + DropOldest** (`mod/src/ResoniteIO.Core/Camera/PushedFrameCameraBridge.cs`):
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
15. **Locomotion velocity semantics canon = proto field comment**
    (`proto/resonite_io/v1/locomotion.proto`, `LocomotionCommand.velocity`):
    the field doc states "単位元は 1.0、Python `LocomotionCmd` で
    default=1.0 を保証、Bridge は素のまま掛ける (再解釈なし)、raw proto
    で未指定だと wire default 0 で Move が 0 倍される" — this is the
    **single canonical surface**. The Bridge inline comment in
    `FrooxEngineLocomotionBridge.ApplyAsync` (just above
    `Move.ExternalInput = new float3(MoveX * Velocity, 0, MoveY * Velocity)`)
    points back at this proto comment rather than repeating it.
    All other surfaces (Python `LocomotionCmd` docstring,
    `ILocomotionBridge` POCO remarks, `mod/tests/manual/locomotion-e2e.md`
    v0 section, e2e `_scenario_command`) deliberately defer to proto.
    Do NOT reintroduce a wire-side 0→1.0 fallback in the Bridge —
    it was removed at `d195212` precisely to keep proto value and
    applied multiplier in 1:1 correspondence.
16. **Pitch sign on Locomotion Bridge: NO flip (2026-05-19)**. Earlier
    decompile reading of `_verticalAngle -= y` led to a Bridge-side
    `-PitchRate`, but live test showed the inverted behaviour and the
    flip was removed. The inline comment above
    `screenInputs.Look.ExternalInput = new float2(snapshot.YawRate, snapshot.PitchRate)`
    in `FrooxEngineLocomotionBridge.ApplyToEngine` documents the
    decompile-vs-runtime mismatch — keep it. If a future refactor
    re-introduces `-PitchRate` "to match decompile", that is a
    regression of this fix. Proto contract (positive = look up) is
    unchanged.
17. **`Drive` test proto3-default round-trip assertion**
    (`mod/tests/ResoniteIO.Core.Tests/Locomotion/LocomotionRoundTripTests.cs`,
    "Service は proto.Velocity を素のまま POCO に詰めるだけ" comment):
    explains why `received[0].Velocity == 0f` (not `1f`) — the
    Service is a pure proto→POCO mapper and the convenience-side
    default lives in Python `LocomotionCmd`. Without this comment
    the assertion looks contradictory to the proto field doc which
    states the unit value is 1.0.
18. **Move body-local rotation via `HeadFacingRotation`** in
    `FrooxEngineLocomotionBridge.ApplyToEngine`: `Move.ExternalInput`
    is interpreted in `UserRoot.Slot` coordinates, not world. A naive
    world-axis write (`new float3(MoveX, 0, MoveY)`) silently produces
    world-fixed locomotion that ignores head yaw — the e2e RPC still
    completes, but the avatar walks in the wrong direction (2026-05-19
    bug). The block computing `headRot * float3.Forward` /
    `Slot.GlobalDirectionToLocal` and the comment above it pointing at
    `feedback_locomotion_external_input.md` §8 are load-bearing — they
    document why the `HeadFacingRotation` indirection exists and the
    quantitative 87.1° verification that locked it in. Removing the
    rotation, or switching to `LocalUserViewRotation` without
    accounting for pitch sink, regresses the fix. Proto contract is
    unchanged (MoveX = Strafe / Right axis, MoveY = Forward axis).
19. **`PushedAudioFrameSpeakerBridge` cap=32 + `DropWrite`**
    (`mod/src/ResoniteIO.Core/Speaker/PushedAudioFrameSpeakerBridge.cs`):
    cap=32 ≈ 680 ms buffer at typical 1024-sample/21 ms @ 48 kHz
    frames; `DropWrite` (drop the *new* frame on overflow) is preferred
    over `DropOldest` so the recent waveform continuity is preserved
    when a consumer stalls. The XML remarks paragraph carrying this
    rationale and the "DropWrite なので満杯でも TryWrite は true を返す"
    inline comment are load-bearing — without them a future refactor
    will assume `TryWrite == false` indicates overflow (it only ever
    means Writer.Complete) and add log spam, or flip to DropOldest and
    silently change the audible behaviour on overload.
20. **`AudioOutputDriver.RenderAudio` direct-assign hazard /
    HarmonyLib Postfix tap** in `FrooxEngineSpeakerBridge`: the engine
    `RenderAudio` Action is `direct assign`-ed by `AudioSystem`, not an
    event — subscribing via `+=` overwrites engine state and breaks
    audio. The class XML remarks `<list>` and the file header comment
    documenting why HarmonyLib Postfix on `AudioOutputDriver.AudioFrameRendered`
    is the only safe tap, plus the four bullet points covering
    `PrimaryOutput`-only target / base-class patch + derived inheritance /
    static singleton constraint / `DefaultAudioOutputChanged` re-attach,
    are all load-bearing. Removing any of them invites a future PR to
    "simplify" by adopting the `RenderAudio` direct assign or by
    patching a derived driver class.
21. **Postfix runs on WASAPI audio thread — no log, swallow exceptions**
    (`FrooxEngineSpeakerBridge.OnAudioFrameRenderedPostfix`):
    the postfix is called every ~21 ms on the WASAPI callback thread.
    The comment block explaining (a) why `dspTime` is discarded
    (UnixNanosClock is the wall-clock surface that clients can sync to),
    (b) why exceptions are swallowed without logging (BepInExLogSink
    can lock and engine drops if exception escapes), and (c) why
    `buffer.Length` odd-check never fires in practice (PrimaryOutput is
    stereo-fixed) is load-bearing. Stripping these lets a future
    refactor add a `LogDebug` per frame and reintroduce audio glitches.
22. **SpeakerBridge dispose order: singleton clear before inner dispose**
    (`FrooxEngineSpeakerBridge.Dispose`): `_singleton` must be CAS-cleared
    *before* `_inner.Dispose()` so the Postfix (which reads `_singleton`)
    cannot push into a disposed channel. The 2-line comment above
    `Interlocked.CompareExchange(ref _singleton, null, this)` is
    load-bearing — reordering these two operations creates a race where
    a tail WASAPI callback fires `_inner.Push` after the channel writer
    is completed (silent no-op, but the code intent looks wrong on
    review). Keep paired with the SafeShutdown chain comment in
    `ResoniteIOPlugin` that mentions Speaker ordering.
23. **`SafeShutdown` chain documents Speaker placement**
    (`ResoniteIOPlugin.SafeShutdown` ordering block, the bullet
    "SpeakerBridge.Dispose は Harmony unpatch + Channel complete を行い、
    WASAPI audio thread からの push を完全に断つ"): the order
    receiver → camera → display → locomotion → speaker → session → cts →
    sessionHost → resolver is intentional. SpeakerBridge must Dispose
    before SessionHost so pending `SpeakerService.StreamAudio` calls see
    the channel complete and exit cleanly (avoiding RpcException from
    abrupt service teardown). Keep the chain comment intact — it's the
    only place documenting the WASAPI-stop contract.
24. **WAV writer rejects stdlib `wave` module**
    (`python/src/resoio/cli/record.py` `_WavFloat32Writer` docstring):
    the class docstring explicitly states "the stdlib `wave` module
    rejects `WAVE_FORMAT_IEEE_FLOAT` and the project declines
    `soundfile` / `scipy` as runtime deps". This is load-bearing —
    a well-meaning future PR will see ~50 lines of `struct.pack`
    bookkeeping and want to swap in `wave.open` for "simplicity",
    silently regressing float32 support. The seek-and-patch design
    (placeholder size fields at offsets 4 / 40, patched on close) is
    the reason `-o -` for `.wav` is disallowed (stdout is non-seekable).
25. **Fixed mono wire format on Microphone** in
    `python/src/resoio/microphone.py` constants comment: voice
    broadcast on the Resonite side flows through
    `UserAudioStream<MonoSample>`; sending stereo would force a
    down-mix at the bridge for zero gain. The const-block comment
    documents this and pairs with the proto schema's "channel 数=1
    固定" note. Removing the comment invites a "consistency with
    Speaker" PR to widen the wire to stereo, which would either fail
    in the Bridge or silently down-mix without anyone noticing the
    pointless conversion.
26. **`AudioSystem.UnregisterAudioInput` does not exist (decompile
    confirmed)** in `FrooxEngineMicrophoneBridge.Dispose` and the
    class XML `<para>` covering Dispose: only `AudioInputs.Add` exists;
    there is no inverse. The Bridge's best-effort
    `_audioSystem.AudioInputs.Remove(_audioInput)` is the engineered
    workaround, and the private `_audioInputDeviceIDs` HashSet residual
    means a re-load may emit a DeviceID-duplicate warning (functional
    impact: none). Both the class-level comment and the inline comment
    above `Remove(_audioInput)` are load-bearing — stripping them
    invites a future PR to either remove the manual Remove ("looks
    like it should be unnecessary") or fail to add a real Unregister
    when (if) the engine ships one.
27. **`IMicrophoneBridge.NotifyDisconnect` must not throw**
    (interface XML on the method + matching comment in
    `FrooxEngineMicrophoneBridge.NotifyDisconnect`'s try/catch):
    `MicrophoneService` calls `NotifyDisconnect` unguarded in its
    cancel / error paths, so an escaping exception would break
    lifecycle. The "log path も best-effort (ProcessExit 経路では
    log sink が dead の可能性)" comment in the catch block documents
    why even the warning emit is itself wrapped — `BepInExLogSink`
    can lock or throw during shutdown. Removing either lets a future
    refactor either propagate Reset() exceptions to the gRPC layer or
    log per-disconnect on ProcessExit and trigger a self-deadlock.
28. **Microphone Cancelled/Errored → ring buffer clear (RL safety)**
    in `FrooxEngineMicrophoneBridge.NotifyDisconnect`'s switch on
    `MicrophoneDisconnectReason`: client crash must not leave the
    last second of audio playing into the world. The comment "RL/
    ロボティクス safety: client crash 時に古い音が残らない" pairs with
    the proto file's lifecycle paragraph and is the only place in the
    Bridge that documents the policy choice (vs the Speaker side which
    keeps the buffer). A future refactor to a single "always preserve"
    path would silently regress RL safety.
29. **`wave` sampwidth=4 → float32 commitment** in
    `python/src/resoio/cli/mic.py` `_load_wav`: stdlib `wave` only
    reports byte width per sample; it cannot distinguish int32 from
    float32. The CLI commits to float32 because that is what the
    ffmpeg-produced output uses by default and matches the wire
    format. The inline comment is the only place this convention is
    documented (the fixture writer in `tests/e2e/fixtures/generate_sine.py`
    also relies on it). Without the comment a future PR will add an
    int32 branch that silently treats float32 bytes as integers and
    produces inaudible noise.

**Why:** these WHYs explain non-local behaviour: changing one site
(removing the resolver, dropping the collection, swapping the channel
order back, etc.) silently breaks another. The codebase is still young
(Steps 2-3) so the bug stories aren't in git blame depth yet.

**How to apply:** if a future docstring/comment pass touches these
files, preserve these notes — compress wording, never drop the
substance. When Step 4+ adds new bridges, append a new section here
rather than rewriting earlier entries.
