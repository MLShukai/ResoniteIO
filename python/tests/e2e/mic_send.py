"""E2E: stream the canonical sine fixture into Resonite via Microphone.

Symmetric counterpart of :mod:`tests.e2e.speaker_record`. Where
``speaker_record`` records the Resonite speaker output to WAV, this
test pushes a pre-recorded 1-second 440 Hz mono float32 fixture
(``fixtures/sine_440hz_1s_mono_48k.wav``) into the engine's virtual
``AudioInput`` device via :class:`resoio.microphone.MicrophoneClient`
and asserts the server-returned summary matches what the wire path
produced.

Scope is deliberately a sanity check: there is no Resonite-side
measurement path that lets us verify whether a remote listener
actually heard the sine, so the assertion budget is limited to
"stream completes without exception" + "summary frame / sample
counts agree with what the client sent". Audible verification is
manual (see ``mod/tests/manual/microphone-verification.md`` once it
lands).

Chunking math: the CLI uses ``_CHUNK_SAMPLES = 1024`` (~21.3 ms at
48 kHz). 48000 samples / 1024 = 46 full chunks; the trailing 896
samples are dropped (CLI ``_iter_wav_chunks`` does not zero-pad EOF
remainders, intentional to keep "what the caller asked for" on the
wire). This file re-uses the public :class:`MicrophoneClient` rather
than the CLI subprocess because the direct path keeps the
assertion (chunk count) anchored to the wire protocol rather than
to CLI argument plumbing.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import grpclib.exceptions
import numpy as np
from grpclib.const import Status

from resoio.microphone import (
    DTYPE,
    SAMPLE_RATE,
    MicrophoneAudioChunk,
    MicrophoneClient,
    MicrophoneStreamSummary,
)
from tests.helpers import mark_e2e

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sine_440hz_1s_mono_48k.wav"

# Mirror :data:`resoio.cli.mic._CHUNK_SAMPLES`. Duplicated rather than
# imported from a private name so the assertion math here is decoupled
# from CLI internals — the wire chunk size is the part under test, not
# the CLI's implementation detail.
_CHUNK_SAMPLES = 1024

# 48000 samples / 1024 = 46 full chunks (trailing 896 samples dropped
# by the chunker; see module docstring). Both numbers are derived
# rather than hard-coded so a future fixture length change surfaces in
# one place.
_EXPECTED_CHUNKS = int(SAMPLE_RATE) // _CHUNK_SAMPLES  # 46
_EXPECTED_SAMPLES = _EXPECTED_CHUNKS * _CHUNK_SAMPLES  # 47104

# Microphone bridge returns FAILED_PRECONDITION until LocalUser /
# AudioSystem are wired up (same shape as Speaker / Locomotion). Retry
# budget is generous to absorb the Resonite cold-boot window.
_BRIDGE_READY_TIMEOUT_S = 120.0
_BRIDGE_READY_RETRY_INTERVAL_S = 2.0


def _load_fixture_samples() -> np.ndarray:
    """Load the fixture WAV into a mono float32 numpy array.

    Uses stdlib :mod:`wave` to parse the header (the fixture is written
    with ``wFormatTag = 1`` so stdlib accepts it) and reinterprets the
    4-byte samples as float32 LE (matching how the fixture was
    serialised in ``generate_sine.py``).
    """
    with wave.open(str(FIXTURE_PATH), "rb") as wav:
        assert wav.getframerate() == SAMPLE_RATE, (
            f"fixture sample rate {wav.getframerate()} != {SAMPLE_RATE}"
        )
        assert wav.getnchannels() == 1, (
            f"fixture must be mono, got {wav.getnchannels()} channels"
        )
        assert wav.getsampwidth() == 4, (
            f"fixture must be 4-byte samples, got sampwidth={wav.getsampwidth()}"
        )
        raw = wav.readframes(wav.getnframes())
    return np.frombuffer(raw, dtype=DTYPE).copy()


async def _wait_for_microphone_ready() -> None:
    """Block until ``Microphone.StreamAudio`` accepts an empty stream.

    Mirrors the pattern in :func:`resoio.cli.mic._wait_for_bridge_ready`
    (and the speaker / locomotion equivalents): open a fresh client,
    send no frames, and accept a clean summary or ``FAILED_PRECONDITION``
    as a retry signal. Anything else surfaces immediately.
    """
    deadline = time.monotonic() + _BRIDGE_READY_TIMEOUT_S
    while True:
        try:
            async with MicrophoneClient() as client:

                async def _empty() -> AsyncIterator[MicrophoneAudioChunk]:
                    # Yield nothing — the empty stream is enough to
                    # provoke the bridge's not-ready precondition.
                    return
                    yield  # pragma: no cover — marks this a generator

                await client.stream(_empty())
            return
        except grpclib.exceptions.GRPCError as exc:
            if exc.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Microphone bridge did not become ready in "
                    f"{_BRIDGE_READY_TIMEOUT_S:.0f}s "
                    f"(last reason: {exc.message})"
                ) from exc
            await asyncio.sleep(_BRIDGE_READY_RETRY_INTERVAL_S)


def _iter_chunks(samples: np.ndarray) -> AsyncIterator[MicrophoneAudioChunk]:
    """Slice ``samples`` into 1024-sample :class:`MicrophoneAudioChunk` frames.

    Behaviour is identical to :func:`resoio.cli.mic._iter_wav_chunks`
    (trailing < 1024-sample remainder dropped, no zero-padding) so the
    expected chunk / sample counts above stay in lock-step with the CLI.
    """
    full_chunks = samples.shape[0] // _CHUNK_SAMPLES

    async def _gen() -> AsyncIterator[MicrophoneAudioChunk]:
        for i in range(full_chunks):
            start = i * _CHUNK_SAMPLES
            end = start + _CHUNK_SAMPLES
            yield MicrophoneAudioChunk(
                samples=samples[start:end].astype(DTYPE, copy=False),
                frame_id=i,
            )

    return _gen()


class TestMicrophoneSend:
    @mark_e2e
    def test_send_sine_fixture(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        samples = _load_fixture_samples()
        assert samples.shape == (int(SAMPLE_RATE),), (
            f"unexpected fixture length: {samples.shape}"
        )

        async def run() -> MicrophoneStreamSummary:
            await _wait_for_microphone_ready()
            async with MicrophoneClient() as client:
                return await client.stream(_iter_chunks(samples))

        summary = asyncio.run(run())

        # Surface the wire-observable numbers on green runs too — useful
        # signal when comparing the manual audibility checklist against
        # what actually crossed the bridge.
        print(f"E2E microphone summary: {summary}")
        print(
            f"sent_chunks={_EXPECTED_CHUNKS}, sent_samples={_EXPECTED_SAMPLES}, "
            f"dropped_remainder_samples={samples.shape[0] - _EXPECTED_SAMPLES}"
        )

        assert summary.received_frames == _EXPECTED_CHUNKS, (
            f"server received {summary.received_frames} frames, "
            f"expected {_EXPECTED_CHUNKS} (one per 1024-sample chunk)"
        )
        assert summary.received_samples == _EXPECTED_SAMPLES, (
            f"server received {summary.received_samples} samples, "
            f"expected {_EXPECTED_SAMPLES} "
            f"(= {_EXPECTED_CHUNKS} chunks × {_CHUNK_SAMPLES} samples)"
        )
        # Bridge currently has no overflow path that increments
        # dropped_frames (the ring buffer absorbs a full second of
        # samples comfortably); assert 0 so a future regression that
        # silently drops mid-stream is caught here.
        assert summary.dropped_frames == 0, (
            f"server reported dropped_frames={summary.dropped_frames}; "
            "expected 0 — bridge ring buffer overflow?"
        )
        assert summary.unix_nanos > 0, (
            f"summary.unix_nanos must be a positive epoch stamp, "
            f"got {summary.unix_nanos}"
        )
