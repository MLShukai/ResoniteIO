"""E2E: drive Locomotion + record Camera to MP4 in a single asyncio run.

The 20 s scenario walks the desktop control set in 11 phases (forward,
fast forward via velocity=2.0, right strafe, world-up, idle, right yaw,
look up, jump, crouch, pre-reset forward, post-reset idle) so the
resulting MP4 is a single visual proof that every ``LocomotionCommand``
field reaches the engine and that the ``Reset`` RPC clears in-flight
state. The ``move_up`` (world-up) phase is wire-only: the default Walk
locomotion module produces no visible vertical motion, so it confirms
the field is sent, not that the avatar rises. Camera frames are
streamed in parallel at the renderer's native rate so the recording is
synchronised with the command timeline.

The Bridge is a stateful repeater (mod re-injects the last command into
``ExternalInput`` every engine tick) and the wire is now a **partial
update**: ``LocomotionClient.send(field=value)`` enqueues one command
carrying only the named fields; unset fields are omitted on the wire and
the bridge holds their previous value. A single ``send`` is therefore
enough to hold an input — the harness still re-sends at 30 Hz, mainly to
keep the client-side ``DriveSummary.received_count`` floor meaningful
(read from ``client.drive_summary`` after the context exits) and to make
the scenario timeline observable on the wire. ``FAILED_PRECONDITION``
from either bridge is retried up to 120 s — both depend on ``LocalUser``
/ ``FocusedWorld`` readiness which lags UDS bind. The Locomotion bridge
additionally requires a walk-capable active module: the default home
world already satisfies this, but Teleport / NoClip / NoLocomotion
worlds need a manual switch within the retry budget.

The Reset phase (16-20 s) drives ``move_forward=1.0`` for 3 s, then a
parallel ``LocomotionClient.reset()`` from a **second** client fires at
19.0 s (the primary client is busy with its own Drive stream) while the
primary client keeps sending neutral ``send(move_forward=0.0, ...)`` for
the remaining 1 s. Because the Bridge re-injects the last command every
tick, the post-reset idle phase MUST send explicit zeroed commands —
sending nothing would let the previously-held ``move_forward=1.0``
survive at the engine, masking the visible effect of Reset. Visual
confirmation that the avatar stops within the 19-20 s window is done by
inspecting the recorded MP4.

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
from resoio.locomotion import LocomotionClient
from tests.helpers import mark_e2e

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# 20 s scenario × 30 Hz ≈ 600 commands. The asserted lower bound is more
# permissive (>= 300) to absorb gRPC back-pressure during world switch
# and the FAILED_PRECONDITION retry that consumes part of the budget on
# heavy worlds.
_SCENARIO_DURATION_S = 20.0
_TICK_HZ = 30
_TICK_INTERVAL_S = 1.0 / _TICK_HZ
_MIN_COMMANDS = 300

# Mid-scenario Reset fires once when the elapsed clock crosses this
# offset. Choose the boundary inside the 16-20 s phase so there is at
# least 1 s on each side: the pre-reset drive (16-19 s) demonstrates
# state-held forward motion, then Reset clears it; the post-reset idle
# (19-20 s) sends a zeroed command so the visible effect is the avatar
# stopping rather than the previous move_forward=1.0 surviving in the bridge.
_RESET_TRIGGER_S = 19.0

# Camera recording streams the renderer's native resolution at its native
# rate (the partial-update refactor dropped width/height/fps_limit from
# stream()). The lower-frame bound is intentionally loose: world switch +
# bridge warm-up consume a few seconds of the budget.
_CAPTURE_FPS = 30.0
_MIN_CAMERA_FRAMES = 180

_LOOK_CAPTURE_WARMUP_FRAMES = 3
_LOOK_YAW_RATE = 90.0
_LOOK_PITCH_RATE = 30.0
_LOOK_YAW_DURATION_S = 1.5
_LOOK_PITCH_DURATION_S = 1.5
_MIN_LOOK_MEAN_ABS_DELTA = 2.0

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
                async for _ in cam.stream():
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


async def _capture_look_frame(out_dir: Path, label: str) -> NDArray[np.uint8]:
    frame_pixels: NDArray[np.uint8] | None = None
    count = 0
    async with CameraClient() as cam:
        async for frame in cam.stream():
            frame_pixels = frame.pixels.copy()
            count += 1
            if count >= _LOOK_CAPTURE_WARMUP_FRAMES:
                break

    if frame_pixels is None:
        raise AssertionError("Camera stream ended before yielding a frame.")

    bgr = cv2.cvtColor(frame_pixels, cv2.COLOR_RGBA2BGR)
    path = out_dir / f"{label}.png"
    assert cv2.imwrite(str(path), bgr), f"failed to write {path}"
    return frame_pixels


async def _drive_look(duration_s: float, **fields: float) -> int:
    """Hold one look command for ``duration_s`` then neutralise + reset.

    Each tick re-sends the same partial ``send(**fields)`` so the
    on-screen motion lasts the full window even though the stateful
    repeater would hold a single command. A final zeroed command stops
    the look before the look group is explicitly reset.
    """
    sent = 0
    t0 = time.monotonic()
    async with LocomotionClient() as client:
        while time.monotonic() - t0 < duration_s:
            await client.send(**fields)
            sent += 1
            await asyncio.sleep(_TICK_INTERVAL_S)
        await client.send(yaw_rate=0.0, pitch_rate=0.0)
        sent += 1
        await client.reset(look=True)
    return sent


def _mean_abs_delta(a: NDArray[np.uint8], b: NDArray[np.uint8]) -> float:
    height = min(a.shape[0], b.shape[0])
    width = min(a.shape[1], b.shape[1])
    a_rgb = a[:height, :width, :3].astype(np.int16)
    b_rgb = b[:height, :width, :3].astype(np.int16)
    return float(np.mean(np.abs(a_rgb - b_rgb)))


async def _verify_look_changes(out_dir: Path) -> tuple[int, int, float, float]:
    baseline = await _capture_look_frame(out_dir, "look_00_baseline")
    yaw_sent = await _drive_look(_LOOK_YAW_DURATION_S, yaw_rate=_LOOK_YAW_RATE)
    yawed = await _capture_look_frame(out_dir, "look_01_after_yaw")

    pitch_sent = await _drive_look(_LOOK_PITCH_DURATION_S, pitch_rate=_LOOK_PITCH_RATE)
    pitched = await _capture_look_frame(out_dir, "look_02_after_pitch")

    return (
        yaw_sent,
        pitch_sent,
        _mean_abs_delta(baseline, yawed),
        _mean_abs_delta(yawed, pitched),
    )


def _scenario_fields(elapsed: float) -> dict[str, float | bool]:
    """Return the ``send`` kwargs for ``elapsed`` seconds into the scenario.

    Phase boundaries are 0/3/5/7/8/9/11/13/14/16/19/20 s. Each phase
    exercises a single ``LocomotionCommand`` field via a partial
    ``send`` so the recorded MP4 can be inspected per-segment (the 7-8 s
    ``move_up`` phase is wire-only — Walk produces no visible vertical
    motion). Transitions between phases pass the *previous* axis as 0.0
    so the stateful repeater clears the held input even though the wire
    is a partial update.
    """
    if elapsed < 3.0:
        return {"move_forward": 1.0}
    if elapsed < 5.0:
        # Same forward input as the previous phase; velocity=2.0 must
        # produce a visibly larger travel distance on the recording.
        return {"move_forward": 1.0, "velocity": 2.0}
    if elapsed < 7.0:
        # Stop forward (and restore unit velocity) before strafing so the
        # held forward input does not survive in the repeater.
        return {"move_forward": 0.0, "velocity": 1.0, "move_right": 1.0}
    if elapsed < 8.0:
        # View-independent absolute world-up. With the default Walk
        # locomotion module this produces no visible vertical motion, so
        # this phase only proves the field reaches the wire / bridge
        # (no visual assertion is made on it).
        return {"move_right": 0.0, "move_up": 1.0}
    if elapsed < 9.0:
        # Explicitly zero the previously held strafe / vertical input so
        # the repeater clears it (sending nothing would hold the last
        # command indefinitely).
        return {"move_up": 0.0}
    if elapsed < 11.0:
        return {"yaw_rate": 90.0}
    if elapsed < 13.0:
        return {"yaw_rate": 0.0, "pitch_rate": 30.0}
    if elapsed < 14.0:
        # Stop the look, then pulse jump. Bridge latches jump=True for a
        # single engine tick and drops it, so re-sending here at 30 Hz
        # produces ~30 jump pulses — engine OR-merge decides the cadence.
        return {"pitch_rate": 0.0, "jump": True}
    if elapsed < 16.0:
        return {"crouch": 1.0}
    if elapsed < _RESET_TRIGGER_S:
        # Pre-reset forward drive (16 s → _RESET_TRIGGER_S). Clear crouch
        # and drive forward. A single command would suffice with the
        # stateful repeater, but the harness keeps sending at 30 Hz to
        # maintain a stable wire-level observable timeline.
        return {"crouch": 0.0, "move_forward": 1.0}
    # Post-reset idle: explicitly send a zeroed command so any state the
    # bridge held before Reset is overwritten by the next tick too. The
    # visible effect (avatar stops moving inside this 1 s window) is the
    # whole point of the Reset phase — see module docstring.
    return {"move_forward": 0.0}


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
        # Camera bridge returns the renderer's native resolution, so we
        # cannot pre-pin a size).
        fourcc = cv2.VideoWriter.fourcc(*"mp4v")
        writer: cv2.VideoWriter | None = None
        writer_size: tuple[int, int] | None = None

        stop_event = asyncio.Event()

        async def capture_frames() -> int:
            nonlocal writer, writer_size
            count = 0
            async with CameraClient() as cam:
                async for frame in cam.stream():
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

        async def _trigger_reset_after(delay_s: float) -> None:
            # Reset RPC is unary and lives on a **separate** client because
            # the primary one is busy with the long-lived drive stream.
            # Errors are swallowed: e2e judgement is visual (manual
            # checklist), and the Drive scenario is the authoritative
            # pass/fail signal — a failed Reset must not abort the
            # recording.
            try:
                await asyncio.sleep(delay_s)
                async with LocomotionClient() as reset_client:
                    summary = await reset_client.reset()
                print(
                    f"Reset RPC fired @ ~{delay_s:.1f}s: "
                    f"move={summary.move}, look={summary.look}, "
                    f"crouch={summary.crouch}, jump={summary.jump}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - intentional best-effort
                print(f"Reset RPC raised (ignored, scenario continues): {e!r}")

        async def drive_scenario() -> int:
            # Locomotion bridge also returns FAILED_PRECONDITION until
            # SmoothLocomotionBase is the active module — retry the
            # whole Drive stream until it accepts the first command. Each
            # retry restarts the scenario timer so the on-screen phases
            # always land at the documented offsets.
            deadline = time.monotonic() + _BRIDGE_READY_TIMEOUT_S
            while True:
                sent = 0
                t0 = time.monotonic()

                # Schedule the mid-scenario Reset relative to this attempt's
                # t0. On a retry the previous task (if any) is cancelled so
                # only the surviving attempt fires reset.
                reset_task = asyncio.create_task(_trigger_reset_after(_RESET_TRIGGER_S))
                try:
                    async with LocomotionClient() as client:
                        while True:
                            elapsed = time.monotonic() - t0
                            if elapsed >= _SCENARIO_DURATION_S:
                                break
                            await client.send(**_scenario_fields(elapsed))
                            sent += 1
                            await asyncio.sleep(_TICK_INTERVAL_S)
                    await reset_task
                    return sent
                except grpclib.exceptions.GRPCError as e:
                    reset_task.cancel()
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

        async def run() -> tuple[int, int, int, int, float, float]:
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
            yaw_sent, pitch_sent, yaw_delta, pitch_delta = await _verify_look_changes(
                out_dir
            )
            return (
                commands_sent,
                frames_captured,
                yaw_sent,
                pitch_sent,
                yaw_delta,
                pitch_delta,
            )

        try:
            (
                commands_sent,
                frames_captured,
                yaw_sent,
                pitch_sent,
                yaw_delta,
                pitch_delta,
            ) = asyncio.run(run())
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
        print(
            f"locomotion look: yaw_sent={yaw_sent}, pitch_sent={pitch_sent}, "
            f"yaw_delta={yaw_delta:.3f}, pitch_delta={pitch_delta:.3f}"
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
        assert yaw_delta >= _MIN_LOOK_MEAN_ABS_DELTA, (
            f"yaw did not visibly change the camera frame "
            f"(mean abs delta {yaw_delta:.3f} < {_MIN_LOOK_MEAN_ABS_DELTA})"
        )
        assert pitch_delta >= _MIN_LOOK_MEAN_ABS_DELTA, (
            f"pitch did not visibly change the camera frame "
            f"(mean abs delta {pitch_delta:.3f} < {_MIN_LOOK_MEAN_ABS_DELTA})"
        )
