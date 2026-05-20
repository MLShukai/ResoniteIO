"""Regenerate the canonical 440 Hz mono float32 WAV fixture.

Run manually after deliberately changing the fixture parameters; the
committed ``sine_440hz_1s_mono_48k.wav`` is the source of truth used by
:mod:`tests.e2e.mic_send` and CI must not silently re-generate it on
every test run.

Format: 1 second of a 440 Hz sine wave at 48 kHz, mono, float32 LE
samples in ``[-0.5, 0.5]`` (amplitude 0.5 avoids any clipping margin
while staying comfortably audible). The WAV uses ``wFormatTag = 1``
(PCM) with ``sampwidth = 4`` so it round-trips through stdlib
:mod:`wave` (which rejects ``WAVE_FORMAT_IEEE_FLOAT`` / 0x0003 with
"unknown format: 3") — the same shape ``resoio mic -i ...`` expects
via :func:`resoio.cli.mic._load_wav` (sampwidth=4 is committed to
float32 there). The 4-byte payload bits themselves are IEEE-754
little-endian float32, so a more permissive reader (libsndfile,
scipy.io.wavfile) decodes the file as float32 PCM unchanged.

Usage::

    python python/tests/e2e/fixtures/generate_sine.py

The script is fully deterministic (``numpy.sin`` on a fixed time
vector, no randomness) and overwrites the fixture in place.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

# Sine parameters. These must stay in lock-step with the assertions in
# ``tests/e2e/mic_send.py`` — if any of these change, regenerate the
# fixture and update the consumer's expected chunk / sample counts.
_FREQUENCY_HZ = 440.0
_DURATION_S = 1.0
_AMPLITUDE = 0.5

# Wire format constants. Mono float32 LE at 48 kHz matches
# ``resoio.microphone.SAMPLE_RATE / CHANNELS / DTYPE``; importing those
# here would couple a stand-alone fixture script to the package install,
# so the numbers are duplicated intentionally and cross-checked by the
# consumer's assertions.
_SAMPLE_RATE = 48000
_CHANNELS = 1
_BITS_PER_SAMPLE = 32
_BYTES_PER_SAMPLE = _BITS_PER_SAMPLE // 8  # 4
_BLOCK_ALIGN = _CHANNELS * _BYTES_PER_SAMPLE  # 4
_BYTE_RATE = _SAMPLE_RATE * _BLOCK_ALIGN  # 192000

# RIFF / fmt / data header layout. Identical struct format to
# ``resoio.cli.record._build_placeholder_header`` (kept duplicated to
# keep the fixture script free of intra-package imports).
_HEADER_FMT = "<4sI4s4sIHHIIHH4sI"
_FMT_CHUNK_SIZE = 16
# Use WAVE_FORMAT_PCM (0x0001) so stdlib :mod:`wave` accepts the file.
# The actual bit pattern of every 4-byte sample is IEEE-754 LE float32
# (the consumer's loader treats sampwidth=4 as float32 by convention).
_WAVE_FORMAT_PCM = 0x0001

_FIXTURE_PATH = Path(__file__).parent / "sine_440hz_1s_mono_48k.wav"


def _sine_samples() -> np.ndarray:
    """Return the mono float32 sine samples for the configured parameters.

    Uses ``np.linspace(..., endpoint=False)`` so the sample grid is
    ``[0, 1/sr, 2/sr, ..., (N-1)/sr]`` — the canonical 1-second window
    that yields exactly ``sample_rate`` samples without duplicating the
    boundary point.
    """
    n_samples = int(_SAMPLE_RATE * _DURATION_S)
    t = np.linspace(0.0, _DURATION_S, n_samples, endpoint=False, dtype=np.float64)
    samples = _AMPLITUDE * np.sin(2.0 * np.pi * _FREQUENCY_HZ * t)
    return samples.astype(np.float32, copy=False)


def _build_header(data_bytes: int) -> bytes:
    """Build a RIFF / WAVE / fmt / data header for ``data_bytes`` of PCM.

    ``data_bytes`` is the size of the trailing samples payload only —
    the RIFF chunk size header (``36 + data_bytes``) and the data chunk
    size header (``data_bytes``) are written directly so no patch-on-
    close logic is needed (unlike the streaming Speaker writer).
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
    """Write the sine fixture to ``path`` and return the path.

    Idempotent: the output is fully determined by the module-level
    constants, so re-running produces a byte-identical file (modulo
    filesystem mtime).
    """
    samples = _sine_samples()
    payload = samples.tobytes()
    header = _build_header(len(payload))
    path.write_bytes(header + payload)
    return path


if __name__ == "__main__":
    out = write_fixture()
    print(f"wrote {out} ({out.stat().st_size} bytes)")
