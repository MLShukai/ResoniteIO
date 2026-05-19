"""E2E: drive Locomotion + record Camera to MP4 in a single asyncio run.

The 18 s scenario walks the desktop control set in 8 phases (forward,
fast forward via velocity=2.0, right strafe, idle, right yaw, look up,
jump, crouch, cool-down) so the resulting MP4 is a single visual proof
that every ``LocomotionCommand`` field reaches the engine. Camera frames
are streamed in parallel at 30 fps so the recording is synchronised with
the command timeline.

``LocomotionCommand.ExternalInput`` is consumed and nulled by the engine
every update tick (see ``Analog3DAction.Evaluate``), so the scenario
sends at 30 Hz to keep inputs held. ``FAILED_PRECONDITION`` from either
bridge is retried up to 120 s — both depend on ``LocalUser`` /
``FocusedWorld`` readiness which lags UDS bind. The Locomotion bridge
additionally requires a walk-capable world (home / Userspace use
NoLocomotion modules and would never settle); the manual checklist in
``mod/tests/manual/locomotion-e2e.md`` describes the world-switch step.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import cv2
import grpclib
from grpclib.const import Status
from numpy.typing import NDArray

from resoio.camera import CameraClient
from resoio.locomotion import LocomotionClient, LocomotionCmd
from tests.helpers import mark_e2e

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# 18 s scenario × 30 Hz ≈ 540 commands. The asserted lower bound is more
# permissive (>= 300) to absorb gRPC back-pressure during world switch
# and the FAILED_PRECONDITION retry that consumes part of the budget on
# heavy worlds.
_SCENARIO_DURATION_S = 18.0
_TICK_HZ = 30
_TICK_INTERVAL_S = 1.0 / _TICK_HZ
_MIN_COMMANDS = 300

# Camera recording mirrors ``camera_stream.py`` (640x480 RGBA8 @ 30 fps).
# The lower-frame bound is intentionally loose: world switch + bridge
# warm-up consume a few seconds of the budget.
_CAPTURE_WIDTH = 640
_CAPTURE_HEIGHT = 480
_CAPTURE_FPS = 30.0
_MIN_CAMERA_FRAMES = 180

# Both bridges return FAILED_PRECONDITION until LocalUser / FocusedWorld
# are ready (and for Locomotion, until SmoothLocomotionBase is the
# active module). Retry budget is generous because world switch is a
# manual step in the e2e flow.
_BRIDGE_READY_TIMEOUT_S = 120.0
_BRIDGE_READY_RETRY_INTERVAL_S = 2.0


async def _wait_for_camera_ready() -> None:
    """Block until the Camera bridge accepts a stream (engine booted).

    Intentional copy of ``camera_stream.py``'s wait — three call sites
    is still below the bar for shared-helper extraction; a refactor
    would land in its own commit.
    """
    deadline = time.monotonic() + _BRIDGE_READY_TIMEOUT_S
    while True:
        try:
            async with CameraClient() as cam:
                async for _ in cam.stream(width=1, height=1, fps_limit=1.0):
                    return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Camera bridge did not become ready in "
                    f"{_BRIDGE_READY_TIMEOUT_S:.0f}s "
                    f"(last reason: {e.message})"
                ) from e
            await asyncio.sleep(_BRIDGE_READY_RETRY_INTERVAL_S)


def _scenario_command(elapsed: float) -> LocomotionCmd:
    """Return the command to send at ``elapsed`` seconds into the scenario.

    Phase boundaries are 0/3/5/7/9/11/13/14/16/18 s — the manual
    checklist (``mod/tests/manual/locomotion-e2e.md``) lists what each
    phase should look like on screen.
    """
    if elapsed < 3.0:
        return LocomotionCmd(move_y=1.0)
    if elapsed < 5.0:
        # Same forward input as the previous phase; velocity=2.0 must
        # produce a visibly larger travel distance on the recording.
        return LocomotionCmd(move_y=1.0, velocity=2.0)
    if elapsed < 7.0:
        return LocomotionCmd(move_x=1.0)
    if elapsed < 9.0:
        # Zero ExternalInput each tick so the engine friction snaps back to rest.
        return LocomotionCmd()
    if elapsed < 11.0:
        return LocomotionCmd(yaw_rate=0.5)
    if elapsed < 13.0:
        return LocomotionCmd(pitch_rate=0.5)
    if elapsed < 14.0:
        # Held for ~30 ticks; OR-merged DigitalAction means engine edge-detect
        # decides whether this is one jump or many.
        return LocomotionCmd(jump=True)
    if elapsed < 16.0:
        return LocomotionCmd(crouch=1.0)
    return LocomotionCmd()


class TestLocomotionDrive:
    @mark_e2e
    def test_drive_with_camera_recording(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"locomotion_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "capture.mp4"

        # ``mp4v`` is the codec most broadly available in pip-shipped
        # headless opencv. Writer dimensions must match the first frame
        # exactly — cv2 silently drops mis-sized frames — so the writer
        # is opened lazily once the first frame size is known (current
        # Camera bridge ignores the requested width/height and returns
        # the renderer's native resolution, so we cannot pre-pin a size).
        fourcc = cv2.VideoWriter.fourcc(*"mp4v")
        writer: cv2.VideoWriter | None = None
        writer_size: tuple[int, int] | None = None

        stop_event = asyncio.Event()

        async def capture_frames() -> int:
            nonlocal writer, writer_size
            count = 0
            async with CameraClient() as cam:
                async for frame in cam.stream(
                    width=_CAPTURE_WIDTH,
                    height=_CAPTURE_HEIGHT,
                    fps_limit=_CAPTURE_FPS,
                ):
                    # cvtColor copies into a fresh writable BGR buffer
                    # that VideoWriter accepts (MP4 / H.264 is not
                    # alpha-aware so the drop is lossless for our
                    # visual verification goal).
                    bgr: NDArray = cv2.cvtColor(frame.pixels, cv2.COLOR_RGBA2BGR)
                    if writer is None:
                        writer_size = (frame.width, frame.height)
                        writer = cv2.VideoWriter(
                            str(out_path), fourcc, _CAPTURE_FPS, writer_size
                        )
                    elif (frame.width, frame.height) != writer_size:
                        # Resize mid-stream is unsupported; resampling per
                        # frame would mask actual bridge behaviour. Skip
                        # to keep the writer aligned with its initial size.
                        count += 1
                        if stop_event.is_set():
                            break
                        continue
                    writer.write(bgr)
                    count += 1
                    if stop_event.is_set():
                        break
            return count

        async def drive_scenario() -> int:
            # Locomotion bridge also returns FAILED_PRECONDITION until
            # SmoothLocomotionBase is the active module — retry the
            # whole Drive RPC until it accepts the first command. Each
            # retry restarts the scenario timer so the on-screen phases
            # always land at the documented offsets.
            deadline = time.monotonic() + _BRIDGE_READY_TIMEOUT_S
            sent_total = 0
            while True:
                sent = 0
                t0 = time.monotonic()

                async def commands() -> AsyncIterator[LocomotionCmd]:
                    nonlocal sent
                    while True:
                        elapsed = time.monotonic() - t0
                        if elapsed >= _SCENARIO_DURATION_S:
                            return
                        yield _scenario_command(elapsed)
                        sent += 1
                        await asyncio.sleep(_TICK_INTERVAL_S)

                try:
                    async with LocomotionClient() as client:
                        await client.drive(commands())
                    sent_total = sent
                    return sent_total
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            f"Locomotion bridge did not become ready in "
                            f"{_BRIDGE_READY_TIMEOUT_S:.0f}s "
                            f"(last reason: {e.message}). Is a walk-capable "
                            "world loaded?"
                        ) from e
                    await asyncio.sleep(_BRIDGE_READY_RETRY_INTERVAL_S)

        async def run() -> tuple[int, int]:
            # Gate both streams behind a single Camera readiness probe;
            # the Locomotion retry loop handles its own FAILED_PRECONDITION
            # because the world-switch step lives between LocalUser
            # readiness and locomotion-controller readiness.
            await _wait_for_camera_ready()
            camera_task = asyncio.create_task(capture_frames())
            try:
                commands_sent = await drive_scenario()
            finally:
                stop_event.set()
            frames_captured = await camera_task
            return commands_sent, frames_captured

        try:
            commands_sent, frames_captured = asyncio.run(run())
        finally:
            if writer is not None:
                writer.release()

        # Surface the artifact path even on green CI runs.
        print(f"E2E artifact dir: {out_dir}")
        print(f"E2E MP4: {out_path}")
        print(
            f"locomotion commands={commands_sent}, camera frames={frames_captured}, "
            f"writer_size={writer_size}"
        )

        assert out_path.exists(), f"MP4 not created at {out_path}"
        # mp4v writes a ~257-byte header even when every frame is dropped
        # (size mismatch), so size > 0 alone does not prove playable
        # content. Require >= 10 KB so the assertion catches the silent
        # codec-failure path discovered on 2026-05-19.
        assert out_path.stat().st_size >= 10_000, (
            f"MP4 at {out_path} looks empty ({out_path.stat().st_size} bytes); "
            "writer likely silently dropped frames (codec or size mismatch)."
        )
        assert frames_captured >= _MIN_CAMERA_FRAMES, (
            f"expected >= {_MIN_CAMERA_FRAMES} camera frames in "
            f"~{_SCENARIO_DURATION_S:.0f}s @ {_CAPTURE_FPS} fps, "
            f"got {frames_captured}"
        )
        assert commands_sent >= _MIN_COMMANDS, (
            f"expected >= {_MIN_COMMANDS} locomotion commands in "
            f"~{_SCENARIO_DURATION_S:.0f}s @ {_TICK_HZ} Hz, "
            f"got {commands_sent}"
        )
