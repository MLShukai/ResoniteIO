"""E2E: stream Speaker audio from a live Resonite and record to WAV.

48 kHz / Stereo / float32 LE は ``SpeakerService`` の固定 wire format。
本テストは ``SpeakerClient.stream()`` の生 chunk を受けて
:class:`resoio.cli.record._WavFloat32Writer` (CLI 実装と完全に同じ writer)
で WAV を書き出し、生成された WAV header を ``struct.unpack`` で直接 parse
して format / channels / sample rate / data size が wire spec に一致する
ことを確認する。

WAV header を ``wave`` 標準モジュールで読まない理由: 標準 ``wave`` は
``WAVE_FORMAT_IEEE_FLOAT (0x0003)`` を ``Error: unknown format`` で拒否
する (整数 PCM 専用)。CLI 側 ``record.py`` が手書き struct で生成して
いる format でもあるため、本テストでも対称的に手書き struct で検証する。

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import struct
import time
from datetime import datetime
from pathlib import Path

import grpclib
import numpy as np
from grpclib.const import Status

from resoio.cli.record import _WavFloat32Writer  # noqa: PLC2701
from resoio.speaker import CHANNELS, SAMPLE_RATE, AudioChunk, SpeakerClient
from tests.helpers import mark_e2e

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# 10 s × 48000 sample/s × 2 ch × 4 byte = 3.84 MB を期待。下限は loose
# (Resonite 起動直後の WASAPI driver warm-up と Bridge attach 遅延を
# 数秒分許容する)。
_CAPTURE_SECONDS = 10.0
_BYTES_PER_SAMPLE = 4
_BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * _BYTES_PER_SAMPLE  # 384000
_MIN_BYTES = int(_BYTES_PER_SECOND * 5.0)  # at least 5 s of audio

# UDS bind と AudioSystem.PrimaryOutput の準備の間に gap があり、その間
# Speaker Bridge は FAILED_PRECONDITION を返す。Camera と同じ retry 契約
# (ICameraBridge / ISpeakerBridge docstring 参照)。
_SPEAKER_READY_TIMEOUT_S = 120.0
_SPEAKER_READY_RETRY_INTERVAL_S = 2.0

# `just resonite-start` 経路で Resonite を起動した直後は
# AudioOutputDriver が 'Dummy Output' などの null driver に attach して
# 一時的にゼロ buffer を吐く期間がある (decompile 上 audio system の
# driver enumeration が deferred で、PulseAudio device が後追いで
# 認識される)。最初の非ゼロ chunk が来るまで wait することで、
# 本録音の peak > 0 assertion が安定する。
_SPEAKER_AUDIO_WARMUP_TIMEOUT_S = 60.0

# WAV header layout (cli/record.py と同じ規約。重複は意図的: テスト側で
# CLI の format spec を独立に再現することで「writer が壊れた / spec が
# silently drift した」のどちらでも catch できる)。
_WAVE_FORMAT_IEEE_FLOAT = 0x0003
_HEADER_FMT = "<4sI4s4sIHHIIHH4sI"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_BITS_PER_SAMPLE = 32


class TestSpeakerRecord:
    @mark_e2e
    def test_record_to_wav(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"speaker_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "record.wav"

        def _chunk_has_audio(chunk: AudioChunk) -> bool:
            """Return True when ``chunk`` carries any non-zero sample.

            'Dummy Output' driver emits zero-valued frames at the
            correct rate, so a chunk arriving is necessary but not
            sufficient for "audio is flowing". See
            _SPEAKER_AUDIO_WARMUP_TIMEOUT_S.
            """
            arr = np.frombuffer(chunk.samples.tobytes(), dtype=np.float32)
            return bool(np.any(arr != 0.0))

        async def wait_for_speaker_ready() -> None:
            ready_deadline = time.monotonic() + _SPEAKER_READY_TIMEOUT_S
            audio_deadline = time.monotonic() + _SPEAKER_AUDIO_WARMUP_TIMEOUT_S
            while True:
                try:
                    async with SpeakerClient() as spk:
                        async for chunk in spk.stream():
                            if _chunk_has_audio(chunk):
                                # First non-zero chunk means the engine's
                                # real audio driver is wired up.
                                return
                            if time.monotonic() > audio_deadline:
                                raise TimeoutError(
                                    "Speaker bridge attached but produced "
                                    "only zero-valued frames for "
                                    f"{_SPEAKER_AUDIO_WARMUP_TIMEOUT_S:.0f}s. "
                                    "Check `gale/BepInEx/LogOutput.log` for "
                                    "the 'FrooxEngineSpeakerBridge' driver "
                                    "name; 'Dummy Output' means Wine has no "
                                    "PulseAudio / PipeWire passthrough."
                                )
                            # Stay subscribed: opening / closing the stream
                            # repeatedly would only re-do the FAILED_PRECONDITION
                            # warm-up, not advance the audio device.
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() > ready_deadline:
                        raise TimeoutError(
                            f"Speaker bridge did not become ready in "
                            f"{_SPEAKER_READY_TIMEOUT_S:.0f}s "
                            f"(last reason: {e.message})"
                        ) from e
                    await asyncio.sleep(_SPEAKER_READY_RETRY_INTERVAL_S)

        async def record() -> tuple[int, int]:
            """Return (chunk_count, bytes_written)."""
            await wait_for_speaker_ready()
            writer = _WavFloat32Writer()
            writer.open(out_path)
            chunk_count = 0
            try:
                deadline = time.monotonic() + _CAPTURE_SECONDS
                async with SpeakerClient() as spk:
                    async for chunk in spk.stream():
                        writer.write(chunk)
                        chunk_count += 1
                        if time.monotonic() >= deadline:
                            break
            finally:
                writer.close()
            return chunk_count, out_path.stat().st_size - _HEADER_SIZE

        chunks, data_bytes = asyncio.run(record())

        # Surface the artifact path even on green CI runs.
        print(f"E2E artifact dir: {out_dir}")
        print(f"E2E WAV: {out_path} ({out_path.stat().st_size} bytes, {chunks} chunks)")

        assert out_path.exists(), f"WAV not created at {out_path}"
        assert chunks > 0, "Speaker bridge yielded no audio chunks"
        assert data_bytes >= _MIN_BYTES, (
            f"expected >= {_MIN_BYTES} bytes (~5 s of audio) in "
            f"{_CAPTURE_SECONDS:.0f}s capture, got {data_bytes}"
        )

        # Validate WAV header manually because the stdlib `wave` module
        # rejects WAVE_FORMAT_IEEE_FLOAT (0x0003).
        with open(out_path, "rb") as f:
            raw = f.read(_HEADER_SIZE)
        (
            riff_tag,
            riff_size,
            wave_tag,
            fmt_tag,
            fmt_size,
            fmt_code,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            data_tag,
            data_size,
        ) = struct.unpack(_HEADER_FMT, raw)

        assert riff_tag == b"RIFF"
        assert wave_tag == b"WAVE"
        assert fmt_tag == b"fmt "
        assert data_tag == b"data"
        assert fmt_size == 16
        assert fmt_code == _WAVE_FORMAT_IEEE_FLOAT, (
            f"WAV format must be IEEE_FLOAT (0x0003), got 0x{fmt_code:04x}"
        )
        assert channels == CHANNELS
        assert sample_rate == SAMPLE_RATE
        assert bits_per_sample == _BITS_PER_SAMPLE
        assert block_align == CHANNELS * _BYTES_PER_SAMPLE
        assert byte_rate == SAMPLE_RATE * CHANNELS * _BYTES_PER_SAMPLE
        assert data_size == data_bytes, (
            f"data chunk size header ({data_size}) must match the on-disk "
            f"payload size ({data_bytes}) — Ctrl+C / duration patch path bug?"
        )
        assert riff_size == 36 + data_size, (
            f"RIFF chunk size header ({riff_size}) must equal 36 + data_size "
            f"({36 + data_size})"
        )

        # Audio content sanity check: ``wait_for_speaker_ready`` already
        # blocked until the first non-zero chunk, so by this point the
        # audio device is warmed up and the entire recording should
        # contain real samples.
        with open(out_path, "rb") as f:
            f.seek(_HEADER_SIZE)
            payload = f.read()
        samples = np.frombuffer(payload, dtype=np.float32).reshape(-1, CHANNELS)
        peak = float(np.max(np.abs(samples)))
        assert peak > 0.0, (
            f"Captured audio peak is 0 across the entire {_CAPTURE_SECONDS:.0f}s "
            "recording even though the warm-up gate observed a non-zero "
            "chunk. The driver may have flipped back to a null output "
            "mid-recording. Check `gale/BepInEx/LogOutput.log` for "
            "'FrooxEngineSpeakerBridge' re-attach lines."
        )
        print(f"Audio content sanity OK: peak amplitude = {peak:.6f}")
