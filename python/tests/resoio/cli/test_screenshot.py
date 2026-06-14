"""Tests for the ``resoio screenshot`` subcommand.

The CLI is exercised end-to-end over a real grpclib UDS server (the
``uds_server`` fixture) with an in-process fake Camera, and the emitted
bytes are decoded back through Pillow — a real PNG codec round-trip
rather than a byte-pattern assertion.
"""

from __future__ import annotations

import io
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from resoio._generated.resonite_io.v1 import (
    CameraBase,
    CameraFrame,
    CameraFrameFormat,
    CameraStreamRequest,
)
from resoio.cli import _amain, _build_parser

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

# Non-square so a width/height swap cannot pass by coincidence, and a
# distinct value per channel so RGB channel order is verified on decode.
# Alpha is deliberately non-opaque (40) so the tests prove screenshot
# drops it and saves an opaque RGB PNG.
_FRAME_W = 4
_FRAME_H = 2
_PIXEL = (10, 20, 30, 40)
_FRAME_COUNT = 3


class _FixedCamera(CameraBase):
    """Fake that yields ``_FRAME_COUNT`` frames of a known RGBA value.

    More than one frame so a test can prove ``screenshot`` takes a single
    shot (frame 0) rather than draining the stream; finite so the stream
    terminates cleanly when the client closes after the first frame.
    """

    async def stream_frames(
        self, message: CameraStreamRequest
    ) -> AsyncIterator[CameraFrame]:
        pixels = bytes(_PIXEL) * (_FRAME_W * _FRAME_H)
        for i in range(_FRAME_COUNT):
            yield CameraFrame(
                width=_FRAME_W,
                height=_FRAME_H,
                format=CameraFrameFormat.RGBA8,
                unix_nanos=time.time_ns(),
                frame_id=i,
                pixels=pixels,
            )


def _decode_rgb(data: bytes) -> np.ndarray:
    """Decode PNG bytes to an ``(H, W, 3)`` array, asserting it is opaque.

    ``mode == "RGB"`` (not ``"RGBA"``) is the precise pin for the
    alpha-drop fix: the saved PNG has no alpha channel at all.
    """
    with Image.open(io.BytesIO(data)) as img:
        assert img.mode == "RGB", f"expected opaque RGB PNG, got mode {img.mode!r}"
        return np.asarray(img)


def _png_magic() -> bytes:
    return b"\x89PNG\r\n\x1a\n"


class TestScreenshotCli:
    async def test_writes_png_file(
        self,
        tmp_path: Path,
        uds_server: UdsServer,
        capsys: pytest.CaptureFixture[str],
    ):
        await uds_server(_FixedCamera())
        out_path = tmp_path / "shot.png"
        args = _build_parser().parse_args(["screenshot", "-o", str(out_path)])
        rc = await _amain(args)
        assert rc == 0

        data = out_path.read_bytes()
        assert data.startswith(_png_magic())
        decoded = _decode_rgb(data)
        assert decoded.shape == (_FRAME_H, _FRAME_W, 3)
        # PNG is lossless: the round-tripped RGB matches the source exactly
        # (proves channel order and dimensions are preserved). The source
        # alpha (40) is dropped — _decode_rgb already pinned mode == "RGB".
        assert tuple(int(c) for c in decoded[0, 0]) == _PIXEL[:3]

        # After saving an explicit -o path, the absolute path is printed as
        # exactly one stdout line so a caller can read back where the file
        # landed without re-deriving the name.
        out_lines = capsys.readouterr().out.splitlines()
        assert out_lines == [os.path.abspath(str(out_path))]

    async def test_writes_png_to_stdout(
        self,
        uds_server: UdsServer,
        capsysbinary: pytest.CaptureFixture[bytes],
    ):
        await uds_server(_FixedCamera())
        args = _build_parser().parse_args(["screenshot", "-o", "-"])
        rc = await _amain(args)
        assert rc == 0

        # stdout carries the raw PNG only — no trailing path line that would
        # corrupt the binary stream a downstream consumer is reading.
        data = capsysbinary.readouterr().out
        assert data.startswith(_png_magic())
        decoded = _decode_rgb(data)
        assert decoded.shape == (_FRAME_H, _FRAME_W, 3)

    async def test_stdout_target_prints_no_path_line(
        self,
        uds_server: UdsServer,
        capsysbinary: pytest.CaptureFixture[bytes],
    ):
        """``-o -`` emits the PNG only — no abs-path line on the byte stream.

        The abs-path report is reserved for the file-saving branches; on
        the stdout target it must be absent so a downstream consumer reading
        the binary pipe never sees a stray path glued onto the PNG. Pinned
        by the absence of the ``screenshot_`` filename token (the only path
        text the command could emit) in the captured bytes.
        """
        await uds_server(_FixedCamera())
        args = _build_parser().parse_args(["screenshot", "-o", "-"])
        rc = await _amain(args)
        assert rc == 0

        data = capsysbinary.readouterr().out
        assert data.startswith(_png_magic())
        assert b"screenshot_" not in data

    async def test_default_filename_in_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uds_server: UdsServer,
        capsys: pytest.CaptureFixture[str],
    ):
        await uds_server(_FixedCamera())
        monkeypatch.chdir(tmp_path)
        args = _build_parser().parse_args(["screenshot"])
        rc = await _amain(args)
        assert rc == 0

        produced = list(tmp_path.glob("*.png"))
        assert len(produced) == 1
        assert re.fullmatch(r"screenshot_\d{8}_\d{6}\.png", produced[0].name)
        assert produced[0].read_bytes().startswith(_png_magic())

        # The date-stamped default save also reports its absolute path as
        # exactly one stdout line, resolved against the (chdir'd) CWD so the
        # caller learns the generated filename it never specified.
        out_lines = capsys.readouterr().out.splitlines()
        assert out_lines == [os.path.abspath(str(produced[0]))]

    async def test_rejects_non_png_extension(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # Extension is validated before any connection, so no server is
        # needed; the command must fail fast with rc=2.
        out_path = tmp_path / "shot.jpg"
        args = _build_parser().parse_args(["screenshot", "-o", str(out_path)])
        rc = await _amain(args)
        assert rc == 2
        assert "unsupported output extension" in capsys.readouterr().err
        assert not out_path.exists()

    def test_subcommand_is_registered(self):
        args = _build_parser().parse_args(["screenshot", "-o", "-"])
        assert args.command == "screenshot"
        assert args.output == "-"
