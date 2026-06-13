"""``resoio screenshot`` subcommand: save one Camera frame as a PNG.

A one-shot counterpart to ``record``: it pulls a single frame from the
Camera stream (:meth:`resoio.camera.CameraClient.shot`), encodes it as a
PNG, and writes it to a file or stdout. Unlike ``record`` the alpha
channel is preserved — PNG is lossless RGBA so the saved image matches
the engine framebuffer exactly.

Output target:

* ``-o -``            → PNG bytes on ``sys.stdout.buffer`` (pipeable).
* ``-o path.png``     → that file (must end in ``.png``).
* (omitted)           → ``screenshot_YYYYMMDD_HHMMSS.png`` in the current
  directory, stamped with the local wall-clock time so repeated shots do
  not clobber each other.

PNG encoding reuses the already-present PyAV dependency (ffmpeg's ``png``
encoder takes ``rgba`` directly), so no image library is added for this
one command.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``screenshot`` subparser on the top-level parser."""
    parser = subparsers.add_parser(
        "screenshot",
        parents=[common],
        help="Save a single Camera frame as a PNG to a file or stdout.",
        description=(
            "Capture one frame from the Camera stream over the Resonite "
            "IO UDS and write it as a lossless RGBA PNG. With no -o the "
            "image is saved to the current directory as "
            "screenshot_YYYYMMDD_HHMMSS.png; -o - emits PNG bytes to "
            "stdout; otherwise -o must end in .png."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            'Output target; "-" emits PNG bytes to stdout, a path ending '
            "in .png writes that file. Omitted: "
            "screenshot_YYYYMMDD_HHMMSS.png in the current directory."
        ),
    )
    parser.set_defaults(func=_run)


def _validate_args(args: argparse.Namespace) -> int | None:
    """Reject a non-PNG output path.

    Returns ``None`` on success, or ``2`` after writing a one-line error
    to ``stderr``. ``-o -`` (stdout) and the omitted default are always
    valid; only an explicit file path is extension-checked.
    """
    target: str | None = args.output
    if target is None or target == "-":
        return None
    if not target.lower().endswith(".png"):
        print(
            f"resoio screenshot: unsupported output extension: {target!r}. "
            "Use '-' (stdout) or a path ending in '.png'.",
            file=sys.stderr,
        )
        return 2
    return None


# ---------------------------------------------------------------------------
# PNG encoding
# ---------------------------------------------------------------------------


def _encode_png(pixels: NDArray[np.uint8]) -> bytes:
    """Encode an ``(H, W, 4)`` RGBA8 array as a complete PNG byte string.

    Uses ffmpeg's ``png`` encoder via PyAV (already a dependency); the
    encoder emits one self-contained PNG per flushed packet, so the
    encode + flush pair below yields the full file.
    """
    import av
    import numpy as np
    from av.codec import CodecContext
    from av.video.codeccontext import VideoCodecContext

    height = int(pixels.shape[0])
    width = int(pixels.shape[1])
    codec = CodecContext.create("png", "w")
    assert isinstance(codec, VideoCodecContext)
    codec.width = width
    codec.height = height
    codec.pix_fmt = "rgba"
    frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(pixels), format="rgba")
    # The png encoder emits one self-contained PNG per packet; encode the
    # frame then flush (encode(None)). The pyright: ignore is confined here
    # because PyAV's stubs type encode() as list[Packet[Unknown]] (mirrors
    # the mux_*_packets helpers in _recording_io).
    chunks: list[bytes] = []
    for packet in [*codec.encode(frame), *codec.encode(None)]:  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        chunks.append(bytes(packet))  # pyright: ignore[reportUnknownArgumentType]
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _default_filename() -> str:
    """``screenshot_YYYYMMDD_HHMMSS.png`` stamped with the local time."""
    return f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"


async def _run(args: argparse.Namespace) -> int:
    """Capture one frame, encode it as PNG, and write it to the target.

    ``BrokenPipeError`` is swallowed (rc=0) so ``... | head -c N`` style
    pipelines closing stdout early are a clean exit rather than a
    traceback.
    """
    rc = _validate_args(args)
    if rc is not None:
        return rc

    from resoio.camera import CameraClient

    async with CameraClient(args.socket) as client:
        frame = await client.shot()
    png = _encode_png(frame.pixels)

    target: str | None = args.output
    try:
        if target == "-":
            sys.stdout.buffer.write(png)
            sys.stdout.buffer.flush()
        else:
            path = target if target is not None else _default_filename()
            with open(path, "wb") as fh:
                fh.write(png)
    except BrokenPipeError:
        return 0
    return 0
