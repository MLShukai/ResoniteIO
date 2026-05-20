"""Client for the Resonite IO ``Microphone`` gRPC streaming service.

Mirror of :mod:`resoio.speaker` for the opposite direction. The bridge
on the mod side registers a virtual ``AudioInput`` device with Resonite;
samples pushed through :meth:`MicrophoneClient.stream` are appended to
that device's ring buffer and broadcast as the local user's voice once
the user picks the virtual device in Settings → Audio Input.

Wire format is fixed at 48 kHz / Mono / float32 LE (no interleave); the
proto carries no negotiation fields and the constants below are the
single source of truth.
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
# ``UserAudioStream<MonoSample>``; sending stereo would require an extra
# down-mix at the bridge for zero gain. Stay mono on the wire.
SAMPLE_RATE: Final[int] = 48000
CHANNELS: Final[int] = 1
DTYPE: Final[np.dtype[np.float32]] = np.dtype(np.float32)


@dataclass(frozen=True, slots=True)
class MicrophoneAudioChunk:
    """One outgoing audio chunk for the microphone stream.

    ``samples`` is a 1-D ``(N,)`` float32 array of mono samples in
    ``[-1.0, 1.0]``. ``frame_id`` is supplied by the caller (typically
    monotonically increasing from ``0``) so the server can detect gaps
    or reordering; the client does not re-number it. ``unix_nanos`` is
    the client-side send timestamp; leave it at the default ``0`` and
    :meth:`MicrophoneClient.stream` will stamp it with
    :func:`time.time_ns` at wire-encode time. A nonzero value is passed
    through verbatim, which is useful when replaying a pre-recorded
    sequence with original timestamps.
    """

    samples: NDArray[np.float32]
    frame_id: int
    unix_nanos: int = 0


@dataclass(frozen=True, slots=True)
class MicrophoneStreamSummary:
    """Server-side summary returned when a ``StreamAudio`` stream ends.

    Mirrors the proto ``MicrophoneStreamSummary`` 1:1. ``dropped_frames``
    counts frames the bridge had to discard (e.g. ring buffer overflow
    when the client outpaces engine consumption); a current bridge
    typically reports ``0``.
    """

    received_frames: int
    received_samples: int
    dropped_frames: int
    unix_nanos: int


class MicrophoneClient:
    """Async client for the Resonite IO ``Microphone`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.SessionClient`. The wire format is fixed at
    48 kHz / Mono / float32 LE; constants are exposed at module level
    (:data:`SAMPLE_RATE`, :data:`CHANNELS`, :data:`DTYPE`).
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

        ``chunks`` is consumed lazily; each :class:`MicrophoneAudioChunk`
        is converted to a wire :class:`MicrophoneAudioFrame` on the fly.
        ``samples`` must be a 1-D float32 array (``dtype`` is enforced
        by ``ndarray.tobytes`` plus ``sample_count = samples.shape[0]``;
        callers are expected to coerce via :data:`DTYPE` upstream).
        ``frame_id`` flows through verbatim. ``unix_nanos`` is stamped
        here when the caller leaves it at ``0``, otherwise passed
        through unchanged. gRPC failures surface as
        :class:`grpclib.exceptions.GRPCError`. Raises
        :class:`RuntimeError` if called outside ``async with``.
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
