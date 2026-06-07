"""Client for the Resonite IO ``Speaker`` gRPC streaming service."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final, override

import numpy as np
from grpclib.client import Channel
from numpy.typing import NDArray

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import SpeakerStreamRequest, SpeakerStub

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


class SpeakerClient(_BaseClient[SpeakerStub]):
    """Async client for the Resonite IO ``Speaker`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.ConnectionClient`. The wire format is fixed at
    48 kHz / Stereo / float32 LE; constants are exposed at module level
    (:data:`SAMPLE_RATE`, :data:`CHANNELS`, :data:`DTYPE`).
    """

    _logger = _logger
    _log_label = "Speaker"

    @override
    def _make_stub(self, channel: Channel) -> SpeakerStub:
        return SpeakerStub(channel)

    async def stream(self) -> AsyncIterator[AudioChunk]:
        """Stream the Resonite final audio mix from the server.

        Yields one :class:`AudioChunk` per server-emitted ``AudioFrame``.
        Raises :class:`RuntimeError` if called outside ``async with``.
        """
        stub = self._require_stub()
        request = SpeakerStreamRequest()
        async for raw in stub.stream_audio(request):
            samples = np.frombuffer(raw.samples, dtype=np.float32).reshape(-1, CHANNELS)
            yield AudioChunk(
                samples=samples,
                unix_nanos=raw.unix_nanos,
                frame_id=raw.frame_id,
            )
