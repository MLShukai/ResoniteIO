---
name: microphone-cleanup-2026-05-20
description: Step 7 (Microphone, Python→Resonite) docstring + comment trim pass on 2026-05-20 — what landed, what was kept load-bearing
metadata:
  type: project
---

Step 7 (Microphone) docstring/comment trim pass on branch
`feature/20260520/microphone-module` after the implementer landed
6 commits. Same pattern as \[\[speaker-doc-landed\]\] — the implementer
wrote substantial docstrings during implementation, so this was a
trim pass, not an authoring pass.

**Files touched (all under Step 7 scope):**

- `python/src/resoio/microphone.py` — module docstring shortened
  (removed "Mirror of speaker" cross-reference), `MicrophoneAudioChunk` /
  `MicrophoneStreamSummary` / `MicrophoneClient` / `stream()` docstrings
  trimmed of paraphrase-of-signature text.
- `python/src/resoio/cli/mic.py` — module docstring lost the bullet
  list of input modes (the `--help` text covers it). `_load_wav` /
  `_wait_for_bridge_ready` / `_iter_wav_chunks` / `_iter_stdin_chunks` /
  `_run` docstrings tightened. `_InputFormatError` one-liner.
- `python/tests/resoio/test_microphone.py` /
  `python/tests/resoio/cli/test_mic.py` — most per-test docstrings
  removed (test names suffice). Inline comments paraphrasing what
  the next line does removed; kept comments about anchor-value
  rationale (e.g. `16384 / 32768 = 0.5`) and stdin shim purpose.
- `python/tests/e2e/mic_send.py` — long module docstring compressed.
  `_load_fixture_samples` / `_wait_for_microphone_ready` / `_iter_chunks`
  docstrings tightened.
- `python/tests/e2e/fixtures/generate_sine.py` — module docstring
  - `_sine_samples` / `_build_header` / `write_fixture` docstrings
    trimmed. Constants kept their grouping comments but lost the
    re-explanation prose.
- `mod/src/ResoniteIO.Core/Microphone/IMicrophoneBridge.cs` — interface
  XML trimmed (3 paragraphs → 2). `MicrophoneFrame` / `MicrophoneDisconnectReason`
  XML doc tightened. Per-method XML stayed close to the original wording.
- `mod/src/ResoniteIO.Core/Microphone/MicrophoneService.cs` — class
  XML remarks compressed; redundant `MapFromProto` inline comment
  dropped (the class XML already documents the defensive-copy +
  bytes-length-trust contract).
- `mod/src/ResoniteIO.Core/Microphone/MicrophoneNotReadyException.cs` —
  tightened one-paragraph XML doc.
- `mod/src/ResoniteIO/Bridge/FrooxEngineMicrophoneBridge.cs` — class
  XML remarks compressed; redundant inline comments paraphrasing
  the next line removed; tickstep/throughput comment moved into
  `DrainAndWrite` summary so the call site stays clean.
- `mod/tests/ResoniteIO.Core.Tests/Helpers/FakeMicrophoneBridge.cs` —
  bullet-list `<remarks>` collapsed into the `<summary>`; redundant
  per-property `<summary>` removed (property names are self-documenting).
- `mod/tests/ResoniteIO.Core.Tests/Microphone/MicrophoneRoundTripTests.cs` —
  class `<summary>` split into summary + remarks; "server-side
  completion は非同期" duplicated comments rephrased per call site.
- `proto/resonite_io/v1/microphone.proto` — not modified (user said
  "確認のみ"; comments are already on the dense-WHY side appropriate
  for a single-source-of-truth schema file).

**What was NOT trimmed (load-bearing — preserved verbatim or only
re-worded for tightness):**

- `microphone.py` `SAMPLE_RATE / CHANNELS / DTYPE` const block
  comment ("voice broadcast flows through `UserAudioStream<MonoSample>`,
  stereo forces a down-mix for zero gain") — explains the fixed-wire
  decision per \[\[load-bearing-whys\]\] §22-equivalent.
- `cli/mic.py` `_CHUNK_SAMPLES = 1024` rationale ("close to 20 ms Opus
  encoder default; engine re-frames anyway") — non-obvious chunk-size choice.
- `cli/mic.py` `sampwidth == 4` → float32 commit comment — stdlib `wave`
  cannot distinguish int32 from float32, so the convention is intentional.
- `FrooxEngineMicrophoneBridge` class XML `<para>` about
  **Dispose: `UnregisterAudioInput` API は存在しない (decompile 確認済み)** —
  the decompile finding shapes the entire Dispose strategy.
- `FrooxEngineMicrophoneBridge` `AudioSystem == null` defensive degrade
  comment — same pattern as Speaker; future readers will want this WHY.
- `FrooxEngineMicrophoneBridge.NotifyDisconnect` "契約上 must not throw"
  - "log path も best-effort (ProcessExit 経路では log sink が dead の
    可能性)" — contract-shape comment for the IF, and the silent
    give-up reasoning is non-obvious.
- `FrooxEngineMicrophoneBridge.NotifyDisconnect` Cancelled/Errored →
  "RL/ロボティクス safety: client crash 時に古い音が残らない" —
  product-level WHY for the buffer-clear policy.
- `ResoniteIOAudioInput` interpolation-state engine-thread-only
  comment + `MonoSample` memory layout reinterpret comment
  (decompile reference to `CSCoreAudioInputDriver.AsAudioBuffer<MonoSample>`).
- `ResoniteIOAudioInput.ResoniteIOAudioInput` ctor `isDefault: false`
  rationale — future readers will be tempted to flip this to true.
- `MicrophoneService.cs` "gRPC 慣習として Unavailable を使う" comment.
- `MicrophoneService.cs` cancel-exception-bucket `catch when` block
  comment referencing
  \[\[feedback-grpc-client-cancel-exception-surface\]\]
  — exception-surface inconsistency is platform-implementation-detail
  and only documented in that feedback memory.
- `MicrophoneService.cs` "`MoveNext` returned false = client が
  CompleteAsync で graceful close" — disconnect-reason switch is
  non-obvious without it.
- `MicrophoneService.cs` `DroppedFrames = 0L` comment ("本層では drop
  は発生しない (Bridge 側 ring buffer overflow が drop の発生源)") —
  documents an invariant for a wire field that proto comment alone
  cannot fully cover (it explains layer responsibility).

**Why:** Step 7 docstrings were dense enough that the user noticed
the redundancy at IDE-read time. The Speaker pattern of "implementer
already wrote substantial XML / docstrings, trim pass exists" applies.

**How to apply:** when modifying Step 7 files in the future, do not
re-author from scratch — re-read first. Append new load-bearing
items to \[\[load-bearing-whys\]\] rather than re-introducing inline
explanations the trim pass deemed redundant.

**Polish wave 2 (2026-05-20, post-landing — paced helper + CLI WAV
pacing + 5 s fixture):**

- `microphone.py` — added `paced()` async helper (exported via
  `__all__`). Docstring carries three load-bearing WHYs that must
  survive future trims:
  1. opt-in helper for pre-loaded buffers — the default path is
     producer-driven pacing on `MicrophoneClient.stream`,
  2. must not be wrapped over real-time producers (live mic, TTS) —
     extra sleep compounds into latency,
  3. sleep-after-yield means `MicrophoneClient.stream` auto-stamp
     reflects emit time, not capture time — set `unix_nanos`
     explicitly to preserve original timestamps.
- `cli/mic.py` — `_WARMUP_CHUNKS = 5` (~107 ms) absorbs engine tick
  drain ramp-up; module docstring + constant comment carry the WHY.
  `_iter_wav_chunks` delegates pacing to `paced()` so the CLI does not
  duplicate the pacing logic (intentional single-source-of-truth).
- `tests/e2e/fixtures/generate_sine.py` — `_DURATION_S = 5.0`; the
  comment explicitly states the 5 s payload deliberately exceeds the
  bridge's 2 s ring buffer so WAV-mode pacing regressions surface as
  `dropped_frames`. The filename keeps the historic "1s" suffix to
  avoid git-history churn — that pair of WHYs is load-bearing.
- `tests/e2e/mic_send.py` — replaced module-level `_EXPECTED_*`
  constants with in-test derive from loaded fixture length, so future
  duration changes don't drift the asserts.
- `tests/resoio/test_microphone.py` — added `TestPaced` (real-time,
  payload pass-through, empty iter). Test docstrings deliberately
  omitted; tolerance comments (5 ms / 250 ms / huge sample_rate)
  retained because they encode the CI-jitter rationale.
- `tests/resoio/cli/test_mic.py` — added
  `test_wav_input_paces_after_warmup`; 70 % lower-bound tolerance
  retained as a CI-jitter shield while still catching a no-pacing
  regression (would land at "a few ms").

The reviewer-suggested "stamps reflect emit time" addition went into
`paced()`'s docstring as a single paragraph — declined the temptation
to expand it into an Args/Returns block.
