"""Client for the Resonite IO ``Microphone`` gRPC streaming service.

The bridge on the mod side registers a virtual ``AudioInput`` device
with Resonite; samples pushed through :meth:`MicrophoneClient.stream`
are appended to that device's ring buffer and broadcast as the local
user's voice once the user selects the virtual device in
Settings → Audio Input.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Final, override

import numpy as np
from grpclib.client import Channel
from numpy.typing import NDArray

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    MicrophoneAudioFrame,
    MicrophoneStreamSummary as _WireSummary,
    MicrophoneStub,
)

__all__ = [
    "CHANNELS",
    "DTYPE",
    "SAMPLE_RATE",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "paced",
]

_logger = logging.getLogger(__name__)

# Fixed wire format: voice broadcast on the Resonite side flows through
# ``UserAudioStream<MonoSample>``; sending stereo would force a down-mix
# at the bridge for zero gain. Stay mono on the wire. proto carries no
# negotiation fields — these constants are the single source of truth.
SAMPLE_RATE: Final[int] = 48000
CHANNELS: Final[int] = 1
DTYPE: Final[np.dtype[np.float32]] = np.dtype(np.float32)


@dataclass(frozen=True, slots=True)
class MicrophoneStreamSummary:
    """Server-side summary returned when a ``StreamAudio`` stream ends.

    ``dropped_frames`` counts frames the bridge discarded on ring buffer
    overflow (client outpacing engine consumption); a healthy run is 0.
    """

    received_frames: int
    received_samples: int
    dropped_frames: int
    unix_nanos: int


class MicrophoneClient(_BaseClient[MicrophoneStub]):
    """Async client for the Resonite IO ``Microphone`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. The wire format is fixed at 48 kHz / Mono /
    float32 LE (:data:`SAMPLE_RATE`, :data:`CHANNELS`, :data:`DTYPE`).
    """

    _logger = _logger
    _log_label = "Microphone"

    @override
    def _make_stub(self, channel: Channel) -> MicrophoneStub:
        return MicrophoneStub(channel)

    async def stream(
        self, chunks: AsyncIterable[NDArray[np.float32]]
    ) -> MicrophoneStreamSummary:
        """Stream microphone chunks to the server and await the summary.

        ``chunks`` is consumed lazily. Callers hand in plain 1-D float32
        ``samples`` arrays (no dtype coercion happens here — ``tobytes``
        blindly serialises whatever buffer it gets). The client owns
        ``frame_id`` (auto-incremented from 0) and stamps
        :func:`time.time_ns` on every chunk. Raises :class:`RuntimeError`
        if called outside ``async with``.
        """
        stub = self._require_stub()

        async def _wire() -> AsyncIterator[MicrophoneAudioFrame]:
            frame_id = 0
            async for samples in chunks:
                yield MicrophoneAudioFrame(
                    frame_id=frame_id,
                    unix_nanos=time.time_ns(),
                    sample_count=int(samples.shape[0]),
                    samples=samples.tobytes(),
                )
                frame_id += 1

        summary: _WireSummary = await stub.stream_audio(_wire())
        return MicrophoneStreamSummary(
            received_frames=summary.received_frames,
            received_samples=summary.received_samples,
            dropped_frames=summary.dropped_frames,
            unix_nanos=summary.unix_nanos,
        )


async def paced(
    chunks: AsyncIterable[NDArray[np.float32]],
    sample_rate: int = SAMPLE_RATE,
) -> AsyncIterator[NDArray[np.float32]]:
    """Yield chunks at wall-clock pace for replaying a pre-loaded buffer.

    Opt-in helper for sources that hand over their whole payload at once
    (e.g. a WAV file): yields each ndarray, then sleeps for its natural
    duration before pulling the next one, so the downstream Bridge ring
    buffer never overflows on long inputs.

    Do **not** wrap real-time producers (live mic, TTS streams) — they
    pace themselves; the extra sleep would compound into latency.
    """
    async for samples in chunks:
        yield samples
        n_samples = int(samples.shape[0])
        if n_samples > 0:
            await asyncio.sleep(n_samples / sample_rate)
