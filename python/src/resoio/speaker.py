"""Client for the Resonite IO ``Speaker`` gRPC streaming service."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Final, Self

import numpy as np
from grpclib.client import Channel
from numpy.typing import NDArray

from resoio._generated.resonite_io.v1 import SpeakerStreamRequest, SpeakerStub
from resoio._socket import resolve_socket_path

__all__ = [
    "CHANNELS",
    "DTYPE",
    "SAMPLE_RATE",
    "AudioChunk",
    "SpeakerClient",
]

_logger = logging.getLogger("resoio.speaker")

# Fixed wire format: the Resonite final audio mix is always emitted as
# 48 kHz / stereo (L,R interleaved) / float32 little-endian. proto does not
# carry negotiation fields; the constants below are the single source of truth.
SAMPLE_RATE: Final[int] = 48000
CHANNELS: Final[int] = 2
DTYPE: Final[np.dtype[np.float32]] = np.dtype(np.float32)


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """One decoded audio chunk from the speaker stream.

    ``samples`` is an ``(N, 2)`` float32 view over the protobuf payload
    bytes (read-only; call ``.copy()`` for a writable array). Channels
    are interleaved L,R in the wire bytes and reshaped to columns
    ``[L, R]``. ``unix_nanos`` is the bridge tap timestamp in UTC nanos
    since the Unix epoch. ``frame_id`` is a server-side monotonic
    counter that restarts at 0 per ``stream()`` call.
    """

    samples: NDArray[np.float32]
    unix_nanos: int
    frame_id: int


class SpeakerClient:
    """Async client for the Resonite IO ``Speaker`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.SessionClient`. The wire format is fixed at
    48 kHz / Stereo / float32 LE; constants are exposed at module level
    (:data:`SAMPLE_RATE`, :data:`CHANNELS`, :data:`DTYPE`).
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: SpeakerStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        _logger.debug("Opening Speaker channel on UDS path: %s", path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = SpeakerStub(channel)
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

    async def stream(self) -> AsyncIterator[AudioChunk]:
        """Stream the Resonite final audio mix from the server.

        Yields one :class:`AudioChunk` per server-emitted ``AudioFrame``.
        Raises :class:`RuntimeError` if called outside ``async with``.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "SpeakerClient is not connected. Use `async with SpeakerClient(): ...`."
            )
        request = SpeakerStreamRequest()
        async for raw in stub.stream_audio(request):
            samples = np.frombuffer(raw.samples, dtype=np.float32).reshape(-1, CHANNELS)
            yield AudioChunk(
                samples=samples,
                unix_nanos=raw.unix_nanos,
                frame_id=raw.frame_id,
            )
