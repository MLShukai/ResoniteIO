"""Tests for the ``resoio screenshot`` subcommand.

The CLI is exercised end-to-end over a real grpclib UDS server (the
``uds_server`` fixture) with an in-process fake Camera, and the emitted
bytes are decoded back through PyAV — a real PNG codec round-trip rather
than a byte-pattern assertion.
"""

from __future__ import annotations

import io
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import av
import numpy as np
import pytest

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
# distinct value per channel so RGBA channel order is verified on decode.
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


def _decode_png(data: bytes) -> np.ndarray:
    """Decode PNG bytes back to an ``(H, W, 4)`` RGBA8 array via PyAV."""
    with av.open(io.BytesIO(data)) as container:
        frame = next(container.decode(video=0))
        return frame.to_ndarray(format="rgba")


def _png_magic() -> bytes:
    return b"\x89PNG\r\n\x1a\n"


class TestScreenshotCli:
    async def test_writes_png_file(self, tmp_path: Path, uds_server: UdsServer):
        await uds_server(_FixedCamera())
        out_path = tmp_path / "shot.png"
        args = _build_parser().parse_args(["screenshot", "-o", str(out_path)])
        rc = await _amain(args)
        assert rc == 0

        data = out_path.read_bytes()
        assert data.startswith(_png_magic())
        decoded = _decode_png(data)
        assert decoded.shape == (_FRAME_H, _FRAME_W, 4)
        # PNG is lossless: the round-tripped pixel matches the source RGBA
        # exactly (proves channel order and dimensions are preserved).
        assert tuple(int(c) for c in decoded[0, 0]) == _PIXEL

    async def test_writes_png_to_stdout(
        self,
        uds_server: UdsServer,
        capsysbinary: pytest.CaptureFixture[bytes],
    ):
        await uds_server(_FixedCamera())
        args = _build_parser().parse_args(["screenshot", "-o", "-"])
        rc = await _amain(args)
        assert rc == 0

        data = capsysbinary.readouterr().out
        assert data.startswith(_png_magic())
        decoded = _decode_png(data)
        assert decoded.shape == (_FRAME_H, _FRAME_W, 4)

    async def test_default_filename_in_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uds_server: UdsServer,
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
