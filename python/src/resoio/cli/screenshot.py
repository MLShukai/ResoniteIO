"""``resoio screenshot`` subcommand: save one Camera frame as a PNG.

A one-shot counterpart to ``record``: it pulls a single frame from the
Camera stream (:meth:`resoio.camera.CameraClient.shot`), encodes it as a
PNG, and writes it to a file or stdout. The alpha channel is dropped so
the screenshot is opaque — the engine framebuffer's alpha is not 255
everywhere, and preserving it renders as a washed-out image when a viewer
composites it over a background (same reason ``record`` drops alpha).

Output target:

* ``-o -``            → PNG bytes on ``sys.stdout.buffer`` (pipeable).
* ``-o path.png``     → that file (must end in ``.png``).
* (omitted)           → ``screenshot_YYYYMMDD_HHMMSS.png`` in the current
  directory, stamped with the local wall-clock time so repeated shots do
  not clobber each other.

On a file save (default or explicit ``-o path``) the saved absolute path
is printed on stdout as a single line so a caller can pick it up without
guessing the timestamp; the ``-o -`` route prints no path line.
"""

from __future__ import annotations

import argparse
import os
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
    """Encode an ``(H, W, 4)`` RGBA8 array as an opaque RGB PNG.

    The alpha channel is dropped before encoding: the engine framebuffer
    carries a non-opaque alpha (a large fraction of pixels < 255), which
    a viewer composites over its background into a washed-out image. A
    screenshot must be opaque, so only the RGB channels are saved (the
    record mp4 path drops alpha for the same reason).
    """
    import io

    import numpy as np
    from PIL import Image

    rgb = np.ascontiguousarray(pixels[..., :3])
    buffer = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


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
            print(os.path.abspath(path))
    except BrokenPipeError:
        return 0
    return 0
