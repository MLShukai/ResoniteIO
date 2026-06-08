"""``resoio record`` subcommand: video / audio / muxed media recording.

``--video`` / ``--audio`` are filter flags (not mutually exclusive)
rather than subcommands so the dispatcher stays single-binary and
users can compose them with one CLI surface — supplying neither
means "both" (muxed) so the common case is the shortest invocation.

The recording routes split along a deliberate boundary: Y4M, raw PCM
and WAV are emitted with stdlib + numpy because their wire formats
are trivial and adding a PyAV dependency for those paths would only
hurt startup time and the dependency footprint. PyAV is reserved for
H.264 / AAC encoding and container muxing where re-implementing
codecs is out of scope. Muxed output therefore only supports mp4
(file) and matroska (stdout) — the two containers PyAV can stream
reliably while preserving A/V sync via a single shared ``t0``.
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
import time
from collections.abc import AsyncIterator, Callable
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    import av
    from av.audio.stream import AudioStream
    from av.container import OutputContainer
    from av.video.stream import VideoStream

    from resoio.camera import CameraClient, Frame
    from resoio.speaker import SpeakerChunk


Mode = Literal["muxed", "video", "audio"]


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def _fps_arg(raw: str) -> float:
    """Parse ``--fps``; reject zero/negative so the Y4M header is sane."""
    value = float(raw)
    if value <= 0.0:
        raise argparse.ArgumentTypeError(f"--fps must be positive, got {value}")
    return value


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``record`` subparser on the top-level parser."""
    parser = subparsers.add_parser(
        "record",
        parents=[common],
        help="Record video, audio, or muxed video+audio to a file or stdout.",
        description=(
            "Record one or both of the Camera (video) and Speaker (audio) "
            "streams over the Resonite IO UDS. --video and --audio are "
            "filter flags (not exclusive); supplying neither records "
            "muxed video+audio. Output target is chosen by extension: "
            "stdout (-) emits Y4M / raw PCM / matroska per mode, files "
            "must end in .mp4 (video/muxed) or .wav (audio)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default="-",
        help=(
            'Output target; "-" emits Y4M / raw float32 PCM / matroska '
            "to stdout per mode, else a path ending in .mp4 / .wav "
            '(default: "-").'
        ),
    )
    parser.add_argument(
        "--video",
        action="store_true",
        help=(
            "Include the video (Camera) stream. Combine with --audio "
            "for an explicit muxed mode."
        ),
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        help=(
            "Include the audio (Speaker) stream. Combine with --video "
            "for an explicit muxed mode."
        ),
    )
    parser.add_argument(
        "--fps",
        type=_fps_arg,
        default=None,
        help=(
            "Video frame rate in Hz; defaults to 30.0 in video-bearing "
            "modes. Rejected when --audio is given alone."
        ),
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop after this many seconds (default: run until Ctrl-C).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Print per-frame stats to stderr (video only). Rejected "
            "when --audio is given alone."
        ),
    )
    parser.set_defaults(func=_run)


# ---------------------------------------------------------------------------
# mode resolution & arg validation
# ---------------------------------------------------------------------------


def _resolve_mode(args: argparse.Namespace) -> Mode:
    """Resolve filter flags into a single mode tag.

    Filter semantics: ``--video`` / ``--audio`` are not mutually
    exclusive, and supplying neither defaults to ``"muxed"``.

    >>> ns = argparse.Namespace
    >>> _resolve_mode(ns(video=False, audio=False))
    'muxed'
    >>> _resolve_mode(ns(video=True, audio=False))
    'video'
    >>> _resolve_mode(ns(video=False, audio=True))
    'audio'
    >>> _resolve_mode(ns(video=True, audio=True))
    'muxed'
    """
    video_enabled = (not args.audio) or args.video
    audio_enabled = (not args.video) or args.audio
    if video_enabled and audio_enabled:
        return "muxed"
    if video_enabled:
        return "video"
    return "audio"


def _validate_args(args: argparse.Namespace) -> int | None:
    """Validate flag/extension consistency.

    Returns ``None`` on success, or ``2`` after writing a one-line
    error to ``stderr``. The two checks run in this order so the
    user's *flag* mistake is surfaced before the *path* mistake:

    1. ``--fps`` / ``-v`` while ``mode == "audio"`` → reject.
    2. Output path (when not ``"-"``) extension mismatch per mode.
    """
    mode = _resolve_mode(args)
    if mode == "audio" and (args.fps is not None or args.verbose):
        print(
            "resoio record: --fps/-v require video; remove --audio or add --video",
            file=sys.stderr,
        )
        return 2

    target: str = args.output
    if target == "-":
        return None

    lower = target.lower()
    if mode == "muxed":
        if not lower.endswith(".mp4"):
            print(
                f"resoio record: unsupported output extension for muxed "
                f"mode: {target!r}. Use '-' (matroska stdout) or a path "
                "ending in '.mp4'.",
                file=sys.stderr,
            )
            return 2
    elif mode == "video":
        if not lower.endswith(".mp4"):
            print(
                f"resoio record: unsupported output extension for "
                f"video-only mode: {target!r}. Use '-' (Y4M stdout) or "
                "a path ending in '.mp4'.",
                file=sys.stderr,
            )
            return 2
    else:  # mode == "audio"
        if not lower.endswith(".wav"):
            print(
                f"resoio record: unsupported output extension for "
                f"audio-only mode: {target!r}. Use '-' (raw PCM stdout) "
                "or a path ending in '.wav'.",
                file=sys.stderr,
            )
            return 2
    return None


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
# Frame pacing — shared between video-Y4M, video-MP4, and (later) muxed.
# ---------------------------------------------------------------------------


async def _paced_frames(
    client: CameraClient,
    fps: float,
    *,
    verbose: bool,
) -> AsyncIterator[Frame]:
    """Yield one :class:`Frame` per ``1/fps``-second tick (drop-oldest).

    A background producer task consumes ``client.stream()`` as fast as
    the server emits frames, keeping the most recent one in
    ``latest_frame``. The generator wakes at a fixed cadence and yields
    that snapshot — duplicating it if the producer was slow, dropping
    intermediate frames if it was fast.

    Termination contract:

    * The generator stops cleanly (returns) when the producer's stream
      ends (``client.stream()`` exhausted).
    * The generator stops cleanly when the resolution of a freshly
      arrived frame differs from the first frame's resolution (the
      output container has a fixed header; mid-stream resize is not
      supported). This matches the legacy ``resoio capture`` behaviour.
    * Producer exceptions are propagated on the next iteration.
    * If the generator is cancelled (``aclose()`` / cancel of the
      consuming task) the producer task is cancelled and awaited so no
      background coroutine outlives the iterator.
    """
    output_period = 1.0 / fps

    latest_frame: Frame | None = None
    first_frame_arrived = asyncio.Event()
    producer_failure: BaseException | None = None

    async def producer() -> None:
        nonlocal latest_frame, producer_failure
        try:
            async for frame in client.stream():
                latest_frame = frame
                first_frame_arrived.set()
        except BaseException as exc:
            producer_failure = exc
            raise
        finally:
            # Unblock the consumer in every termination path (normal EOS,
            # zero-frame EOS, cancellation, error) so the generator never
            # deadlocks on `first_frame_arrived.wait()`.
            first_frame_arrived.set()

    producer_task = asyncio.create_task(producer())
    try:
        await first_frame_arrived.wait()
        if producer_failure is not None:
            raise producer_failure
        if latest_frame is None:
            # Producer finished cleanly without yielding a single frame —
            # nothing to pace; terminate the iterator quietly.
            return

        header_w = latest_frame.width
        header_h = latest_frame.height
        frame_count = 0
        next_emit = time.monotonic()

        while True:
            frame_to_emit: Frame = latest_frame
            if (frame_to_emit.width, frame_to_emit.height) != (header_w, header_h):
                # Output header is fixed at the first frame's dims; the
                # spec does not allow renegotiation mid-stream, so end
                # the iterator cleanly (consumer treats this as EOS).
                if verbose:
                    print(
                        f"frame {frame_to_emit.frame_id} resolution "
                        f"changed: {header_w}x{header_h} -> "
                        f"{frame_to_emit.width}x{frame_to_emit.height}; "
                        "stopping capture",
                        file=sys.stderr,
                    )
                return

            frame_count += 1
            if verbose:
                print(
                    f"frame {frame_to_emit.frame_id} "
                    f"{frame_to_emit.width}x{frame_to_emit.height} "
                    f"unix_nanos={frame_to_emit.unix_nanos} "
                    f"total={frame_count}",
                    file=sys.stderr,
                )
            yield frame_to_emit

            next_emit += output_period
            sleep_for = next_emit - time.monotonic()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            else:
                # Re-anchor: a long stall would otherwise emit a burst
                # of catch-up frames on recovery.
                next_emit = time.monotonic()

            if producer_task.done():
                exc = producer_task.exception()
                if exc is not None:
                    raise exc
                return
    finally:
        producer_task.cancel()
        try:
            await producer_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Recording routes — one async function per (mode, target_kind) pair.
# ---------------------------------------------------------------------------


async def _record_video_y4m(args: argparse.Namespace, out: BinaryIO) -> int:
    """Stream Camera frames as a Y4M (C444) byte stream to ``out``.

    ``BrokenPipeError`` is *not* caught here — :func:`_run` wraps the
    whole dispatch in one outer ``try/except BrokenPipeError`` so the
    "downstream closed stdout" case (e.g. ``... | head``) collapses to a
    single rc=0 path regardless of which write raised.
    """
    from resoio.camera import CameraClient

    fps: float = args.fps if args.fps is not None else 30.0
    fps_num, fps_den = _fps_to_fraction(fps)
    header_written = False

    async with CameraClient(args.socket) as client:
        async for frame in _paced_frames(client, fps, verbose=args.verbose):
            if not header_written:
                _y4m_write_header(out, frame.width, frame.height, fps_num, fps_den)
                header_written = True
            _y4m_write_frame(out, frame.pixels)
            out.flush()
    return 0


async def _record_video_mp4(args: argparse.Namespace, path: str) -> int:
    """Stream Camera frames as an H.264 (yuv420p) mp4 via PyAV.

    Flush ordering matters: encoder ``encode(None)`` must run *before*
    ``container.close()`` so the reorder-buffer's last packets land in
    the file before ``close()`` writes the moov atom. Both calls live in
    a single ``try/finally`` so cancellation (``--duration`` timeout) and
    exceptions still produce a well-formed mp4 (spec §7.6 MUST).
    """
    import av
    from av.video.stream import VideoStream

    from resoio.camera import CameraClient

    fps: float = args.fps if args.fps is not None else 30.0

    container = av.open(path, mode="w")
    # The "h264" overload of add_stream returns a VideoStream; pyright
    # widens to VideoStream | AudioStream | SubtitleStream, so narrow
    # explicitly to keep encode()/pix_fmt assignment strict-typed.
    raw_stream = container.add_stream("h264", rate=int(round(fps)))  # pyright: ignore[reportUnknownMemberType]
    assert isinstance(raw_stream, VideoStream)
    v_stream: VideoStream = raw_stream
    v_stream.pix_fmt = "yuv420p"

    header_written = False
    try:
        async with CameraClient(args.socket) as client:
            async for frame in _paced_frames(client, fps, verbose=args.verbose):
                if not header_written:
                    v_stream.width = frame.width
                    v_stream.height = frame.height
                    header_written = True
                # Drop alpha; copy to a contiguous (H,W,3) RGB24 buffer so
                # PyAV's strided memcpy into the VideoFrame is well-defined.
                rgb = np.ascontiguousarray(frame.pixels[..., :3])
                vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
                _mux_video_packets(container, v_stream, vf)
    finally:
        try:
            # Flush the encoder's reorder buffer before close() finalises
            # the moov atom; skipped if no frame ever arrived (header
            # never written → stream dims unset → encode would raise).
            if header_written:
                _mux_video_packets(container, v_stream, None)
        finally:
            container.close()
    return 0


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

    Used by :func:`_record_muxed` to flush + close cleanly when stdout
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


async def _record_audio_pcm(args: argparse.Namespace) -> int:
    """Stream raw float32 LE PCM to ``sys.stdout.buffer``.

    Stdout is non-seekable, so this path emits no WAV header — the
    consumer (typically ``ffmpeg -f f32le ...``) is expected to be told
    the sample rate / channels / format out-of-band.
    """
    from resoio.speaker import SpeakerClient

    out = sys.stdout.buffer
    async with SpeakerClient(args.socket) as client:
        async for chunk in client.stream():
            try:
                out.write(chunk.samples.tobytes())
                out.flush()
            except BrokenPipeError:
                # Downstream closed stdout (e.g. `... | head -c N`) — clean exit.
                return 0
    return 0


async def _record_audio_wav(args: argparse.Namespace, path: str) -> int:
    """Stream samples into a ``.wav`` file, patching sizes on close."""
    from resoio.speaker import SpeakerClient

    writer = _WavFloat32Writer()
    writer.open(path)
    try:
        async with SpeakerClient(args.socket) as client:
            async for chunk in client.stream():
                writer.write(chunk)
    finally:
        writer.close()
    return 0


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


async def _record_muxed(args: argparse.Namespace, target: str | None) -> int:
    """Stream Camera+Speaker into a muxed mp4 file or matroska stdout.

    ``target`` selects the container:

    * ``target is None`` → matroska on ``sys.stdout.buffer`` (so the
      output can be piped into ``ffmpeg`` or ``ffplay`` live).
    * ``target is not None`` → mp4 file at that path.

    Both pumps share a single :class:`_MuxedState` anchor for ``t0``
    (the earliest Unix-nanos seen by either side) so A/V sync is
    preserved across container formats. The classic flush MUST sequence
    is enforced by nested ``try/finally`` blocks: video encode(None) →
    audio encode(None) → ``container.close()``. Skipping any of those
    on the cancellation path would leave an unreadable mp4 (missing
    moov atom) or a truncated mkv cluster.
    """
    import av
    from av.audio.stream import AudioStream
    from av.video.stream import VideoStream

    from resoio.camera import CameraClient
    from resoio.speaker import SAMPLE_RATE, SpeakerClient

    fps: float = args.fps if args.fps is not None else 30.0

    if target is None:
        container = av.open(  # pyright: ignore[reportUnknownMemberType]
            sys.stdout.buffer, mode="w", format="matroska"
        )
    else:
        container = av.open(target, mode="w")  # pyright: ignore[reportUnknownMemberType]

    raw_v = container.add_stream("h264", rate=int(round(fps)))  # pyright: ignore[reportUnknownMemberType]
    assert isinstance(raw_v, VideoStream)
    v_stream: VideoStream = raw_v
    v_stream.pix_fmt = "yuv420p"
    v_stream.time_base = Fraction(1, 90_000)
    # codec_context.time_base must match stream.time_base, otherwise PyAV's
    # encoder interprets vf.pts in its default 1/rate (=1/fps) units while
    # the muxer rescales each packet from stream.time_base (1/90000),
    # inflating durations by 90000/fps (=3000× at 30 fps). Setting it
    # explicitly here keeps the conversion a no-op.
    v_stream.codec_context.time_base = Fraction(1, 90_000)

    raw_a = container.add_stream("aac", rate=SAMPLE_RATE)  # pyright: ignore[reportUnknownMemberType]
    assert isinstance(raw_a, AudioStream)
    a_stream: AudioStream = raw_a
    a_stream.format = "fltp"
    a_stream.layout = "stereo"
    a_stream.time_base = Fraction(1, SAMPLE_RATE)

    state = _MuxedState()
    video_header_ready = asyncio.Event()
    video_header_written = False
    audio_pts_initialised = False

    async def video_pump(cam: CameraClient) -> None:
        """Pull paced frames, encode them as H.264, share ``t0`` with audio."""
        nonlocal video_header_written
        async for frame in _paced_frames(cam, fps, verbose=args.verbose):
            if not video_header_written:
                # mp4 freezes stream metadata on the first muxed packet:
                # if an AAC packet lands while ``v_stream`` still reports
                # 0×0, the video dims are locked at 0×0 and every later
                # ``v_stream.encode(...)`` raises AVERROR_EXTERNAL. The
                # ``video_header_ready`` event below gates the audio
                # pump until these assignments have happened.
                v_stream.width = frame.width
                v_stream.height = frame.height
                state.anchor(frame.unix_nanos)
                video_header_written = True
                video_header_ready.set()
            t0 = state.anchor(frame.unix_nanos)
            pts = _video_pts_from_nanos(frame.unix_nanos, t0)
            if pts <= state.video_pts_seen:
                # Container demuxers refuse non-monotonic PTS — nudge by
                # one tick rather than dropping the frame so we keep the
                # constant-rate cadence intact.
                pts = state.video_pts_seen + 1
            state.video_pts_seen = pts
            rgb = np.ascontiguousarray(frame.pixels[..., :3])
            vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            vf.pts = pts
            _mux_video_packets(container, v_stream, vf)

    async def audio_pump(spk: SpeakerClient) -> None:
        """Pull SpeakerChunks, encode AAC, share ``t0`` with video."""
        nonlocal audio_pts_initialised
        sample_offset = 0
        # See video_pump: muxing an AAC packet before v_stream has real
        # width/height freezes the video metadata at 0×0 and breaks all
        # subsequent video encoding under mp4.
        await video_header_ready.wait()
        async for chunk in spk.stream():
            t0 = state.anchor(chunk.unix_nanos)
            if not audio_pts_initialised:
                # Convert (first_chunk_unix_nanos - t0) ns → samples at
                # 48 kHz. Clamped at zero so the very first audio chunk
                # always lands at PTS ≥ 0 even when it preceded the
                # first video frame (i.e. it *is* t0).
                delta_ns = max(0, chunk.unix_nanos - t0)
                sample_offset = (delta_ns * SAMPLE_RATE + 500_000_000) // 1_000_000_000
                audio_pts_initialised = True
            pts = sample_offset
            if pts <= state.audio_pts_seen:
                pts = state.audio_pts_seen + 1
            state.audio_pts_seen = pts
            # SpeakerChunk samples is (N, 2) interleaved L,R — transpose to
            # planar (2, N) for the "fltp" sample format.
            planar = np.ascontiguousarray(chunk.samples.T)
            af = av.AudioFrame.from_ndarray(planar, format="fltp", layout="stereo")
            af.sample_rate = SAMPLE_RATE
            af.pts = pts
            _mux_audio_packets(container, a_stream, af)
            sample_offset += chunk.samples.shape[0]

    try:
        async with (
            CameraClient(args.socket) as cam,
            SpeakerClient(args.socket) as spk,
        ):
            v_task = asyncio.create_task(video_pump(cam))
            a_task = asyncio.create_task(audio_pump(spk))
            try:
                done, pending = await asyncio.wait(
                    {v_task, a_task}, return_when=asyncio.FIRST_COMPLETED
                )
            except asyncio.CancelledError:
                # --duration timeout (or external cancel): tear down both
                # pumps deterministically before we propagate so the
                # finally block can still flush + close.
                for t in (v_task, a_task):
                    t.cancel()
                await asyncio.gather(v_task, a_task, return_exceptions=True)
                raise
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for t in done:
                exc = t.exception()
                if exc is None or isinstance(
                    exc, (BrokenPipeError, asyncio.CancelledError)
                ):
                    continue
                raise exc
    finally:
        # Teardown writes must all run regardless of which step fails, and
        # any I/O error in this phase is benign: it only happens when the
        # downstream sink has already closed (stdout pipe broken — file
        # outputs never raise here). Swallowing keeps the user's rc=0 path
        # clean instead of producing a 3-stage cascade of BrokenPipeError /
        # PyAVCallbackError tracebacks.
        if video_header_written:
            _suppress_teardown_errors(
                lambda: _mux_video_packets(container, v_stream, None)
            )
        if audio_pts_initialised:
            _suppress_teardown_errors(
                lambda: _mux_audio_packets(container, a_stream, None)
            )
        _suppress_teardown_errors(container.close)
    return 0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def _dispatch(args: argparse.Namespace, mode: Mode) -> int:
    """Pick the recording coroutine for ``(mode, args.output)`` and await it.

    The six live routes are:

    * ``("video", "-")``    → Y4M on ``sys.stdout.buffer``
    * ``("video", "*.mp4")``→ PyAV mp4 file (H.264 yuv420p)
    * ``("audio", "-")``    → raw PCM on stdout
    * ``("audio", "*.wav")``→ WAV file
    * ``("muxed", "-")``    → matroska on stdout (H.264 + AAC)
    * ``("muxed", "*.mp4")``→ mp4 file (H.264 + AAC)
    """
    if mode == "video":
        if args.output == "-":
            return await _record_video_y4m(args, sys.stdout.buffer)
        return await _record_video_mp4(args, args.output)
    if mode == "audio":
        if args.output == "-":
            return await _record_audio_pcm(args)
        return await _record_audio_wav(args, args.output)
    # muxed
    target = None if args.output == "-" else args.output
    return await _record_muxed(args, target)


async def _run(args: argparse.Namespace) -> int:
    """Entry point: validate, resolve mode, dispatch, bound by duration.

    ``BrokenPipeError`` is swallowed here (rc=0) so any write in the
    nested dispatch — header, frame payload, encoder flush — collapses
    to the same clean exit when the downstream pipe closes (``... |
    head``). ``--duration`` is enforced via ``asyncio.wait_for``; the
    resulting ``TimeoutError`` is the normal end-of-record signal, not
    an error.
    """
    rc = _validate_args(args)
    if rc is not None:
        return rc
    mode = _resolve_mode(args)

    try:
        if args.duration is None:
            return await _dispatch(args, mode)
        # wait_for's cancel unwinds the async client context managers
        # cleanly; the resulting TimeoutError is the normal end-of-record
        # signal.
        try:
            return await asyncio.wait_for(_dispatch(args, mode), timeout=args.duration)
        except TimeoutError:
            return 0
    except BrokenPipeError:
        return 0
