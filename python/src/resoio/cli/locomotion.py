"""``resoio locomotion drive`` subcommand: interactive WASD drive.

The mod-side bridge is a **stateful repeater** — it holds the most
recent command and re-injects it into the engine every update tick — so
this CLI is purely event-driven: a :class:`asyncio.Event` is set on
each state-altering keystroke, the loop wakes and calls
:meth:`LocomotionClient.send` once with the full hold-state, and then
blocks again until the next keypress. No tick loop is required. The CLI
holds the full state of every axis, so it passes all fields on every
``send`` (equivalent to the previous full-command behaviour). On graceful
exit (``q`` / EOF) the CLI calls
:meth:`LocomotionClient.reset` before closing the stream so the avatar
ends up neutral; Ctrl-C (UDS drop) is handled bridge-side by
auto-resetting on disconnect, no CLI cleanup needed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import termios
import tty
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from resoio.locomotion import DriveSummary, LocomotionClient


@dataclass
class _DriveState:
    """Mutable hold-state of every input axis the interactive drive tracks.

    Axes are exclusive within a pair (``w``/``s``, ``a``/``d``,
    ``LEFT``/``RIGHT``, ``UP``/``DOWN``): pressing the opposing key while
    one is held cancels it (toggle to neutral) before a second press flips
    the sign. Jump is the exception — it is an edge-trigger pulse, see
    :attr:`jump_pending`.
    """

    forward: float = 0.0
    right: float = 0.0
    up: float = 0.0
    yaw_rate: float = 0.0
    pitch_rate: float = 0.0
    sprint_on: bool = False
    crouch_on: bool = False
    # ``jump_pending`` is a single-shot signal: set by Space, drained by
    # the next :meth:`emit` call with ``consume_jump=True`` (the wire
    # producer). Consume-once at the engine level lives on the bridge —
    # it fires jump on exactly one tick — so this latch only exists to
    # make sure subsequent emits do not re-send ``jump=True``.
    jump_pending: bool = False

    async def emit(
        self,
        client: LocomotionClient,
        sprint_velocity: float,
        *,
        consume_jump: bool = False,
    ) -> None:
        """Send the full current hold-state via :meth:`LocomotionClient.send`.

        The CLI tracks every axis, so it always passes all fields (the
        bridge keeps no field "unset" from this caller's perspective —
        same behaviour as the previous full-command producer). When
        ``consume_jump`` is ``True`` the ``jump_pending`` latch is drained
        atomically with the send, keeping the drain in exactly one place;
        with the default ``False`` no field on ``self`` is mutated.
        """
        await client.send(
            move_forward=self.forward,
            move_right=self.right,
            move_up=self.up,
            yaw_rate=self.yaw_rate,
            pitch_rate=self.pitch_rate,
            jump=self.jump_pending,
            velocity=sprint_velocity if self.sprint_on else 1.0,
            crouch=1.0 if self.crouch_on else 0.0,
        )
        if consume_jump:
            self.jump_pending = False

    def reset(self) -> None:
        """Reset every axis to neutral (the ``x`` / ``0`` stop-all key)."""
        self.forward = 0.0
        self.right = 0.0
        self.up = 0.0
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.sprint_on = False
        self.crouch_on = False
        self.jump_pending = False


class _KeyParser:
    """Byte-oriented decoder that emits one key name per completed sequence.

    Recognises ASCII printables verbatim and ANSI arrow escape sequences
    ``ESC [ A/B/C/D`` as ``"UP" / "DOWN" / "RIGHT" / "LEFT"``.

    A bare ``ESC`` is *not* surfaced as its own key: the decoder always
    waits for the next byte to disambiguate. Exit is wired to ``q``
    instead, sidestepping the timeout-based ESC heuristic that would
    otherwise be needed with non-blocking stdin reads.
    """

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
        """Feed one byte; return the completed key (if any) as a 0/1-element
        list.

        The list-shaped return keeps the caller's ``for key in feed(b):``
        symmetric across the consumed-mid-sequence and completed-key cases.
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
            self._state = self._GROUND
            return []
        self._state = self._GROUND
        key = self._ARROW_MAP.get(byte)
        return [key] if key is not None else []


def _apply_key(
    state: _DriveState,
    key: str,
    look_rate: float,
    state_changed: asyncio.Event,
) -> bool:
    """Apply ``key`` to ``state``; return ``True`` iff an exit was requested.

    ``state_changed`` is the wake signal driving the event-driven send
    loop. Any recognised key that mutates ``state`` sets it so the next
    iteration emits exactly one fresh
    :meth:`LocomotionClient.send`. Unrecognised keys and the ``q`` exit key
    do not set it (the former never changed state; the latter triggers a
    separate stop path).
    """
    match key:
        case "w":
            state.forward = 1.0 if state.forward == 0.0 else 0.0
        case "s":
            state.forward = -1.0 if state.forward == 0.0 else 0.0
        case "a":
            state.right = -1.0 if state.right == 0.0 else 0.0
        case "d":
            state.right = 1.0 if state.right == 0.0 else 0.0
        case "r":
            state.up = 1.0 if state.up == 0.0 else 0.0
        case "f":
            state.up = -1.0 if state.up == 0.0 else 0.0
        case "LEFT":
            state.yaw_rate = -look_rate if state.yaw_rate == 0.0 else 0.0
        case "RIGHT":
            state.yaw_rate = look_rate if state.yaw_rate == 0.0 else 0.0
        case "UP":
            state.pitch_rate = look_rate if state.pitch_rate == 0.0 else 0.0
        case "DOWN":
            state.pitch_rate = -look_rate if state.pitch_rate == 0.0 else 0.0
        case " ":
            # Bridge handles consume-once: emitting jump=True in one
            # send() fires jump on exactly one engine tick.
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
            # Unrecognised: do not wake the producer.
            return False
    state_changed.set()
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
        f"move=(fwd{state.forward:+.1f},right{state.right:+.1f},up{state.up:+.1f}) "
        f"look=({state.yaw_rate:+.1f},{state.pitch_rate:+.1f}) "
        f"velocity={velocity:.2f} crouch={crouch_state}"
    )


# ---------------------------------------------------------------------------
# Async runtime layer
# ---------------------------------------------------------------------------


_BRIDGE_READY_TIMEOUT_S = 120.0
_BRIDGE_READY_RETRY_INTERVAL_S = 2.0


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
            "(WASD + r/f + arrows + Space/t/c/x/q) into LocomotionCommand "
            "messages. r / f は上昇 / 下降 (fly/noclip 中のみ有効)。 "
            "The mod-side bridge is a stateful repeater, so "
            "this CLI emits exactly one command per state-altering key "
            "press — no fixed tick rate is required."
        ),
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
        default=90.0,
        dest="look_rate",
        help=(
            "Yaw / pitch angular speed in deg/s while a look axis is held "
            "(default: 90.0). Resonite's own MouseLookSpeed default is "
            "100 deg/s and KeyboardLookSettings.HorizontalSpeed default is "
            "20 deg/s; 90 deg/s lands close to the mouse feel which suits "
            "interactive CLI driving better than the keyboard preset."
        ),
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
    a fresh client, push a single neutral ``send()`` (all fields unset, so
    the bridge keeps its initial neutral state), and accept either a clean
    exit or a ``FAILED_PRECONDITION`` GRPCError as a retry signal. Anything
    else propagates immediately.
    """
    import time

    import grpclib.exceptions
    from grpclib.const import Status

    from resoio.locomotion import LocomotionClient

    deadline = time.monotonic() + timeout_s
    while True:
        try:
            async with LocomotionClient(socket_path) as client:
                await client.send()
            return
        except grpclib.exceptions.GRPCError as exc:
            if exc.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"locomotion bridge did not become ready in "
                    f"{timeout_s:.0f}s (last reason: {exc.message})"
                ) from exc
            await asyncio.sleep(interval_s)


def _print_help(stream: TextIO, *, sprint: float, look_rate: float) -> None:
    """Print the keymap to ``stream`` once at start of session.

    Sent to stderr so the human-facing summary does not pollute stdout
    where the final ``DriveSummary`` is emitted (the latter is scriptable).
    """
    print(
        "resoio locomotion drive — interactive controls\n"
        "  w / s : forward / back toggle (mutually exclusive)\n"
        "  a / d : strafe left / right toggle (mutually exclusive)\n"
        "  r / f : 上昇 / 下降 (fly/noclip 中のみ有効)\n"
        "  LEFT/RIGHT arrows : yaw left / right toggle\n"
        "  UP/DOWN arrows    : look up / down toggle\n"
        "  Space : jump pulse (one tick)\n"
        f"  t : sprint toggle (velocity 1.0 <-> {sprint})\n"
        "  c : crouch toggle\n"
        "  x / 0 : stop all (reset every axis)\n"
        "  q : quit\n"
        f"settings: look_rate={look_rate} deg/s, sprint={sprint}",
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

    sprint: float = args.sprint
    look_rate: float = args.look_rate

    _print_help(sys.stderr, sprint=sprint, look_rate=look_rate)

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
    # state_changed wakes the event-driven send loop. The bridge is a
    # stateful repeater so we only emit on actual change.
    state_changed = asyncio.Event()
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
            # EOF (pipe closed or Ctrl-D): wake the producer and trip
            # the stop flag so the loop terminates after its current
            # iteration rather than hanging on state_changed.wait().
            stop_event.set()
            state_changed.set()
            return
        for byte in data:
            for key in parser.feed(byte):
                if _apply_key(state, key, look_rate, state_changed):
                    stop_event.set()
                    state_changed.set()
                    return

    summary: DriveSummary | None = None
    with _raw_tty(sys.stdin):
        loop.add_reader(stdin_fd, on_stdin)
        try:
            async with LocomotionClient(args.socket) as client:
                try:
                    # Initial neutral so the bridge sees the client and
                    # latches a defined state immediately, instead of
                    # waiting for the first keystroke. ``consume_jump=True``
                    # is the single drain site for ``jump_pending``: the
                    # bridge handles consume-once at the engine level, but
                    # the next emit must not re-send ``jump=True``.
                    await state.emit(client, sprint, consume_jump=True)
                    _write_status(sys.stderr, state, sprint)
                    while not stop_event.is_set():
                        await state_changed.wait()
                        state_changed.clear()
                        if stop_event.is_set():
                            break
                        await state.emit(client, sprint, consume_jump=True)
                        _write_status(sys.stderr, state, sprint)
                except grpclib.exceptions.GRPCError as exc:
                    print(
                        f"\nlocomotion drive failed: {exc.status.name} {exc.message}",
                        file=sys.stderr,
                    )
                    return 1

                # Graceful exit (q / EOF) keeps the bridge state alive
                # otherwise; explicit reset returns the avatar to
                # neutral. Ctrl-C / UDS drop is handled bridge-side
                # (auto-reset on disconnect) so no CLI hook is needed.
                try:
                    await client.reset()
                except grpclib.exceptions.GRPCError as exc:
                    # Reset failure is non-fatal — summary still prints.
                    print(
                        f"\nlocomotion reset failed: {exc.status.name} {exc.message}",
                        file=sys.stderr,
                    )

            # Context has exited: the Drive stream was closed gracefully and
            # the server summary is resolved on the client.
            summary = client.drive_summary
        finally:
            loop.remove_reader(stdin_fd)
            # Close the status line so subsequent stderr output starts on
            # a fresh row regardless of how we exited.
            print("", file=sys.stderr)

    if summary is None:
        print("locomotion drive: no summary produced", file=sys.stderr)
        return 1

    print(
        f"received_count={summary.received_count} "
        f"dropped_count={summary.dropped_count} "
        f"unix_nanos={summary.unix_nanos}"
    )
    return 0
