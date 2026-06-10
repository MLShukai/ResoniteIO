import time
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

import numpy as np
import pytest

from resoio._generated.resonite_io.v1 import (
    MicrophoneAudioFrame,
    MicrophoneBase,
    MicrophoneStreamSummary as _WireSummary,
)
from resoio.microphone import (
    MicrophoneClient,
    MicrophoneStreamSummary,
    paced,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

_SAMPLES_PER_FRAME = 256


def _make_chunk_samples(value: float) -> np.ndarray:
    """Constant payload = ``value`` so every byte traces to its source
    frame."""
    return np.full(_SAMPLES_PER_FRAME, float(value), dtype=np.float32)


class _RecordingMicrophone(MicrophoneBase):
    """In-process fake that records every received frame."""

    def __init__(self) -> None:
        self.received: list[MicrophoneAudioFrame] = []

    async def stream_audio(
        self, messages: AsyncIterator[MicrophoneAudioFrame]
    ) -> _WireSummary:
        async for frame in messages:
            self.received.append(frame)
        return _WireSummary(
            received_frames=len(self.received),
            received_samples=sum(f.sample_count for f in self.received),
            dropped_frames=0,
            unix_nanos=time.time_ns(),
        )


async def _arrays(
    items: list[np.ndarray],
) -> AsyncIterator[np.ndarray]:
    for arr in items:
        yield arr


class TestMicrophoneClient:
    async def test_round_trip_over_uds(self, uds_server: UdsServer):
        fake = _RecordingMicrophone()
        socket_path = await uds_server(fake)
        # Caller hands the client plain float32 ndarrays — no chunk wrapper.
        scenario = [_make_chunk_samples(i) for i in range(3)]
        async with MicrophoneClient() as client:
            assert client.socket_path == socket_path
            summary = await client.stream(_arrays(scenario))

        assert isinstance(summary, MicrophoneStreamSummary)
        assert summary.received_frames == 3
        assert summary.received_samples == 3 * _SAMPLES_PER_FRAME
        assert summary.dropped_frames == 0
        assert summary.unix_nanos > 0

        assert len(fake.received) == 3
        for sent, got in zip(scenario, fake.received, strict=True):
            assert got.sample_count == _SAMPLES_PER_FRAME
            # Client stamps unix_nanos on every chunk.
            assert got.unix_nanos > 0
            decoded = np.frombuffer(got.samples, dtype=np.float32)
            assert decoded.shape == (_SAMPLES_PER_FRAME,)
            # float32 bytes round-trip unchanged through the wire.
            np.testing.assert_array_equal(decoded, sent)

    async def test_client_assigns_monotonic_frame_ids_from_zero(
        self, uds_server: UdsServer
    ):
        # The client owns frame_id: regardless of input order, the wire frames
        # must be numbered 0, 1, 2, ... in send order.
        fake = _RecordingMicrophone()
        await uds_server(fake)
        scenario = [_make_chunk_samples(v) for v in (5.0, -3.0, 1.0, 0.0)]
        async with MicrophoneClient() as client:
            await client.stream(_arrays(scenario))

        assert [f.frame_id for f in fake.received] == [0, 1, 2, 3]

    async def test_sample_count_matches_array_length(self, uds_server: UdsServer):
        # sample_count is derived from the array length, not a fixed constant.
        fake = _RecordingMicrophone()
        await uds_server(fake)
        scenario = [
            np.zeros(10, dtype=np.float32),
            np.zeros(512, dtype=np.float32),
            np.zeros(1, dtype=np.float32),
        ]
        async with MicrophoneClient() as client:
            await client.stream(_arrays(scenario))

        assert [f.sample_count for f in fake.received] == [10, 512, 1]

    async def test_raises_when_not_connected(self):
        client = MicrophoneClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.stream(_arrays([_make_chunk_samples(0)]))


class TestPaced:
    async def test_yields_at_real_time(self):
        samples_per_chunk = 480
        n_chunks = 3
        sample_rate = 48000
        expected_s = n_chunks * samples_per_chunk / sample_rate  # 30 ms

        arrays_in = [
            np.zeros(samples_per_chunk, dtype=np.float32) for _ in range(n_chunks)
        ]

        start = time.monotonic()
        collected: list[np.ndarray] = []
        async for arr in paced(_arrays(arrays_in), sample_rate=sample_rate):
            collected.append(arr)
        elapsed = time.monotonic() - start

        assert len(collected) == n_chunks
        # Slack of 5 ms / 250 ms absorbs event-loop jitter on busy CI;
        # the point is "noticeably > 0", not microsecond precision.
        assert elapsed >= expected_s - 0.005, (
            f"paced returned faster than real-time: {elapsed * 1000:.1f} ms "
            f"< {expected_s * 1000:.1f} ms - 5 ms slack"
        )
        assert elapsed < expected_s + 0.250, (
            f"paced is much slower than real-time: {elapsed * 1000:.1f} ms"
        )

    async def test_passes_through_array_payload(self):
        samples_in = np.array([0.1, -0.2, 0.3], dtype=np.float32)
        # Huge sample_rate collapses the sleep so the test stays fast.
        out: list[np.ndarray] = []
        async for arr in paced(_arrays([samples_in]), sample_rate=10_000_000):
            out.append(arr)
        assert len(out) == 1
        np.testing.assert_array_equal(out[0], samples_in)

    async def test_handles_empty_iterable(self):
        # Tiny sample_rate so a stray sleep would obviously time out.
        empty: AsyncIterable[np.ndarray] = _arrays([])
        start = time.monotonic()
        out: list[np.ndarray] = []
        async for arr in paced(empty, sample_rate=1):
            out.append(arr)
        elapsed = time.monotonic() - start
        assert out == []
        assert elapsed < 0.05, (
            f"paced over empty iter took {elapsed * 1000:.1f} ms — expected ~0"
        )
