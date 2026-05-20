"""Regenerate the canonical 440 Hz mono float32 WAV fixture.

Run manually after deliberately changing fixture parameters — the
committed ``sine_440hz_1s_mono_48k.wav`` is the source of truth and
CI must not regenerate it on every run.

WAV uses ``wFormatTag = 1`` (PCM) with ``sampwidth = 4`` so it
round-trips through stdlib :mod:`wave` (which rejects
``WAVE_FORMAT_IEEE_FLOAT`` / 0x0003 with "unknown format: 3"). The
4-byte payload bits are IEEE-754 LE float32 nonetheless, matching
``resoio.cli.mic._load_wav``'s sampwidth=4-is-float32 convention.

Usage::

    python python/tests/e2e/fixtures/generate_sine.py
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

# 5 s payload deliberately exceeds the bridge's 2 s ring buffer, so any
# future regression that drops WAV-mode pacing surfaces as dropped_frames
# in ``mic_send`` instead of slipping through unnoticed (1 s used to fit
# even when burst-sent).
_FREQUENCY_HZ = 440.0
_DURATION_S = 5.0
_AMPLITUDE = 0.5

# Wire format constants duplicated from ``resoio.microphone`` to keep
# this fixture script free of intra-package imports.
_SAMPLE_RATE = 48000
_CHANNELS = 1
_BITS_PER_SAMPLE = 32
_BYTES_PER_SAMPLE = _BITS_PER_SAMPLE // 8  # 4
_BLOCK_ALIGN = _CHANNELS * _BYTES_PER_SAMPLE  # 4
_BYTE_RATE = _SAMPLE_RATE * _BLOCK_ALIGN  # 192000

_HEADER_FMT = "<4sI4s4sIHHIIHH4sI"
_FMT_CHUNK_SIZE = 16
# stdlib :mod:`wave` rejects 0x0003 (IEEE_FLOAT); use PCM tag (0x0001)
# even though payload bytes are still IEEE-754 LE float32. The consumer
# treats sampwidth=4 as float32 by convention.
_WAVE_FORMAT_PCM = 0x0001

# Filename keeps the historic "1s" suffix for git-history continuity —
# actual length follows ``_DURATION_S``. Renaming churns every reference
# without changing behaviour.
_FIXTURE_PATH = Path(__file__).parent / "sine_440hz_1s_mono_48k.wav"


def _sine_samples() -> np.ndarray:
    """Return the mono float32 sine samples for the configured parameters.

    ``endpoint=False`` so the sample grid stays canonical
    (``[0, 1/sr, ..., (N-1)/sr]``) — no boundary point duplicated.
    """
    n_samples = int(_SAMPLE_RATE * _DURATION_S)
    t = np.linspace(0.0, _DURATION_S, n_samples, endpoint=False, dtype=np.float64)
    samples = _AMPLITUDE * np.sin(2.0 * np.pi * _FREQUENCY_HZ * t)
    return samples.astype(np.float32, copy=False)


def _build_header(data_bytes: int) -> bytes:
    """Build a RIFF / WAVE / fmt / data header for ``data_bytes`` of PCM.

    Total length is known up-front so the chunk sizes are written
    directly (no patch-on-close as in the streaming Speaker writer).
    """
    riff_size = 36 + data_bytes
    return struct.pack(
        _HEADER_FMT,
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        _FMT_CHUNK_SIZE,
        _WAVE_FORMAT_PCM,
        _CHANNELS,
        _SAMPLE_RATE,
        _BYTE_RATE,
        _BLOCK_ALIGN,
        _BITS_PER_SAMPLE,
        b"data",
        data_bytes,
    )


def write_fixture(path: Path = _FIXTURE_PATH) -> Path:
    """Write the sine fixture and return the path.

    Idempotent — output is fully determined by the module-level
    constants, so re-running produces a byte-identical file.
    """
    samples = _sine_samples()
    payload = samples.tobytes()
    header = _build_header(len(payload))
    path.write_bytes(header + payload)
    return path


if __name__ == "__main__":
    out = write_fixture()
    print(f"wrote {out} ({out.stat().st_size} bytes)")
