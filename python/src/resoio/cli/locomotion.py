"""``resoio locomotion drive`` subcommand: interactive WASD drive.

Two layers live here:

* The **pure logic layer** — :class:`_DriveState` / :class:`_KeyParser` /
  :func:`_apply_key` / :func:`_format_status` — is unit-tested in
  isolation (no asyncio, no termios, no gRPC). Phase 1A delivered this
  half.
* The **async runtime layer** — :func:`register` / :func:`_run_drive`
  plus :func:`_raw_tty` and :func:`_wait_for_bridge_ready` — wires the
  pure logic up to a UDS gRPC client, raw-mode stdin via ``asyncio``'s
  ``add_reader``, and a Bridge-ready retry loop.

Engine-side constraint that shapes this file: ``ExternalInput`` is
consumed and nulled every update tick, so we send at a fixed cadence
(default 30 Hz) for the entire session — any input held by the user is
re-asserted on every tick rather than transmitted as a single edge.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import termios
import tty
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO

from resoio.locomotion import LocomotionCmd

if TYPE_CHECKING:
    from resoio.locomotion import DriveSummary

# Listed here so pyright does not flag the Phase 1A pure-logic helpers as
# unused: they are exercised by the test suite and consumed in-module by
# the Phase 2 async runtime additions, but neither path is visible to a
# strict-mode scan of ``src/`` alone.
__all__ = [
    "_DriveState",
    "_KeyParser",
    "_apply_key",
    "_format_status",
]


@dataclass
class _DriveState:
    """Mutable hold-state of every input axis the interactive drive tracks.

    Axes are exclusive within a pair (``w``/``s``, ``a``/``d``,
    ``LEFT``/``RIGHT``, ``UP``/``DOWN``): pressing the opposing key while
    one is held cancels it (toggle to neutral) before a second press flips
    the sign. Jump is the exception — it is an edge-trigger pulse, see
    :meth:`to_cmd`.
    """

    move_y: float = 0.0
    move_x: float = 0.0
    yaw_rate: float = 0.0
    pitch_rate: float = 0.0
    sprint_on: bool = False
    crouch_on: bool = False
    jump_pending: bool = False

    def to_cmd(self, sprint_velocity: float) -> LocomotionCmd:
        """Snapshot the current state into a :class:`LocomotionCmd`.

        ``jump_pending`` is drained to ``False`` after every call so a
        single Space press emits ``jump=True`` on exactly one tick — the
        engine's ``ExternalInput`` has no edge detection and would treat
        a held ``True`` as continuous re-jumping.
        """
        cmd = LocomotionCmd(
            move_x=self.move_x,
            move_y=self.move_y,
            yaw_rate=self.yaw_rate,
            pitch_rate=self.pitch_rate,
            jump=self.jump_pending,
            velocity=sprint_velocity if self.sprint_on else 1.0,
            crouch=1.0 if self.crouch_on else 0.0,
        )
        self.jump_pending = False
        return cmd

    def reset(self) -> None:
        """Reset every axis to neutral (the ``x`` / ``0`` stop-all key)."""
        self.move_y = 0.0
        self.move_x = 0.0
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.sprint_on = False
        self.crouch_on = False
        self.jump_pending = False


class _KeyParser:
    """Byte-oriented decoder that emits one key name per completed sequence.

    Accepts a single byte at a time so the caller can feed an
    ``os.read()`` buffer in order without buffering decisions of its own.
    Recognises ASCII printables verbatim and ANSI arrow escape sequences
    ``ESC [ A/B/C/D`` as ``"UP" / "DOWN" / "RIGHT" / "LEFT"``.

    A bare ``ESC`` is *not* surfaced as its own key: the decoder always
    waits for the next byte to disambiguate. Exit is wired to ``q``
    instead, sidestepping the timeout-based ESC heuristic that would
    otherwise be needed with non-blocking stdin reads.
    """

    # 3-state state machine: 0 = ground, 1 = saw ESC, 2 = saw ESC '['.
    _GROUND = 0
    _ESC = 1
    _CSI = 2

    _ARROW_MAP = {
        ord("A"): "UP",
        ord("B"): "DOWN",
        ord("C"): "RIGHT",
        ord("D"): "LEFT",
    }

    def __init__(self) -> None:
        self._state: int = self._GROUND

    def feed(self, byte: int) -> list[str]:
        """Feed one byte; return zero or one key names (list for batchability).

        Returning a list keeps the call-site symmetric across the
        "consumed mid-sequence" case (``[]``) and the "completed key"
        case (``["UP"]``), so the caller can simply iterate.
        """
        if self._state == self._GROUND:
            if byte == 0x1B:
                self._state = self._ESC
                return []
            return [chr(byte)]
        if self._state == self._ESC:
            if byte == ord("["):
                self._state = self._CSI
                return []
            # Any non-'[' aborts the ESC sequence; drop it to ground silently.
            self._state = self._GROUND
            return []
        # _CSI: expect A/B/C/D; anything else is an unsupported sequence.
        self._state = self._GROUND
        key = self._ARROW_MAP.get(byte)
        return [key] if key is not None else []


def _apply_key(
    state: _DriveState,
    key: str,
    look_rate: float,
    sprint_velocity: float,  # noqa: ARG001 - kept for symmetry with Phase 2 status renderer
) -> bool:
    """Apply ``key`` to ``state``; return ``True`` iff an exit was requested.

    The ``sprint_velocity`` parameter is unused here — sprint magnitude
    is applied in :meth:`_DriveState.to_cmd`. It is kept on the
    signature so the Phase 2 status renderer (which interleaves
    ``_apply_key`` and status redraws) can pass the same value to both
    without inspecting ``args``.
    """
    # Pair semantics: pressing the same key toggles between target and 0;
    # pressing the opposite key while engaged cancels to 0 (one press to
    # cancel, a second press to flip). The "engaged with opposite" branch
    # is what makes a held-w + tap-s sequence land on neutral rather than
    # snapping straight to -1.
    match key:
        case "w":
            state.move_y = 1.0 if state.move_y == 0.0 else 0.0
        case "s":
            state.move_y = -1.0 if state.move_y == 0.0 else 0.0
        case "a":
            state.move_x = -1.0 if state.move_x == 0.0 else 0.0
        case "d":
            state.move_x = 1.0 if state.move_x == 0.0 else 0.0
        case "LEFT":
            state.yaw_rate = -look_rate if state.yaw_rate == 0.0 else 0.0
        case "RIGHT":
            state.yaw_rate = look_rate if state.yaw_rate == 0.0 else 0.0
        case "UP":
            state.pitch_rate = look_rate if state.pitch_rate == 0.0 else 0.0
        case "DOWN":
            state.pitch_rate = -look_rate if state.pitch_rate == 0.0 else 0.0
        case " ":
            # One-tick pulse; drained by to_cmd() on the next emit.
            state.jump_pending = True
        case "t":
            state.sprint_on = not state.sprint_on
        case "c":
            state.crouch_on = not state.crouch_on
        case "x" | "0":
            state.reset()
        case "q":
            return True
        case _:
            pass
    return False


def _format_status(state: _DriveState, sprint_velocity: float) -> str:
    """Render a single-line status of the held axes (no ``\\r`` / newline).

    Excludes ``jump_pending`` since it lives for a single tick — the
    rendered line is meant for a held-keys overview, not the per-frame
    payload.
    """
    velocity = sprint_velocity if state.sprint_on else 1.0
    crouch_state = "on" if state.crouch_on else "off"
    return (
        f"move=({state.move_x:+.1f},{state.move_y:+.1f}) "
        f"look=({state.yaw_rate:+.1f},{state.pitch_rate:+.1f}) "
        f"velocity={velocity:.2f} crouch={crouch_state}"
    )


# ---------------------------------------------------------------------------
# Async runtime layer
# ---------------------------------------------------------------------------


_BRIDGE_READY_TIMEOUT_S = 120.0
_BRIDGE_READY_RETRY_INTERVAL_S = 2.0


def _positive_float(raw: str) -> float:
    """Reject zero/negative values that would cause an infinite tick period."""
    value = float(raw)
    if value <= 0.0:
        raise argparse.ArgumentTypeError(f"must be positive, got {value}")
    return value


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``locomotion`` subparser with nested ``drive``.

    ``common`` is re-attached on the leaf (not just the ``locomotion``
    node) because argparse does not inherit shared flags from a parent
    subparser to its children; ``resoio locomotion drive -s SOCK`` would
    otherwise drop ``-s`` on the leaf's namespace.

    The nesting (``locomotion drive`` rather than just ``locomotion``)
    leaves room for future ``send`` / ``play`` one-shot subcommands
    without breaking the published CLI surface.
    """
    parser = subparsers.add_parser(
        "locomotion",
        parents=[common],
        help="Drive avatar locomotion (move / look / jump / sprint / crouch).",
        description=(
            "Drive the Resonite IO Locomotion service. Subcommands group "
            "interactive (drive) and (future) scripted entry points."
        ),
    )
    locomotion_subs = parser.add_subparsers(dest="locomotion_command", required=True)

    drive_parser = locomotion_subs.add_parser(
        "drive",
        parents=[common],
        help="Interactive WASD drive over the Resonite IO UDS.",
        description=(
            "Open a Locomotion stream and translate keyboard input "
            "(WASD + arrows + Space/t/c/x/q) into LocomotionCommand "
            "messages emitted at a fixed cadence. Engine consumes and "
            "nulls ExternalInput every update tick so held axes are "
            "re-asserted by --rate Hz."
        ),
    )
    drive_parser.add_argument(
        "--rate",
        type=_positive_float,
        default=30.0,
        help="Tick frequency in Hz (default: 30.0).",
    )
    drive_parser.add_argument(
        "--sprint",
        type=float,
        default=2.0,
        help=(
            "LocomotionCommand.velocity to send while sprint is toggled on "
            "(default: 2.0)."
        ),
    )
    drive_parser.add_argument(
        "--look-rate",
        type=float,
        default=1.0,
        dest="look_rate",
        help="Yaw / pitch rate amplitude while a look axis is held (default: 1.0).",
    )
    drive_parser.add_argument(
        "--no-wait",
        action="store_true",
        dest="no_wait",
        help=(
            "Skip the Bridge-ready retry loop (default: retry "
            f"FAILED_PRECONDITION for up to {_BRIDGE_READY_TIMEOUT_S:.0f}s)."
        ),
    )
    drive_parser.set_defaults(func=_run_drive)


@contextmanager
def _raw_tty(stream: TextIO) -> Generator[None]:
    """Put ``stream`` into cbreak mode and restore on exit.

    The ``finally`` branch is the load-bearing piece: if the asyncio
    loop crashes mid-drive the terminal must end up echoing again or
    the user's shell is left effectively unusable.

    A non-tty fd (pipe / file) is a no-op rather than an error so
    end-to-end tests can feed canned input via ``os.pipe()`` without
    needing a pty.
    """
    fd: int
    try:
        fd = stream.fileno()
    except (OSError, ValueError):
        # No fd at all — nothing to switch to raw mode.
        yield
        return
    if not os.isatty(fd):
        yield
        return
    original = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


async def _wait_for_bridge_ready(
    socket_path: str | None,
    timeout_s: float = _BRIDGE_READY_TIMEOUT_S,
    interval_s: float = _BRIDGE_READY_RETRY_INTERVAL_S,
) -> None:
    """Block until ``Locomotion.Drive`` no longer raises
    ``FAILED_PRECONDITION``.

    Same shape as ``tests/e2e/locomotion.py:_wait_for_camera_ready``: open
    a fresh client, push a single neutral command, and accept either a
    clean summary or a ``FAILED_PRECONDITION`` GRPCError as a retry
    signal. Anything else propagates immediately.
    """
    import time as _time

    import grpclib.exceptions
    from grpclib.const import Status

    from resoio.locomotion import LocomotionClient

    deadline = _time.monotonic() + timeout_s
    while True:
        try:
            async with LocomotionClient(socket_path) as client:

                async def _one_neutral() -> AsyncIterator[LocomotionCmd]:
                    yield LocomotionCmd()

                await client.drive(_one_neutral())
            return
        except grpclib.exceptions.GRPCError as exc:
            if exc.status != Status.FAILED_PRECONDITION:
                raise
            if _time.monotonic() > deadline:
                raise TimeoutError(
                    f"locomotion bridge did not become ready in "
                    f"{timeout_s:.0f}s (last reason: {exc.message})"
                ) from exc
            await asyncio.sleep(interval_s)


def _print_help(
    stream: TextIO, *, sprint: float, look_rate: float, rate: float
) -> None:
    """Print the keymap to ``stream`` once at start of session.

    Sent to stderr so the human-facing summary does not pollute stdout
    where the final ``DriveSummary`` is emitted (the latter is scriptable).
    """
    print(
        "resoio locomotion drive — interactive controls\n"
        "  w / s : forward / back toggle (mutually exclusive)\n"
        "  a / d : strafe left / right toggle (mutually exclusive)\n"
        "  LEFT/RIGHT arrows : yaw left / right toggle\n"
        "  UP/DOWN arrows    : look up / down toggle\n"
        "  Space : jump pulse (one tick)\n"
        f"  t : sprint toggle (velocity 1.0 <-> {sprint})\n"
        "  c : crouch toggle\n"
        "  x / 0 : stop all (reset every axis)\n"
        "  q : quit\n"
        f"settings: rate={rate} Hz, look_rate={look_rate}, sprint={sprint}",
        file=stream,
    )


def _write_status(stream: TextIO, state: _DriveState, sprint_velocity: float) -> None:
    """Overwrite the status line in place with the current held-axis
    snapshot."""
    line = _format_status(state, sprint_velocity)
    # Leading \r so the line is overwritten rather than scrolled; no
    # newline so the cursor stays parked on the same row.
    stream.write("\r" + line)
    stream.flush()


async def _run_drive(args: argparse.Namespace) -> int:
    """Open a Locomotion stream and translate stdin into LocomotionCommands."""
    # Deferred to keep `resoio --help` and shell completion fast.
    import grpclib.exceptions

    from resoio.locomotion import LocomotionClient

    rate: float = args.rate
    sprint: float = args.sprint
    look_rate: float = args.look_rate

    _print_help(sys.stderr, sprint=sprint, look_rate=look_rate, rate=rate)

    if not args.no_wait:
        try:
            await _wait_for_bridge_ready(args.socket)
        except TimeoutError as exc:
            print(f"locomotion bridge not ready: {exc}", file=sys.stderr)
            return 1
        except grpclib.exceptions.GRPCError as exc:
            print(
                f"locomotion bridge error: {exc.status.name} {exc.message}",
                file=sys.stderr,
            )
            return 1

    state = _DriveState()
    stop_event = asyncio.Event()
    period = 1.0 / rate
    parser = _KeyParser()
    loop = asyncio.get_running_loop()

    # If stdin has no fd (e.g. captured by pytest), bail before opening
    # the gRPC channel — there is no useful drive to run.
    try:
        stdin_fd = sys.stdin.fileno()
    except (OSError, ValueError):
        print("resoio locomotion drive: stdin has no fd", file=sys.stderr)
        return 1

    def on_stdin() -> None:
        try:
            data = os.read(stdin_fd, 64)
        except BlockingIOError:
            return
        if not data:
            # EOF (pipe closed or Ctrl-D): exit cleanly so the summary
            # still prints.
            stop_event.set()
            return
        for byte in data:
            for key in parser.feed(byte):
                if _apply_key(state, key, look_rate, sprint):
                    stop_event.set()
                    return

    summary: DriveSummary
    with _raw_tty(sys.stdin):
        loop.add_reader(stdin_fd, on_stdin)
        try:
            async with LocomotionClient(args.socket) as client:

                async def commands() -> AsyncIterator[LocomotionCmd]:
                    while not stop_event.is_set():
                        cmd = state.to_cmd(sprint)
                        yield cmd
                        _write_status(sys.stderr, state, sprint)
                        await asyncio.sleep(period)

                try:
                    summary = await client.drive(commands())
                except grpclib.exceptions.GRPCError as exc:
                    print(
                        f"\nlocomotion drive failed: {exc.status.name} {exc.message}",
                        file=sys.stderr,
                    )
                    return 1
        finally:
            loop.remove_reader(stdin_fd)
            # Close the status line so subsequent stderr output starts on
            # a fresh row regardless of how we exited.
            print("", file=sys.stderr)

    print(
        f"received_count={summary.received_count} "
        f"dropped_count={summary.dropped_count} "
        f"unix_nanos={summary.unix_nanos}"
    )
    return 0
