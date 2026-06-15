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

Output target:

* ``-o -``            → Y4M / raw float32 PCM / matroska on
  ``sys.stdout.buffer`` per mode (pipeable).
* ``-o path``         → that file (``.mp4`` for video / muxed, ``.wav``
  for audio-only).
* (omitted)           → ``record_YYYYMMDD_HHMMSS.<ext>`` in the current
  directory, ``.wav`` for ``--audio`` and ``.mp4`` for video / muxed.

On a file save (default or explicit ``-o path``) the saved absolute path
is printed once on stdout after the recording stops; the ``-o -`` route
prints no path line.

This module owns the argparse surface, arg validation, frame pacing,
and the per-route orchestration that wires the gRPC clients to the
media-encoding primitives. Those primitives (Y4M / WAV writers, PyAV
muxing, the muxed-timing state) live in :mod:`resoio.cli._recording_io`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import AsyncIterator
from datetime import datetime
from fractions import Fraction
from typing import TYPE_CHECKING, BinaryIO, Literal

import numpy as np

# suppress_teardown_errors is aliased back to its old module-private name
# because tests/resoio/cli/test_record.py imports it via
# ``from resoio.cli.record import _suppress_teardown_errors``.
from resoio.cli._recording_io import (
    MuxedState,
    WavFloat32Writer,
    fps_to_fraction,
    mux_audio_packets,
    mux_video_packets,
    suppress_teardown_errors as _suppress_teardown_errors,
    video_pts_from_nanos,
    y4m_write_frame,
    y4m_write_header,
)

if TYPE_CHECKING:
    from av.audio.stream import AudioStream
    from av.video.stream import VideoStream

    from resoio.camera import CameraClient, Frame


# ``_suppress_teardown_errors`` is re-exported (aliased above) so tests can
# import it via ``from resoio.cli.record import _suppress_teardown_errors``;
# listing it in ``__all__`` marks that re-export as intentional for pyright.
__all__ = ["register", "_suppress_teardown_errors"]


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
            "muxed video+audio. With no -o the recording is saved to the "
            "current directory as record_YYYYMMDD_HHMMSS.mp4 (.wav for "
            "--audio); -o - emits Y4M / raw PCM / matroska to stdout per "
            "mode; otherwise -o must end in .mp4 (video/muxed) or .wav "
            "(audio)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            'Output target; "-" emits Y4M / raw float32 PCM / matroska '
            "to stdout per mode, a path ending in .mp4 / .wav writes that "
            "file. Omitted: record_YYYYMMDD_HHMMSS.mp4 (.wav for --audio) "
            "in the current directory."
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


def _default_filename(mode: Mode) -> str:
    """``record_YYYYMMDD_HHMMSS.<ext>`` stamped with the local time.

    The extension follows the mode: ``.wav`` for audio-only, ``.mp4``
    for video-only and muxed (the two container formats the file routes
    write).
    """
    ext = "wav" if mode == "audio" else "mp4"
    return f"record_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"


def _validate_args(args: argparse.Namespace) -> int | None:
    """Validate flag/extension consistency.

    Returns ``None`` on success, or ``2`` after writing a one-line
    error to ``stderr``. The two checks run in this order so the
    user's *flag* mistake is surfaced before the *path* mistake:

    1. ``--fps`` / ``-v`` while ``mode == "audio"`` → reject.
    2. Output path (when not ``"-"``) extension mismatch per mode.

    A ``None`` target (the omitted default → date file) is always
    valid; only an explicit file path is extension-checked.
    """
    mode = _resolve_mode(args)
    if mode == "audio" and (args.fps is not None or args.verbose):
        print(
            "resoio record: --fps/-v require video; remove --audio or add --video",
            file=sys.stderr,
        )
        return 2

    target: str | None = args.output
    if target is None or target == "-":
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
    fps_num, fps_den = fps_to_fraction(fps)
    header_written = False

    async with CameraClient(args.socket) as client:
        async for frame in _paced_frames(client, fps, verbose=args.verbose):
            if not header_written:
                y4m_write_header(out, frame.width, frame.height, fps_num, fps_den)
                header_written = True
            y4m_write_frame(out, frame.pixels)
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
                mux_video_packets(container, v_stream, vf)
    finally:
        try:
            # Flush the encoder's reorder buffer before close() finalises
            # the moov atom; skipped if no frame ever arrived (header
            # never written → stream dims unset → encode would raise).
            if header_written:
                mux_video_packets(container, v_stream, None)
        finally:
            container.close()
    return 0


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

    writer = WavFloat32Writer()
    writer.open(path)
    try:
        async with SpeakerClient(args.socket) as client:
            async for chunk in client.stream():
                writer.write(chunk)
    finally:
        writer.close()
    return 0


async def _record_muxed(args: argparse.Namespace, target: str | None) -> int:
    """Stream Camera+Speaker into a muxed mp4 file or matroska stdout.

    ``target`` selects the container:

    * ``target is None`` → matroska on ``sys.stdout.buffer`` (so the
      output can be piped into ``ffmpeg`` or ``ffplay`` live).
    * ``target is not None`` → mp4 file at that path.

    Both pumps share a single :class:`MuxedState` anchor for ``t0``
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

    state = MuxedState()
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
            pts = video_pts_from_nanos(frame.unix_nanos, t0)
            if pts <= state.video_pts_seen:
                # Container demuxers refuse non-monotonic PTS — nudge by
                # one tick rather than dropping the frame so we keep the
                # constant-rate cadence intact.
                pts = state.video_pts_seen + 1
            state.video_pts_seen = pts
            rgb = np.ascontiguousarray(frame.pixels[..., :3])
            vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            vf.pts = pts
            mux_video_packets(container, v_stream, vf)

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
            mux_audio_packets(container, a_stream, af)
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
                lambda: mux_video_packets(container, v_stream, None)
            )
        if audio_pts_initialised:
            _suppress_teardown_errors(
                lambda: mux_audio_packets(container, a_stream, None)
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

    # Resolve the omitted default (None) into a date-stamped file in the
    # current directory so the file routes treat it like an explicit
    # path; "-" (stdout) and explicit paths pass through unchanged.
    if args.output is None:
        args.output = _default_filename(mode)
    file_path: str | None = args.output if args.output != "-" else None

    try:
        if args.duration is None:
            rc = await _dispatch(args, mode)
        else:
            # wait_for's cancel unwinds the async client context managers
            # cleanly; the resulting TimeoutError is the normal
            # end-of-record signal.
            try:
                rc = await asyncio.wait_for(
                    _dispatch(args, mode), timeout=args.duration
                )
            except TimeoutError:
                rc = 0
    except BrokenPipeError:
        return 0

    # The recording has stopped and the file is fully written; emit the
    # saved absolute path once. The "-" (stdout binary) route prints no
    # path line.
    if file_path is not None:
        print(os.path.abspath(file_path))
    return rc
