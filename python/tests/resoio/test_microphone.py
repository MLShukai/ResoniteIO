import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    MicrophoneAudioFrame,
    MicrophoneBase,
    MicrophoneStreamSummary as _WireSummary,
)
from resoio.microphone import (
    CHANNELS,
    DTYPE,
    SAMPLE_RATE,
    MicrophoneAudioChunk,
    MicrophoneClient,
    MicrophoneStreamSummary,
    paced,
)

_SAMPLES_PER_FRAME = 256


def _make_chunk_samples(frame_index: int) -> np.ndarray:
    """Constant payload = ``frame_index`` so every byte traces to its source
    frame."""
    return np.full(_SAMPLES_PER_FRAME, float(frame_index), dtype=np.float32)


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


async def _chunks(
    items: list[MicrophoneAudioChunk],
) -> AsyncIterator[MicrophoneAudioChunk]:
    for chunk in items:
        yield chunk


class TestMicrophoneClient:
    async def test_round_trip_over_uds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-microphone.sock"
        fake = _RecordingMicrophone()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            scenario = [
                MicrophoneAudioChunk(samples=_make_chunk_samples(i), frame_id=i)
                for i in range(3)
            ]
            async with MicrophoneClient() as client:
                assert client.socket_path == str(socket_path)
                summary = await client.stream(_chunks(scenario))

            assert isinstance(summary, MicrophoneStreamSummary)
            assert summary.received_frames == 3
            assert summary.received_samples == 3 * _SAMPLES_PER_FRAME
            assert summary.dropped_frames == 0
            assert summary.unix_nanos > 0

            assert len(fake.received) == 3
            for sent, got in zip(scenario, fake.received, strict=True):
                assert got.frame_id == sent.frame_id
                assert got.sample_count == _SAMPLES_PER_FRAME
                # Client stamps unix_nanos when caller leaves it at 0.
                assert got.unix_nanos > 0
                decoded = np.frombuffer(got.samples, dtype=np.float32)
                assert decoded.shape == (_SAMPLES_PER_FRAME,)
                np.testing.assert_array_equal(decoded, sent.samples)
        finally:
            server.close()
            await server.wait_closed()

    async def test_raises_when_not_connected(self):
        client = MicrophoneClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.stream(
                _chunks(
                    [MicrophoneAudioChunk(samples=_make_chunk_samples(0), frame_id=0)]
                )
            )

    async def test_frame_id_is_passed_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-microphone.sock"
        fake = _RecordingMicrophone()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            # Non-contiguous IDs — client must not renumber them.
            sent_ids = [0, 1, 2, 7, 8]
            scenario = [
                MicrophoneAudioChunk(samples=_make_chunk_samples(0), frame_id=fid)
                for fid in sent_ids
            ]
            async with MicrophoneClient() as client:
                await client.stream(_chunks(scenario))

            assert [f.frame_id for f in fake.received] == sent_ids
        finally:
            server.close()
            await server.wait_closed()

    async def test_explicit_unix_nanos_is_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-microphone.sock"
        fake = _RecordingMicrophone()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            # Replay scenarios depend on the explicit timestamp surviving.
            explicit_ts = 1_700_000_000_000_000_000
            chunk = MicrophoneAudioChunk(
                samples=_make_chunk_samples(0),
                frame_id=0,
                unix_nanos=explicit_ts,
            )
            async with MicrophoneClient() as client:
                await client.stream(_chunks([chunk]))

            assert len(fake.received) == 1
            assert fake.received[0].unix_nanos == explicit_ts
        finally:
            server.close()
            await server.wait_closed()


class TestModuleConstants:
    def test_fixed_format(self):
        assert SAMPLE_RATE == 48000
        assert CHANNELS == 1
        assert DTYPE == np.dtype(np.float32)


class TestPaced:
    async def test_yields_at_real_time(self):
        samples_per_chunk = 480
        n_chunks = 3
        sample_rate = 48000
        expected_s = n_chunks * samples_per_chunk / sample_rate  # 30 ms

        chunks_in = [
            MicrophoneAudioChunk(
                samples=np.zeros(samples_per_chunk, dtype=np.float32),
                frame_id=i,
            )
            for i in range(n_chunks)
        ]

        start = time.monotonic()
        collected: list[MicrophoneAudioChunk] = []
        async for chunk in paced(_chunks(chunks_in), sample_rate=sample_rate):
            collected.append(chunk)
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

    async def test_passes_through_chunk_payload(self):
        samples_in = np.array([0.1, -0.2, 0.3], dtype=np.float32)
        chunk_in = MicrophoneAudioChunk(
            samples=samples_in, frame_id=42, unix_nanos=1_700_000_000_000_000_000
        )
        # Huge sample_rate collapses the sleep so the test stays fast.
        out: list[MicrophoneAudioChunk] = []
        async for chunk in paced(_chunks([chunk_in]), sample_rate=10_000_000):
            out.append(chunk)
        assert len(out) == 1
        assert out[0].frame_id == 42
        assert out[0].unix_nanos == 1_700_000_000_000_000_000
        np.testing.assert_array_equal(out[0].samples, samples_in)

    async def test_handles_empty_iterable(self):
        # Tiny sample_rate so a stray sleep would obviously time out.
        start = time.monotonic()
        out: list[MicrophoneAudioChunk] = []
        async for chunk in paced(_chunks([]), sample_rate=1):
            out.append(chunk)
        elapsed = time.monotonic() - start
        assert out == []
        assert elapsed < 0.05, (
            f"paced over empty iter took {elapsed * 1000:.1f} ms — expected ~0"
        )
