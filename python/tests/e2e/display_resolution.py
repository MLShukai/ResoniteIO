"""E2E: verify ``DisplayClient.apply()`` actually retargets the renderer.

Polls ``CameraClient.stream()`` after ``apply`` and asserts the streamed
frame dimensions match — the only ground-truth that
``FrooxEngineDisplayBridge`` → ``ResolutionSettings.ApplyResolution()``
propagates through to the Renderer (not just into the engine snapshot).

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
from grpclib.const import Status

from resoio.camera import CameraClient, Frame
from resoio.display import DisplayClient, DisplayInfo
from tests.helpers import mark_e2e

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# Aspect ratios are intentionally different so a width-only or height-only
# regression cannot pass by accident. Both clear ResolutionSettings'
# IsResolutionValid() floor of 800x600 with aspect >= 1.0.
_TARGET_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (1024, 768),
    (1280, 720),
)

# How long to wait for a streamed frame whose dimensions match the new
# target. Renderer resize is not instantaneous; a few seconds is typical
# but the cap is generous for heavier worlds.
_FRAME_MATCH_TIMEOUT_S = 15.0

# UDS bind and LocalUser/FocusedWorld readiness race: while the engine is
# still booting, Camera bridge returns FAILED_PRECONDITION. Mirrors
# ``camera_stream.py``; intentionally copy-pasted (one duplication is below
# the bar for shared helper extraction — see commit message).
_CAMERA_READY_TIMEOUT_S = 120.0
_CAMERA_READY_RETRY_INTERVAL_S = 2.0

# Display bridge readiness lags Camera readiness: ``ResolutionSettings`` /
# ``DesktopRenderSettings`` activate slightly later than LocalUser /
# FocusedWorld. The conftest now stops Resonite before every test, so the
# engine is always cold and this race surfaces deterministically.
_DISPLAY_READY_TIMEOUT_S = 30.0
_DISPLAY_READY_RETRY_INTERVAL_S = 1.0


async def _wait_for_camera_ready() -> None:
    """Block until the Camera bridge accepts a stream (engine fully booted).

    Intentional copy of ``camera_stream.py``'s wait — two call sites is
    below the bar for shared-helper extraction.
    """
    ready_deadline = time.monotonic() + _CAMERA_READY_TIMEOUT_S
    while True:
        try:
            async with CameraClient() as cam:
                async for _ in cam.stream(width=1, height=1, fps_limit=1.0):
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


async def _wait_for_display_ready() -> None:
    """Block until ``Display.Get`` stops returning FAILED_PRECONDITION.

    ``FrooxEngineDisplayBridge`` reports FAILED_PRECONDITION until both
    ``ResolutionSettings`` and ``DesktopRenderSettings`` are active. This
    can lag Camera readiness by a few seconds on a freshly booted engine.
    """
    ready_deadline = time.monotonic() + _DISPLAY_READY_TIMEOUT_S
    while True:
        try:
            async with DisplayClient() as c:
                await c.get()
                return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > ready_deadline:
                raise TimeoutError(
                    f"Display bridge did not become ready in "
                    f"{_DISPLAY_READY_TIMEOUT_S:.0f}s "
                    f"(last reason: {e.message})"
                ) from e
            await asyncio.sleep(_DISPLAY_READY_RETRY_INTERVAL_S)


async def _get_current_display() -> DisplayInfo:
    async with DisplayClient() as c:
        return await c.get()


async def _apply_resolution(width: int, height: int) -> DisplayInfo:
    """Apply ``width``/``height`` and assert the engine snapshot reflects them.

    A mismatch here means the Apply path is broken at the engine level,
    before any Renderer propagation could be involved.
    """
    async with DisplayClient() as c:
        info = await c.apply(width=width, height=height)
    assert (info.width, info.height) == (width, height), (
        f"apply({width}x{height}) returned snapshot {info.width}x{info.height}; "
        f"FrooxEngineDisplayBridge.ApplyResolution() path may be broken."
    )
    return info


async def _poll_frame_with_dimensions(
    target_w: int, target_h: int, timeout_s: float
) -> Frame:
    """Stream frames until one matches ``target_w x target_h`` or deadline."""
    deadline = time.monotonic() + timeout_s
    last_size: tuple[int, int] | None = None
    async with CameraClient() as cam:
        async for frame in cam.stream():
            last_size = (frame.width, frame.height)
            if last_size == (target_w, target_h):
                return frame
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Frame did not reach {target_w}x{target_h} within "
                    f"{timeout_s:.1f}s (last seen: {last_size})"
                )
    raise RuntimeError(
        f"Camera stream ended before reaching {target_w}x{target_h} "
        f"(last seen: {last_size})"
    )


class TestDisplayResolution:
    @mark_e2e
    def test_apply_changes_frame_dimensions(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"display_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        async def run() -> None:
            await _wait_for_camera_ready()
            await _wait_for_display_ready()
            initial = await _get_current_display()
            try:
                for target_w, target_h in _TARGET_RESOLUTIONS:
                    await _apply_resolution(target_w, target_h)
                    frame = await _poll_frame_with_dimensions(
                        target_w, target_h, timeout_s=_FRAME_MATCH_TIMEOUT_S
                    )
                    bgr = cv2.cvtColor(frame.pixels, cv2.COLOR_RGBA2BGR)
                    cv2.imwrite(str(out_dir / f"{target_w}x{target_h}.png"), bgr)
            finally:
                # Restore so sibling e2e files (camera_stream.py) read frames
                # at the engine default and are not perturbed by this run.
                await _apply_resolution(initial.width, initial.height)

        asyncio.run(run())

        print(f"E2E artifact dir: {out_dir}")
