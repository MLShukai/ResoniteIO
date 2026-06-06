import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

import numpy as np
import pytest

from resoio._generated.resonite_io.v1 import (
    AudioFrame,
    SpeakerBase,
    SpeakerStreamRequest,
)
from resoio.speaker import (
    CHANNELS,
    AudioChunk,
    SpeakerClient,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

_FRAME_COUNT = 3
_SAMPLES_PER_FRAME = 256  # samples per channel per frame


def _make_frame_samples(frame_index: int) -> np.ndarray:
    """Deterministic stereo payload for frame ``frame_index``.

    L channel = frame_index, R channel = -frame_index (constant across
    the 256 samples). Proves both interleave order and per-channel
    values flow through unchanged.
    """
    left = np.full(_SAMPLES_PER_FRAME, float(frame_index), dtype=np.float32)
    right = np.full(_SAMPLES_PER_FRAME, -float(frame_index), dtype=np.float32)
    return np.stack([left, right], axis=1)  # shape (N, 2)


class _ConstantSpeaker(SpeakerBase):
    """In-process fake yielding ``_FRAME_COUNT`` deterministic audio frames."""

    async def stream_audio(
        self, message: SpeakerStreamRequest
    ) -> AsyncIterator[AudioFrame]:
        for i in range(_FRAME_COUNT):
            samples = _make_frame_samples(i)
            yield AudioFrame(
                frame_id=i,
                unix_nanos=time.time_ns(),
                sample_count=_SAMPLES_PER_FRAME,
                samples=samples.tobytes(),
            )


class TestSpeakerClient:
    async def test_round_trip_over_uds(self, uds_server: UdsServer):
        socket_path = await uds_server(_ConstantSpeaker())
        chunks: list[AudioChunk] = []
        async with SpeakerClient() as client:
            assert client.socket_path == socket_path
            async for chunk in client.stream():
                chunks.append(chunk)
        assert len(chunks) == _FRAME_COUNT
        for i, chunk in enumerate(chunks):
            assert chunk.frame_id == i
            assert chunk.unix_nanos > 0
            assert isinstance(chunk.samples, np.ndarray)
            assert chunk.samples.dtype == np.float32
            assert chunk.samples.shape == (_SAMPLES_PER_FRAME, CHANNELS)
            # L = i, R = -i throughout the chunk (proves
            # interleave order is L, R, L, R, ...).
            assert float(chunk.samples[0, 0]) == float(i)
            assert float(chunk.samples[0, 1]) == -float(i)
            assert float(chunk.samples[-1, 0]) == float(i)
            assert float(chunk.samples[-1, 1]) == -float(i)

    async def test_raises_when_not_connected(self):
        client = SpeakerClient()
        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in client.stream():
                pass
