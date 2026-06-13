"""E2E: stream Camera frames from a live Resonite and record to MP4.

The first and last frame are also dumped as PNG so the artifact can be
sanity-checked without a video player.

MP4 / H.264 は alpha 非対応のため ``cv2.cvtColor(RGBA2BGR)`` で alpha を落として
3-channel BGR で書く (visual verification 目的なので alpha drop で十分。alpha
込みで保存したい場合は MOV + PNG codec や個別 PNG dump が必要)。

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

import cv2
import grpclib
import numpy as np
from grpclib.const import Status
from numpy.typing import NDArray

from resoio.camera import CameraClient
from tests.helpers import mark_e2e

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# 公称 10 s × 30 fps = 300 frames。重 world で fps を割る可能性を見込み下限を
# 実効 20fps 相当 (200 frames) に緩める。解像度は Display modality 側が決める
# (cam.stream() は size 引数を取らない) ため、VideoWriter は最初の frame の
# 実寸から遅延生成する。
_CAPTURE_FPS = 30.0
_CAPTURE_SECONDS = 10.0
_MIN_FRAMES = 200

# UDS bind と LocalUser/FocusedWorld 準備の間に gap があり、その間 Camera Bridge
# は FAILED_PRECONDITION を返す。client retry で吸収する契約 (ICameraBridge
# docstring 参照)。
_CAMERA_READY_TIMEOUT_S = 120.0
_CAMERA_READY_RETRY_INTERVAL_S = 2.0


class TestCameraStream:
    @mark_e2e
    def test_capture_to_mp4(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"camera_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "capture.mp4"
        first_png = out_dir / "frame_0000.png"
        last_png = out_dir / "frame_last.png"

        # The capture resolution is now engine-owned (Display modality);
        # cam.stream() carries no size, so the writer is opened lazily from
        # the first frame's actual dimensions. ``mp4v`` is the codec most
        # broadly available in pip-shipped headless opencv. If unavailable the
        # writer silently fails open and ``out_path`` stays zero-bytes
        # (asserted below).
        fourcc = cv2.VideoWriter.fourcc(*"mp4v")
        writer: cv2.VideoWriter | None = None

        async def wait_for_camera_ready() -> None:
            ready_deadline = time.monotonic() + _CAMERA_READY_TIMEOUT_S
            while True:
                try:
                    async with CameraClient() as cam:
                        await cam.shot()
                        return
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() > ready_deadline:
                        raise TimeoutError(
                            f"Camera bridge did not become ready in "
                            f"{_CAMERA_READY_TIMEOUT_S:.0f}s "
                            f"(last reason: {e.message})"
                        ) from e
                    await asyncio.sleep(_CAMERA_READY_RETRY_INTERVAL_S)

        async def capture() -> int:
            nonlocal writer
            await wait_for_camera_ready()
            count = 0
            last_bgr: NDArray[np.uint8] | None = None
            deadline = time.monotonic() + _CAPTURE_SECONDS
            async with CameraClient() as cam:
                async for frame in cam.stream():
                    # cvtColor copies into a fresh writable BGR buffer that
                    # VideoWriter / imwrite accept.
                    bgr = cv2.cvtColor(frame.pixels, cv2.COLOR_RGBA2BGR)
                    if writer is None:
                        # Frame dimensions are engine-owned; size the writer
                        # from the first frame so every frame is accepted.
                        writer = cv2.VideoWriter(
                            str(out_path),
                            fourcc,
                            _CAPTURE_FPS,
                            (frame.width, frame.height),
                        )
                    writer.write(bgr)
                    if count == 0:
                        cv2.imwrite(str(first_png), bgr)
                    last_bgr = bgr
                    count += 1
                    if time.monotonic() >= deadline:
                        break
            if last_bgr is not None:
                cv2.imwrite(str(last_png), last_bgr)
            return count

        try:
            n = asyncio.run(capture())
        finally:
            if writer is not None:
                writer.release()

        # Surface the artifact path even on green CI runs.
        print(f"E2E artifact dir: {out_dir}")
        print(f"E2E MP4: {out_path}")

        assert out_path.exists(), f"MP4 not created at {out_path}"
        assert out_path.stat().st_size > 0, (
            f"MP4 at {out_path} is empty (codec missing?)"
        )
        assert n >= _MIN_FRAMES, (
            f"expected >= {_MIN_FRAMES} frames in "
            f"{_CAPTURE_SECONDS:.0f}s @ {_CAPTURE_FPS} fps, got {n}"
        )
