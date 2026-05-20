---
name: speaker-doc-landed
description: Step 5 (Speaker modality) docstring + comment trim pass on 2026-05-20 — what landed, what was already substantial from the implementer, and where the trim opportunities were
metadata:
  type: project
---

Step 5 (Speaker) docstring pass on branch `feature/20260520/speaker-module`
landed on top of HEAD `475cc57`. The implementer wrote substantial XML
doc comments during the implementation phase, so this docstring pass
was largely a verification + small trim exercise rather than a heavy
authoring pass. Treat this memory as a "current state snapshot" of the
Speaker public surface — most files need no further docstring work
unless a behaviour change introduces a new WHY.

**Why:** the Speaker implementer landed Wave-1 / Wave-2 code with
docstrings already attached (see plan §2-5 in
`/home/dev/.claude/plans/claude-manipulation-audio-plan-resonite-vectorized-hinton.md`
which calls out exactly what each file should document). A future
docstring pass should not "add docstrings" to Speaker files — they're
there. The remaining work was tightening / removing duplicates.

**How to apply:** when a future PR touches Speaker files, do not assume
the docstrings are sparse and reach for new authoring. Re-read first.
Specifically:

- `mod/src/ResoniteIO.Core/Speaker/ISpeakerBridge.cs` — XML doc covers
  push semantics, FrameId numbering, exception contract.
  `AudioFrame` constants `ChannelCount` / `SampleRate` are documented.
- `mod/src/ResoniteIO.Core/Speaker/PushedAudioFrameSpeakerBridge.cs` —
  class XML remarks document cap=32 + DropWrite policy; inline
  comments document Defensive copy + DropWrite-vs-Complete TryWrite
  semantics + ReadAllAsync exit behaviour. (See load-bearing item 19.)
- `mod/src/ResoniteIO.Core/Speaker/SpeakerService.cs` — XML doc covers
  Unavailable / FailedPrecondition / Internal translation policy and
  no-renumber contract for FrameId.
- `mod/src/ResoniteIO.Core/Speaker/SpeakerNotReadyException.cs` —
  XML doc explains FailedPrecondition translation rationale.
- `mod/src/ResoniteIO/Bridge/FrooxEngineSpeakerBridge.cs` — class XML
  remarks `<list>` covers the four design judgements (RenderAudio
  direct-assign hazard / PrimaryOutput target / base-class patch /
  static singleton constraint / DefaultAudioOutputChanged re-attach).
  Postfix method has its own XML doc + inline comments for the WASAPI
  hot path constraints. Dispose has the load-bearing
  "singleton clear → inner dispose" ordering comment. (See
  load-bearing items 20–22.)
- `mod/src/ResoniteIO/ResoniteIOPlugin.cs` — SafeShutdown chain comment
  already lists Speaker placement (receiver → camera → display →
  locomotion → speaker → session). No additional comment needed at
  the speaker instantiation line — it matches other modalities'
  style (single line, no comment). (See load-bearing item 23.)
- `python/src/resoio/speaker.py` — `AudioChunk` / `SpeakerClient` /
  module-level constants all have docstrings matching the
  `camera.py` style. The `Fixed wire format` module comment block at
  lines 28-30 documents why proto carries no negotiation.
- `python/src/resoio/cli/record.py` — `_WavFloat32Writer` docstring
  carries the "stdlib `wave` rejects float32" rationale. Header
  layout constants are documented inline. `_record_to_stdout`
  documents why no WAV header (non-seekable stdout). `_run`
  documents why extension validation returns rc=2 rather than
  `parser.error`. (See load-bearing item 24.)

**Trim pass actually made (2026-05-20):**

1. Dropped arithmetic-restating comment
   "`sample_count * 2 (ch) * 4 (bytes) = byteSpan.Length`" in
   `PushedAudioFrameSpeakerBridge.Push` — was redundant with the
   Defensive copy WHY directly above.
2. Tightened the `ChannelClosedException` comment in
   `PushedAudioFrameSpeakerBridge.StreamFramesAsync` to reflect that
   `ReadAllAsync` exits silently on Writer.Complete (the original
   comment implied an exception path that does not exist).
3. Dropped duplicate
   "1 mod 全体で 1 instance が前提" comment at the
   `Interlocked.CompareExchange(ref _singleton, ...)` site in
   `FrooxEngineSpeakerBridge` ctor — duplicated the class XML
   `<remarks>` `<item>` paragraph just above.
4. Rephrased the `_targetDriver` field comment to be technically
   accurate (was "対象 driver 参照を static field 経由でアクセスする"
   which read as if `_targetDriver` itself were static; it's an
   instance field accessed via the static `_singleton`).
5. No Python-side trims — the implementer's docstrings were already
   tight (no `Args:` / `Returns:` blocks paraphrasing signatures).

**What was NOT trimmed (intentionally — these are load-bearing):**

- The 4-bullet `<list type="bullet">` in
  `FrooxEngineSpeakerBridge` class XML — each bullet is one of the
  design judgements summarised in load-bearing items 20-22.
- The WASAPI hot path exception-swallow comment in
  `OnAudioFrameRenderedPostfix` (item 21).
- The Dispose order comment "singleton clear → inner dispose" (item 22).
- The `// Client が disconnect すると WriteAsync が ... (Camera と同様)`
  comment in `SpeakerService.cs` — even though it cross-references
  Camera, it's needed for someone reading SpeakerService alone.
- The SafeShutdown chain comment in `ResoniteIOPlugin.cs` (item 23).
