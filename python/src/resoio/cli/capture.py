"""``resoio capture`` subcommand: stream Camera frames as Y4M.

Heavy imports (numpy, the Camera client, the Y4M writer) are deferred to
:func:`_run` so ``resoio capture --help`` and shell completion stay fast.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import BinaryIO


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
    """Register the ``capture`` subparser on the top-level parser.

    ``common`` carries flags shared by every subcommand (e.g.
    ``-s/--socket``) and is attached via ``parents=[common]``.
    """
    parser = subparsers.add_parser(
        "capture",
        parents=[common],
        help="Stream Camera frames and emit a Y4M video to stdout or a file.",
        description=(
            "Open a Camera stream over the Resonite IO UDS and emit a Y4M "
            "(YUV4MPEG2) video. Pipe into `ffmpeg -i -` for transcoding, or "
            "use `-o FILE` to write a `.y4m` file directly."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default="-",
        help='Output file path; "-" writes to stdout (default: "-").',
    )
    parser.add_argument(
        "--fps",
        type=_fps_arg,
        default=30.0,
        help=(
            "Y4M output frame rate; faster game frames are dropped, slower "
            "ones are duplicated to keep this rate constant (default: 30.0)."
        ),
    )
    parser.add_argument(
        "--chroma",
        choices=["420", "444"],
        default="444",
        help=(
            "Chroma subsampling. 444 preserves any resolution; 420 is more "
            "compact but requires even dimensions (odd inputs are cropped)."
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
        help="Print per-frame stats to stderr.",
    )
    parser.set_defaults(func=_run)


def _open_output(path: str) -> tuple[BinaryIO, bool]:
    """Open the output sink.

    Returns ``(stream, should_close)``: stdout must not be closed by us,
    but a file we opened ourselves must be.
    """
    if path == "-":
        return sys.stdout.buffer, False
    return open(path, "wb"), True


async def _capture_loop(args: argparse.Namespace, out: BinaryIO) -> int:
    """Run the producer/consumer pacing loop.

    The producer task drains :meth:`CameraClient.stream` and rebinds
    ``latest_frame`` on every arrival (drop-oldest with a single slot). The
    consumer (this coroutine) wakes every ``1/fps`` seconds, snapshots the
    latest frame, and writes it to Y4M -- so slow game streams duplicate
    the previous frame and fast streams drop intermediate ones, keeping
    the output rate aligned with the Y4M header.
    """
    # Deferred imports: keep `resoio --help` and tab-completion snappy.
    import numpy as np
    from numpy.typing import NDArray

    from resoio.camera import CameraClient, Frame
    from resoio.cli import y4m

    fps_num, fps_den = y4m.fps_to_fraction(args.fps)
    chroma: y4m.ChromaSubsampling = args.chroma
    output_period = 1.0 / args.fps

    async with CameraClient(args.socket) as client:
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
                first_frame_arrived.set()
                raise

        producer_task = asyncio.create_task(producer())
        try:
            await first_frame_arrived.wait()
            if producer_failure is not None:
                raise producer_failure
            assert latest_frame is not None  # event-set invariant

            header_written = False
            header_w = 0
            header_h = 0
            frame_count = 0
            next_emit = time.monotonic()

            while True:
                # Snapshot the latest frame; producer may rebind concurrently.
                frame_to_emit: Frame = latest_frame
                pixels: NDArray[np.uint8] = frame_to_emit.pixels
                h, w = frame_to_emit.height, frame_to_emit.width
                if chroma == "420":
                    h2, w2 = h & ~1, w & ~1
                    if (h2, w2) != (h, w):
                        if args.verbose and not header_written:
                            print(
                                f"frame {frame_to_emit.frame_id} cropped: "
                                f"{w}x{h} -> {w2}x{h2}",
                                file=sys.stderr,
                            )
                        pixels = pixels[:h2, :w2, :]
                        h, w = h2, w2
                if not header_written:
                    y4m.write_header(out, w, h, fps_num, fps_den, chroma)
                    header_written = True
                    header_w, header_h = w, h
                elif (w, h) != (header_w, header_h):
                    # Mid-stream resolution change: Y4M header is fixed, so
                    # abort cleanly instead of writing mismatched frames.
                    if args.verbose:
                        print(
                            f"frame {frame_to_emit.frame_id} resolution "
                            f"changed: {header_w}x{header_h} -> {w}x{h}; "
                            "stopping capture",
                            file=sys.stderr,
                        )
                    return 0
                try:
                    y4m.write_frame(out, pixels, chroma)
                    out.flush()
                except BrokenPipeError:
                    # Downstream closed stdout (e.g. `resoio capture | head`).
                    # That is a clean exit, not a failure.
                    return 0
                frame_count += 1
                if args.verbose:
                    print(
                        f"frame {frame_to_emit.frame_id} {w}x{h} "
                        f"unix_nanos={frame_to_emit.unix_nanos} "
                        f"total={frame_count}",
                        file=sys.stderr,
                    )

                # Pace to the requested output fps. Skipping the producer
                # check before sleeping lets us emit one final duplicate if
                # the producer ended right after the most recent frame.
                next_emit += output_period
                sleep_for = next_emit - time.monotonic()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    # We are behind schedule (e.g. heavy frame conversion).
                    # Re-anchor to "now" so a long stall does not produce a
                    # burst of catch-up frames once it recovers.
                    next_emit = time.monotonic()

                if producer_task.done():
                    exc = producer_task.exception()
                    if exc is not None:
                        raise exc
                    # Stream ended naturally -- stop after the last frame
                    # has been emitted above. Avoids spinning forever on a
                    # closed source.
                    return 0
        finally:
            producer_task.cancel()
            try:
                await producer_task
            except (asyncio.CancelledError, Exception):
                # Cancellation is the expected outcome here, and any
                # producer failure has either been re-raised above or is
                # already being unwound by the consumer.
                pass


async def _run(args: argparse.Namespace) -> int:
    out, should_close = _open_output(args.output)
    try:
        if args.duration is None:
            return await _capture_loop(args, out)
        # wait_for cancels the coroutine on timeout, which unwinds the
        # `async with CameraClient(...)` inside _capture_loop and closes
        # the gRPC channel cleanly. Treat the resulting TimeoutError as
        # a normal end-of-capture, not an error.
        try:
            return await asyncio.wait_for(
                _capture_loop(args, out), timeout=args.duration
            )
        except TimeoutError:
            return 0
    except BrokenPipeError:
        return 0
    finally:
        try:
            out.flush()
        except BrokenPipeError:
            pass
        if should_close:
            out.close()
