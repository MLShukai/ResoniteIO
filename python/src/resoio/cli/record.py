"""``resoio record`` subcommand: stream Speaker audio as WAV or raw PCM.

Mirrors :mod:`resoio.cli.capture` (camera) as a flat command. The output
path's extension selects the encoder:

* ``"-"`` writes raw float32 LE PCM (interleaved L,R) to stdout, suitable
  for ``ffmpeg -f f32le -ar 48000 -ac 2 -i -``.
* ``"*.wav"`` writes a RIFF / WAVE / fmt / data file with header sizes
  patched back in on close (no other extensions are accepted).

The wire format is fixed at 48 kHz / Stereo / float32 LE
(see :mod:`resoio.speaker`); the WAV header reflects that directly.
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from resoio.speaker import AudioChunk


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

    def write(self, chunk: AudioChunk) -> None:
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


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``record`` subparser on the top-level parser.

    The flat-command shape (``resoio record`` instead of e.g.
    ``resoio speaker record``) mirrors :mod:`resoio.cli.capture` and
    leaves room for future input-side commands (``resoio voice``) on
    the same axis without rearranging the published surface.
    """
    parser = subparsers.add_parser(
        "record",
        parents=[common],
        help="Stream Speaker audio and emit a WAV file or raw float32 PCM.",
        description=(
            "Open a Speaker stream over the Resonite IO UDS and emit one of: "
            "(a) a WAV file (48 kHz / Stereo / float32 LE) when -o ends in "
            '".wav", or (b) raw float32 LE PCM to stdout when -o is "-" '
            "(pipe into `ffmpeg -f f32le -ar 48000 -ac 2 -i -`)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help='Output path; "-" writes raw float32 LE PCM to stdout, "*.wav" '
        "writes a WAV file. Other extensions are rejected.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop after this many seconds (default: run until Ctrl-C).",
    )
    parser.set_defaults(func=_run)


async def _record_to_stdout(args: argparse.Namespace) -> int:
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


async def _record_to_wav(args: argparse.Namespace) -> int:
    """Stream samples into a ``.wav`` file, patching sizes on close."""
    from resoio.speaker import SpeakerClient

    writer = _WavFloat32Writer()
    writer.open(args.output)
    try:
        async with SpeakerClient(args.socket) as client:
            async for chunk in client.stream():
                writer.write(chunk)
    finally:
        writer.close()
    return 0


async def _run(args: argparse.Namespace) -> int:
    """Dispatch on output target and apply the optional duration timeout.

    Extension validation runs here (not via ``parser.error``) so that
    callers driving the CLI through :func:`resoio.cli._amain` — including
    the test suite — observe the failure as a non-zero return code
    rather than ``SystemExit(2)``. The console-script entry point also
    returns this code, so the user-visible behaviour is identical.
    """
    target: str = args.output
    if target != "-" and not target.endswith(".wav"):
        print(
            f"resoio record: unsupported output extension: {target!r}. "
            "Use '-' for raw PCM stdout, or a path ending in '.wav' for "
            "a WAV file.",
            file=sys.stderr,
        )
        return 2

    loop = _record_to_stdout if target == "-" else _record_to_wav

    try:
        if args.duration is None:
            return await loop(args)
        # wait_for cancels the streaming task which unwinds the
        # SpeakerClient async context manager cleanly; the WAV writer's
        # `finally` then patches header sizes.
        try:
            return await asyncio.wait_for(loop(args), timeout=args.duration)
        except TimeoutError:
            return 0
    except BrokenPipeError:
        return 0
