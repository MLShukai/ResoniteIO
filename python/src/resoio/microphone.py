"""Client for the Resonite IO ``Microphone`` gRPC streaming service.

The bridge on the mod side registers a virtual ``AudioInput`` device
with Resonite; samples pushed through :meth:`MicrophoneClient.stream`
are appended to that device's ring buffer and broadcast as the local
user's voice once the user selects the virtual device in
Settings → Audio Input.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Final, Self

import numpy as np
from grpclib.client import Channel
from numpy.typing import NDArray

from resoio._generated.resonite_io.v1 import (
    MicrophoneAudioFrame,
    MicrophoneStreamSummary as _WireSummary,
    MicrophoneStub,
)
from resoio._socket import resolve_socket_path

__all__ = [
    "CHANNELS",
    "DTYPE",
    "SAMPLE_RATE",
    "MicrophoneAudioChunk",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
]

_logger = logging.getLogger("resoio.microphone")

# Fixed wire format: voice broadcast on the Resonite side flows through
# ``UserAudioStream<MonoSample>``; sending stereo would force a down-mix
# at the bridge for zero gain. Stay mono on the wire. proto carries no
# negotiation fields — these constants are the single source of truth.
SAMPLE_RATE: Final[int] = 48000
CHANNELS: Final[int] = 1
DTYPE: Final[np.dtype[np.float32]] = np.dtype(np.float32)


@dataclass(frozen=True, slots=True)
class MicrophoneAudioChunk:
    """One outgoing audio chunk for the microphone stream.

    ``samples`` is a 1-D ``(N,)`` float32 array of mono samples in
    ``[-1.0, 1.0]``. ``frame_id`` flows through verbatim — the client
    never rewrites it. Leave ``unix_nanos`` at ``0`` and
    :meth:`MicrophoneClient.stream` stamps :func:`time.time_ns` at
    wire-encode time; pass a nonzero value to replay pre-recorded
    timestamps unchanged.
    """

    samples: NDArray[np.float32]
    frame_id: int
    unix_nanos: int = 0


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


class MicrophoneClient:
    """Async client for the Resonite IO ``Microphone`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. The wire format is fixed at 48 kHz / Mono /
    float32 LE (:data:`SAMPLE_RATE`, :data:`CHANNELS`, :data:`DTYPE`).
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: MicrophoneStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        _logger.debug("Opening Microphone channel on UDS path: %s", path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = MicrophoneStub(channel)
        self._resolved_path = path
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        channel = self._channel
        self._channel = None
        self._stub = None
        self._resolved_path = None
        if channel is not None:
            channel.close()

    async def stream(
        self, chunks: AsyncIterable[MicrophoneAudioChunk]
    ) -> MicrophoneStreamSummary:
        """Stream microphone chunks to the server and await the summary.

        ``chunks`` is consumed lazily. Callers must hand in 1-D float32
        ``samples`` (no dtype coercion happens here — ``tobytes`` blindly
        serialises whatever buffer it gets). Raises :class:`RuntimeError`
        if called outside ``async with``.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "MicrophoneClient is not connected. "
                "Use `async with MicrophoneClient(): ...`."
            )

        async def _wire() -> AsyncIterator[MicrophoneAudioFrame]:
            async for chunk in chunks:
                samples = chunk.samples
                unix_nanos = (
                    chunk.unix_nanos if chunk.unix_nanos != 0 else time.time_ns()
                )
                yield MicrophoneAudioFrame(
                    frame_id=chunk.frame_id,
                    unix_nanos=unix_nanos,
                    sample_count=int(samples.shape[0]),
                    samples=samples.tobytes(),
                )

        summary: _WireSummary = await stub.stream_audio(_wire())
        return MicrophoneStreamSummary(
            received_frames=summary.received_frames,
            received_samples=summary.received_samples,
            dropped_frames=summary.dropped_frames,
            unix_nanos=summary.unix_nanos,
        )
