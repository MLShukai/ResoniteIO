"""Media I/O helpers for the ``resoio record`` subcommand.

These are the codec / container primitives the recording routes lean on,
deliberately kept separate from the argparse + dispatch layer in
:mod:`resoio.cli.record` so each side stays focused: this module knows
nothing about ``argparse.Namespace`` or the gRPC clients, only about
turning frames / samples into Y4M, WAV, and PyAV-muxed bytes.

The recording routes split along a deliberate boundary: Y4M, raw PCM and
WAV are emitted with stdlib + numpy because their wire formats are trivial
and adding a PyAV dependency for those paths would only hurt startup time
and the dependency footprint. PyAV is reserved for H.264 / AAC encoding
and container muxing where re-implementing codecs is out of scope.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    import av
    from av.audio.stream import AudioStream
    from av.container import OutputContainer
    from av.video.stream import VideoStream

    from resoio.speaker import SpeakerChunk

# Names re-imported by resoio.cli.record. They keep their ``_`` prefix per the
# project's private-module convention; listing them here marks the module's
# exported surface so pyright accepts the cross-module import (mirrors how
# resoio._client exports ``_BaseClient``).
__all__ = [
    "_MuxedState",
    "_WavFloat32Writer",
    "_build_placeholder_header",
    "_fps_to_fraction",
    "_mux_audio_packets",
    "_mux_video_packets",
    "_suppress_teardown_errors",
    "_video_pts_from_nanos",
    "_y4m_write_frame",
    "_y4m_write_header",
]


# ---------------------------------------------------------------------------
# Y4M helpers (formerly in resoio.cli.y4m, now private to this module)
# ---------------------------------------------------------------------------


def _fps_to_fraction(fps: float) -> tuple[int, int]:
    """Return ``(numerator, denominator)`` for the Y4M ``F`` header field.

    The fraction is bounded to a denominator of at most ``1000``; integer
    rates like ``30.0`` collapse to ``(30, 1)``.

    >>> _fps_to_fraction(30.0)
    (30, 1)
    """
    frac = Fraction(fps).limit_denominator(1000)
    return frac.numerator, frac.denominator


def _y4m_write_header(
    out: BinaryIO, width: int, height: int, fps_num: int, fps_den: int
) -> None:
    """Write a Y4M stream header (C444, square pixels, progressive)."""
    header = (
        f"YUV4MPEG2 W{width} H{height} F{fps_num}:{fps_den} Ip A1:1 C444\n"
    ).encode("ascii")
    out.write(header)


def _y4m_write_frame(out: BinaryIO, rgba: NDArray[np.uint8]) -> None:
    """Write one Y4M frame (``FRAME`` marker plus Y/U/V planes, C444)."""
    y, u, v = _rgba_to_yuv444(rgba)
    out.write(b"FRAME\n")
    out.write(y.tobytes())
    out.write(u.tobytes())
    out.write(v.tobytes())


def _rgba_to_yuv_planes(
    rgba: NDArray[np.uint8],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Apply BT.601 full-range matrix; return float planes pre-clip."""
    r = rgba[..., 0].astype(np.float64)
    g = rgba[..., 1].astype(np.float64)
    b = rgba[..., 2].astype(np.float64)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = -0.168736 * r - 0.331264 * g + 0.5 * b + 128.0
    v = 0.5 * r - 0.418688 * g - 0.081312 * b + 128.0
    return y, u, v


def _rgba_to_yuv444(
    rgba: NDArray[np.uint8],
) -> tuple[NDArray[np.uint8], NDArray[np.uint8], NDArray[np.uint8]]:
    """Convert RGBA8 ``(H, W, 4)`` to BT.601 full-range YUV 4:4:4."""
    y, u, v = _rgba_to_yuv_planes(rgba)
    y8 = np.clip(y, 0.0, 255.0).astype(np.uint8)
    u8 = np.clip(u, 0.0, 255.0).astype(np.uint8)
    v8 = np.clip(v, 0.0, 255.0).astype(np.uint8)
    return y8, u8, v8


# ---------------------------------------------------------------------------
# WAV writer (unchanged from the previous record.py)
# ---------------------------------------------------------------------------

# RIFF / WAVE / fmt / data layout for fixed 48 kHz stereo float32 LE.
# Header size (offset 0..43) is constant — only the two size fields
# (offset 4 = RIFF chunk size, offset 40 = data chunk size) are patched
# back in on close once the total byte count is known.
_HEADER_SIZE = 44
_WAVE_FORMAT_IEEE_FLOAT = 0x0003
_FMT_CHUNK_SIZE = 16
_CHANNELS = 2
_SAMPLE_RATE = 48000
_BITS_PER_SAMPLE = 32
_BYTES_PER_SAMPLE = _BITS_PER_SAMPLE // 8  # 4
_BLOCK_ALIGN = _CHANNELS * _BYTES_PER_SAMPLE  # 8
_BYTE_RATE = _SAMPLE_RATE * _BLOCK_ALIGN  # 384000

_RIFF_SIZE_OFFSET = 4
_DATA_SIZE_OFFSET = 40


def _build_placeholder_header() -> bytes:
    """Build the 44-byte WAV header with placeholder size fields (zeros).

    Size fields at offsets 4 and 40 are written as ``0`` and patched in
    :meth:`_WavFloat32Writer.close` once the streamed byte count is known.
    """
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        0,  # RIFF chunk size (patched on close)
        b"WAVE",
        b"fmt ",
        _FMT_CHUNK_SIZE,
        _WAVE_FORMAT_IEEE_FLOAT,
        _CHANNELS,
        _SAMPLE_RATE,
        _BYTE_RATE,
        _BLOCK_ALIGN,
        _BITS_PER_SAMPLE,
        b"data",
        0,  # data chunk size (patched on close)
    )


class _WavFloat32Writer:
    """Streaming WAV writer for 48 kHz / Stereo / float32 LE samples.

    Standard library only (``struct`` + raw file I/O): the stdlib
    :mod:`wave` module rejects ``WAVE_FORMAT_IEEE_FLOAT`` and the project
    declines ``soundfile`` / ``scipy`` as runtime deps. The header is
    written once with placeholder size fields, frame payloads are
    appended, and the two size fields are seeked-and-patched on
    :meth:`close`.
    """

    def __init__(self) -> None:
        self._fp: BinaryIO | None = None
        self._bytes_written = 0

    def open(self, path: str | Path) -> None:
        """Open ``path`` for binary write and emit the placeholder header."""
        if self._fp is not None:
            raise RuntimeError("_WavFloat32Writer.open called twice without close")
        fp = open(path, "wb")
        fp.write(_build_placeholder_header())
        self._fp = fp
        self._bytes_written = 0

    def write(self, chunk: SpeakerChunk) -> None:
        """Append one chunk's interleaved float32 LE samples to the file.

        ``chunk.samples`` is ``(N, 2)`` float32; ``tobytes()`` returns a
        fresh contiguous byte string in native byte order, which is
        little-endian on every platform Resonite supports.
        """
        fp = self._fp
        if fp is None:
            raise RuntimeError("_WavFloat32Writer.write called before open")
        payload = chunk.samples.tobytes()
        fp.write(payload)
        self._bytes_written += len(payload)

    def close(self) -> None:
        """Patch the RIFF / data chunk sizes and close the file.

        Idempotent: calling ``close()`` again is a no-op so callers
        do not need to guard against double-close from the duration
        timeout + finally paths.
        """
        fp = self._fp
        if fp is None:
            return
        self._fp = None
        try:
            data_size = self._bytes_written
            riff_size = 36 + data_size
            fp.seek(_RIFF_SIZE_OFFSET)
            fp.write(struct.pack("<I", riff_size))
            fp.seek(_DATA_SIZE_OFFSET)
            fp.write(struct.pack("<I", data_size))
        finally:
            fp.close()


# ---------------------------------------------------------------------------
# PyAV packet muxing + teardown suppression
# ---------------------------------------------------------------------------


def _mux_video_packets(
    container: OutputContainer,
    v_stream: VideoStream,
    frame: av.VideoFrame | None,
) -> None:
    """Encode ``frame`` (or flush on ``None``) and mux every packet.

    Wrapped in a helper so the ``Packet[Unknown]`` return type from
    PyAV's stubs is contained behind one ``pyright: ignore`` — keeping
    the strict-mode footprint to a single line.
    """
    for packet in v_stream.encode(frame):  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        container.mux(packet)  # pyright: ignore[reportUnknownMemberType]


def _mux_audio_packets(
    container: OutputContainer,
    a_stream: AudioStream,
    frame: av.AudioFrame | None,
) -> None:
    """Encode ``frame`` (or flush on ``None``) and mux every audio packet.

    Symmetric to :func:`_mux_video_packets`: PyAV's AAC encoder accepts
    arbitrary input ``AudioFrame`` sizes (it FIFOs internally into 1024-
    sample AAC frames) so callers do not need an explicit
    ``av.AudioFifo``. The ``pyright: ignore`` is confined to the two
    lines that interact with PyAV's untyped packet stream.
    """
    for packet in a_stream.encode(frame):  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        container.mux(packet)  # pyright: ignore[reportUnknownMemberType]


def _suppress_teardown_errors(fn: Callable[[], None]) -> None:
    """Run ``fn`` and silently swallow broken-pipe / PyAV I/O errors.

    Used by ``_record_muxed`` to flush + close cleanly when stdout
    has already been closed by the downstream consumer (the classic
    ``resoio record | head`` / ``resoio record | ffmpeg`` shape). PyAV
    surfaces these as :class:`av.error.PyAVCallbackError` (the writer
    callback raised ``BrokenPipeError`` inside libav) rather than the
    bare :class:`BrokenPipeError`, so we have to catch both. File-backed
    outputs never raise here, so this suppression is a no-op for them.

    Lazy-imports ``av.error`` to keep the CLI's cold-start path off PyAV
    when the user is only invoking non-muxed routes.
    """
    import av.error

    try:
        fn()
    except (BrokenPipeError, av.error.PyAVCallbackError):
        pass


# ---------------------------------------------------------------------------
# Muxed A/V timing state
# ---------------------------------------------------------------------------


class _MuxedState:
    """Mutable bookkeeping shared between the muxed video and audio pumps.

    ``t0_nanos`` is the **shared** Unix-nanos timestamp of the earliest
    frame seen by either pump; both pumps anchor their PTS to it so the
    resulting mp4 / mkv preserves A/V sync. ``video_pts_seen`` /
    ``audio_pts_seen`` are used only as a sanity guard against
    monotonicity regressions (rare clock skew or a server re-emitting
    a frame with an older timestamp). asyncio is single-threaded so no
    locks are needed around these fields.
    """

    __slots__ = ("audio_pts_seen", "t0_nanos", "video_pts_seen")

    def __init__(self) -> None:
        self.t0_nanos: int | None = None
        self.video_pts_seen: int = -1
        self.audio_pts_seen: int = -1

    def anchor(self, unix_nanos: int) -> int:
        """Set ``t0_nanos`` on first call; return the shared value."""
        if self.t0_nanos is None:
            self.t0_nanos = unix_nanos
        return self.t0_nanos


def _video_pts_from_nanos(unix_nanos: int, t0_nanos: int) -> int:
    """Convert a Camera ``unix_nanos`` to a 1/90000-Hz PTS, clamped to ≥0.

    The spec (§7.1) fixes the video stream ``time_base`` to ``1/90000``
    because 90 kHz is the common MPEG presentation-timestamp clock and
    divides cleanly into the typical frame rates (30 fps → 3000 ticks).
    PTS is rounded to the nearest tick and clamped at zero so the first
    frame (whose nanos == ``t0_nanos``) lands exactly at PTS 0.

    >>> _video_pts_from_nanos(0, 0)
    0
    >>> _video_pts_from_nanos(33_333_333, 0)
    3000
    >>> _video_pts_from_nanos(0, 100)
    0
    """
    delta = max(0, unix_nanos - t0_nanos)
    # (delta_ns * 90000) / 1e9 == delta_ns * 90 / 1_000_000 (integer math).
    return (delta * 90 + 500_000) // 1_000_000
