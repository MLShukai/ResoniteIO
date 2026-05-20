import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    AudioFrame,
    SpeakerBase,
    SpeakerStreamRequest,
)
from resoio.speaker import (
    CHANNELS,
    DTYPE,
    SAMPLE_RATE,
    AudioChunk,
    SpeakerClient,
)

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
    async def test_round_trip_over_uds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-speaker.sock"
        server = Server([_ConstantSpeaker()])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            chunks: list[AudioChunk] = []
            async with SpeakerClient() as client:
                assert client.socket_path == str(socket_path)
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
        finally:
            server.close()
            await server.wait_closed()

    async def test_raises_when_not_connected(self):
        client = SpeakerClient()
        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in client.stream():
                pass


class TestModuleConstants:
    def test_fixed_format(self):
        assert SAMPLE_RATE == 48000
        assert CHANNELS == 2
        assert DTYPE == np.dtype(np.float32)
