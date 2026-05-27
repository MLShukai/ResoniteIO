"""E2E: stream the canonical sine fixture into Resonite via Microphone.

Pushes the 440 Hz mono float32 fixture (length defined by
``fixtures/generate_sine.py``) into the engine's virtual
``AudioInput`` and asserts the server-returned summary matches the
wire path. Audible verification (does another user actually hear
the voice?) requires a second human in-world; that residual manual
step lives in ``mod/tests/manual/microphone-verification.md``.

Uses :class:`MicrophoneClient` directly so the chunking assertion
stays anchored to the wire protocol, not CLI argument plumbing.
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

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sine_440hz_5s_mono_48k.wav"

# Duplicated from ``resoio.cli.mic`` so the assertion math is anchored
# to the wire chunk size rather than a CLI implementation detail.
_CHUNK_SAMPLES = 1024

# Generous retry budget absorbs the Resonite cold-boot window
# (FAILED_PRECONDITION fires until LocalUser / AudioSystem are wired up).
_BRIDGE_READY_TIMEOUT_S = 120.0
_BRIDGE_READY_RETRY_INTERVAL_S = 2.0


def _load_fixture_samples() -> np.ndarray:
    """Load the fixture WAV into a mono float32 numpy array.

    The fixture is written with ``wFormatTag = 1`` so stdlib :mod:`wave`
    accepts it; the 4-byte samples are reinterpreted as float32 LE per
    ``generate_sine.py``'s serialisation contract.
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

    Treats ``FAILED_PRECONDITION`` as a retry signal; any other status
    surfaces immediately.
    """
    deadline = time.monotonic() + _BRIDGE_READY_TIMEOUT_S
    while True:
        try:
            async with MicrophoneClient() as client:

                async def _empty() -> AsyncIterator[MicrophoneAudioChunk]:
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
    """Slice ``samples`` into 1024-sample frames; trailing remainder is
    dropped."""
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
        del resonite_session  # only the fixture's lifecycle side-effect matters here

        samples = _load_fixture_samples()
        # Derive expected counts from the loaded fixture so duration
        # changes in ``generate_sine.py`` do not require updating asserts.
        expected_chunks = samples.shape[0] // _CHUNK_SAMPLES
        expected_samples = expected_chunks * _CHUNK_SAMPLES

        async def run() -> MicrophoneStreamSummary:
            await _wait_for_microphone_ready()
            async with MicrophoneClient() as client:
                return await client.stream(_iter_chunks(samples))

        summary = asyncio.run(run())

        # Print the wire-observable numbers on green runs too — useful
        # when cross-checking against the manual audibility checklist.
        print(f"E2E microphone summary: {summary}")
        print(
            f"sent_chunks={expected_chunks}, sent_samples={expected_samples}, "
            f"dropped_remainder_samples={samples.shape[0] - expected_samples}"
        )

        assert summary.received_frames == expected_chunks, (
            f"server received {summary.received_frames} frames, "
            f"expected {expected_chunks} (one per 1024-sample chunk)"
        )
        assert summary.received_samples == expected_samples, (
            f"server received {summary.received_samples} samples, "
            f"expected {expected_samples} "
            f"(= {expected_chunks} chunks × {_CHUNK_SAMPLES} samples)"
        )
        # Non-zero here means a bridge ring buffer overflow regression.
        assert summary.dropped_frames == 0, (
            f"server reported dropped_frames={summary.dropped_frames}; "
            "expected 0 — bridge ring buffer overflow?"
        )
        assert summary.unix_nanos > 0, (
            f"summary.unix_nanos must be a positive epoch stamp, "
            f"got {summary.unix_nanos}"
        )
