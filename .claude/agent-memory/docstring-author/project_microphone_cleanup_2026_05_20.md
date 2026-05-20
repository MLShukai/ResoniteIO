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
