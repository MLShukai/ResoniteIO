import asyncio
import io
import os
import pty
import termios
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    LocomotionBase,
    LocomotionCommand,
    LocomotionDriveSummary,
    LocomotionResetRequest,
    LocomotionResetSummary,
)
from resoio.cli import _amain, _build_parser
from resoio.cli.locomotion import (
    _apply_key,
    _DriveState,
    _format_status,
    _KeyParser,
    _raw_tty,
    _run_drive,
    _wait_for_bridge_ready,
)


def _apply(state: _DriveState, key: str, look_rate: float = 1.0) -> bool:
    """Test shim: call _apply_key with a fresh signal event we drop.

    Most _apply_key tests do not care about the wake signal; only the
    "did this state-change set the event?" assertion does. Pinning the
    signature here keeps the rest of the suite terse.
    """
    return _apply_key(state, key, look_rate, asyncio.Event())


# ---------------------------------------------------------------------------
# Move toggles (w/s, a/d)
# ---------------------------------------------------------------------------


def test_w_toggles_move_y_forward_and_back_to_neutral():
    state = _DriveState()
    assert _apply(state, "w") is False
    assert state.move_y == 1.0
    assert _apply(state, "w") is False
    assert state.move_y == 0.0


def test_s_cancels_held_w_then_flips_negative():
    state = _DriveState(move_y=1.0)
    assert _apply(state, "s") is False
    assert state.move_y == 0.0  # exclusive cancel
    assert _apply(state, "s") is False
    assert state.move_y == -1.0


def test_a_and_d_are_exclusive_on_move_x():
    state = _DriveState()
    _apply(state, "d")
    assert state.move_x == 1.0
    _apply(state, "a")
    assert state.move_x == 0.0  # d cancelled by a
    _apply(state, "a")
    assert state.move_x == -1.0


# ---------------------------------------------------------------------------
# Look toggles (UP/DOWN, LEFT/RIGHT)
# ---------------------------------------------------------------------------


def test_up_toggles_pitch_at_look_rate():
    state = _DriveState()
    _apply(state, "UP", 0.5)
    assert state.pitch_rate == 0.5
    _apply(state, "UP", 0.5)
    assert state.pitch_rate == 0.0


def test_down_cancels_up_then_flips_negative():
    state = _DriveState(pitch_rate=0.5)
    _apply(state, "DOWN", 0.5)
    assert state.pitch_rate == 0.0
    _apply(state, "DOWN", 0.5)
    assert state.pitch_rate == -0.5


def test_left_and_right_are_exclusive_on_yaw():
    state = _DriveState()
    _apply(state, "RIGHT", 0.5)
    assert state.yaw_rate == 0.5
    _apply(state, "LEFT", 0.5)
    assert state.yaw_rate == 0.0  # right cancelled by left
    _apply(state, "LEFT", 0.5)
    assert state.yaw_rate == -0.5


# ---------------------------------------------------------------------------
# Sprint (t) and the velocity field on to_cmd()
# ---------------------------------------------------------------------------


def test_t_toggles_sprint_flag():
    state = _DriveState()
    _apply(state, "t")
    assert state.sprint_on is True
    _apply(state, "t")
    assert state.sprint_on is False


def test_to_cmd_velocity_reflects_sprint_state():
    state = _DriveState()
    assert state.to_cmd(2.0).velocity == 1.0
    state.sprint_on = True
    assert state.to_cmd(2.0).velocity == 2.0
    # Custom sprint magnitude propagates through to the cmd.
    assert state.to_cmd(3.5).velocity == 3.5


# ---------------------------------------------------------------------------
# Crouch (c)
# ---------------------------------------------------------------------------


def test_c_toggles_crouch_flag_and_cmd_crouch_field():
    state = _DriveState()
    _apply(state, "c")
    assert state.crouch_on is True
    assert state.to_cmd(2.0).crouch == 1.0
    _apply(state, "c")
    assert state.crouch_on is False
    assert state.to_cmd(2.0).crouch == 0.0


# ---------------------------------------------------------------------------
# Jump pulse (Space) — bridge-side consume-once; to_cmd is now a pure read
# ---------------------------------------------------------------------------


def test_space_sets_jump_pending_for_next_to_cmd():
    """Space pressed -> ``jump_pending`` latches True, the next ``to_cmd`` sees
    it set on the wire.

    With the consume-once responsibility moved to the bridge (the engine
    fires jump on exactly one tick from a single ``SetState`` carrying
    ``jump=True``), ``to_cmd`` no longer drains the latch on its own.
    The producer in ``_run_drive`` clears ``jump_pending`` right after
    each emit so subsequent commands do not redundantly re-send the
    pulse — but ``to_cmd`` itself is a pure read.
    """
    state = _DriveState()
    _apply(state, " ")
    assert state.jump_pending is True
    first = state.to_cmd(2.0)
    assert first.jump is True
    # ``to_cmd`` does NOT mutate state any more: re-reading without an
    # external drain still observes the latch.
    assert state.jump_pending is True
    second = state.to_cmd(2.0)
    assert second.jump is True


def test_to_cmd_is_pure_read_no_mutation():
    """A second invariant check: ``to_cmd`` (default ``consume_jump=False``)
    must not mutate any field.

    The producer relies on the snapshot being side-effect-free by
    default so introspection call sites (debug status renderers, tests,
    etc.) cannot accidentally swallow a jump pulse.
    """
    state = _DriveState(
        move_y=1.0,
        move_x=-1.0,
        yaw_rate=0.5,
        pitch_rate=-0.5,
        sprint_on=True,
        crouch_on=True,
        jump_pending=True,
    )
    before = _DriveState(
        move_y=state.move_y,
        move_x=state.move_x,
        yaw_rate=state.yaw_rate,
        pitch_rate=state.pitch_rate,
        sprint_on=state.sprint_on,
        crouch_on=state.crouch_on,
        jump_pending=state.jump_pending,
    )
    state.to_cmd(2.0)
    assert state == before


def test_to_cmd_consume_jump_drains_pending_latch_only():
    """``consume_jump=True`` drains ``jump_pending`` (the single drain site
    used by the wire producer) and leaves every other field untouched."""
    state = _DriveState(
        move_y=1.0,
        move_x=-1.0,
        yaw_rate=0.5,
        pitch_rate=-0.5,
        sprint_on=True,
        crouch_on=True,
        jump_pending=True,
    )

    first = state.to_cmd(2.0, consume_jump=True)
    assert first.jump is True
    assert state.jump_pending is False
    # Non-jump axes survive the drain unchanged.
    assert state.move_y == 1.0
    assert state.move_x == -1.0
    assert state.sprint_on is True
    assert state.crouch_on is True

    # Second emit without an intervening Space sees jump=False.
    second = state.to_cmd(2.0, consume_jump=True)
    assert second.jump is False
    assert state.jump_pending is False


# ---------------------------------------------------------------------------
# Stop-all (x / 0)
# ---------------------------------------------------------------------------


def test_x_resets_all_axes_to_neutral():
    state = _DriveState(
        move_y=1.0,
        move_x=-1.0,
        yaw_rate=0.5,
        pitch_rate=-0.5,
        sprint_on=True,
        crouch_on=True,
        jump_pending=True,
    )
    _apply(state, "x")
    assert state == _DriveState()


def test_zero_resets_all_axes_to_neutral():
    state = _DriveState(move_y=1.0, sprint_on=True)
    _apply(state, "0")
    assert state == _DriveState()


# ---------------------------------------------------------------------------
# Exit (q) and no-op keys
# ---------------------------------------------------------------------------


def test_q_returns_true_to_signal_exit():
    state = _DriveState(move_y=1.0)
    assert _apply(state, "q") is True
    # State is not touched by the exit key — caller handles teardown.
    assert state.move_y == 1.0


# ---------------------------------------------------------------------------
# state_changed wake signal — the event-driven producer wakes on real changes
# ---------------------------------------------------------------------------


def test_state_changing_key_sets_wake_signal():
    """Recognised keys that mutate state must trip the wake event so the event-
    driven producer emits exactly one fresh command per change."""
    state = _DriveState()
    event = asyncio.Event()
    _apply_key(state, "w", 1.0, event)
    assert event.is_set()


def test_jump_key_sets_wake_signal():
    """Space is a state-altering key (sets jump_pending) and must wake."""
    state = _DriveState()
    event = asyncio.Event()
    _apply_key(state, " ", 1.0, event)
    assert event.is_set()


def test_unrecognised_key_does_not_set_wake_signal():
    """No-op keys must not wake the producer — otherwise every random keystroke
    would burn a wire message."""
    state = _DriveState()
    event = asyncio.Event()
    _apply_key(state, "?", 1.0, event)
    assert not event.is_set()


def test_quit_key_does_not_set_wake_signal():
    """``q`` returns the exit signal via the return value; the producer wake
    event is set separately by the stdin reader on the stop path."""
    state = _DriveState()
    event = asyncio.Event()
    assert _apply_key(state, "q", 1.0, event) is True
    assert not event.is_set()


def test_unrecognised_keys_are_noop():
    state = _DriveState(move_y=1.0)
    before = _DriveState(
        move_y=state.move_y,
        move_x=state.move_x,
        yaw_rate=state.yaw_rate,
        pitch_rate=state.pitch_rate,
        sprint_on=state.sprint_on,
        crouch_on=state.crouch_on,
        jump_pending=state.jump_pending,
    )
    for key in ("?", "z", "1", "Q"):
        assert _apply(state, key) is False
    assert state == before


# ---------------------------------------------------------------------------
# _KeyParser — ASCII + ANSI arrow escape sequences
# ---------------------------------------------------------------------------


def test_parser_passes_through_ascii_printables():
    parser = _KeyParser()
    assert parser.feed(ord("w")) == ["w"]
    assert parser.feed(ord("a")) == ["a"]
    assert parser.feed(ord(" ")) == [" "]


def test_parser_decodes_arrow_up():
    parser = _KeyParser()
    assert parser.feed(0x1B) == []
    assert parser.feed(ord("[")) == []
    assert parser.feed(ord("A")) == ["UP"]


def test_parser_decodes_each_arrow_direction():
    cases = {
        ord("A"): "UP",
        ord("B"): "DOWN",
        ord("C"): "RIGHT",
        ord("D"): "LEFT",
    }
    for terminator, expected in cases.items():
        parser = _KeyParser()
        parser.feed(0x1B)
        parser.feed(ord("["))
        assert parser.feed(terminator) == [expected]


def test_parser_drops_unknown_csi_terminator():
    parser = _KeyParser()
    parser.feed(0x1B)
    parser.feed(ord("["))
    # 'Z' is not an arrow — sequence is dropped silently.
    assert parser.feed(ord("Z")) == []
    # Parser is back in ground state and can decode normal keys after.
    assert parser.feed(ord("w")) == ["w"]


def test_parser_drops_esc_followed_by_non_bracket():
    parser = _KeyParser()
    parser.feed(0x1B)
    # 'X' aborts the ESC sequence (no '['); decoder returns to ground silently.
    assert parser.feed(ord("X")) == []
    assert parser.feed(ord("w")) == ["w"]


def test_parser_handles_back_to_back_inputs():
    parser = _KeyParser()
    assert parser.feed(ord("w")) == ["w"]
    assert parser.feed(ord("a")) == ["a"]
    # Then an arrow.
    assert parser.feed(0x1B) == []
    assert parser.feed(ord("[")) == []
    assert parser.feed(ord("B")) == ["DOWN"]
    # Then a printable again.
    assert parser.feed(ord("q")) == ["q"]


# ---------------------------------------------------------------------------
# _format_status — contains the major fields for regression purposes
# ---------------------------------------------------------------------------


def test_format_status_contains_key_field_labels():
    state = _DriveState(move_y=1.0, sprint_on=True)
    line = _format_status(state, 2.0)
    assert "move" in line
    assert "look" in line
    assert "velocity" in line
    assert "crouch" in line
    # No trailing newline or carriage return — caller handles framing.
    assert "\n" not in line
    assert "\r" not in line


def test_format_status_velocity_reflects_sprint_state():
    state = _DriveState()
    assert "velocity=1.00" in _format_status(state, 2.0)
    state.sprint_on = True
    assert "velocity=2.00" in _format_status(state, 2.0)


# ---------------------------------------------------------------------------
# argparse surface (subparser registration + validator + propagated flags)
# ---------------------------------------------------------------------------


def test_locomotion_without_subcommand_is_rejected():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["locomotion"])
    assert excinfo.value.code == 2


def test_drive_rejects_legacy_rate_flag():
    """``--rate`` was removed: the bridge is a stateful repeater, the
    CLI is event-driven, and a fixed tick rate no longer makes sense.

    argparse exits 2 on an unrecognised flag, matching the contract
    other regression tests rely on.
    """
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["locomotion", "drive", "--rate", "30"])
    assert excinfo.value.code == 2


def test_socket_flag_accepted_on_drive(tmp_path: Path):
    """`-s/--socket` must work on the leaf, mirroring `display`'s nesting."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    args = parser.parse_args(["locomotion", "drive", "-s", sock, "--no-wait"])
    assert args.socket == sock
    assert args.no_wait is True
    # Defaults for the optional knobs flow through. ``--rate`` is gone.
    assert not hasattr(args, "rate")
    assert args.sprint == 2.0
    # 90 deg/s ≈ Resonite's MouseLookSpeed default (100 deg/s); the
    # previous 30 deg/s tracked the keyboard preset which felt sluggish.
    assert args.look_rate == 90.0


# ---------------------------------------------------------------------------
# _raw_tty — restores tty state and tolerates non-tty fds
# ---------------------------------------------------------------------------


def test_raw_tty_enters_cbreak_mode_inside_block_on_real_pty():
    """Inside the context manager, the tty's termios state must differ from the
    entry state — that is the externally observable effect of cbreak mode
    (lflag's ICANON / ECHO bits cleared)."""
    master_fd, slave_fd = pty.openpty()
    try:
        stream = os.fdopen(slave_fd, "r+b", buffering=0)
        try:
            before = termios.tcgetattr(slave_fd)
            with _raw_tty(stream):  # type: ignore[arg-type]
                during = termios.tcgetattr(slave_fd)
            # cbreak clears ICANON + ECHO on lflag (index 3 in the
            # termios attribute list); assert observably different
            # without coupling the test to specific bit layouts.
            assert during != before, (
                "termios state inside _raw_tty must differ from the entry "
                "state (cbreak mode should be in effect)"
            )
        finally:
            stream.close()  # also closes slave_fd
    finally:
        os.close(master_fd)


def test_raw_tty_restores_original_state_on_normal_exit_on_real_pty():
    """The whole point of the context manager: termios state at exit
    must match the state at entry, observed directly on a real pty."""
    master_fd, slave_fd = pty.openpty()
    try:
        stream = os.fdopen(slave_fd, "r+b", buffering=0)
        try:
            before = termios.tcgetattr(slave_fd)
            with _raw_tty(stream):  # type: ignore[arg-type]
                pass
            after = termios.tcgetattr(slave_fd)
            assert after == before
        finally:
            stream.close()
    finally:
        os.close(master_fd)


def test_raw_tty_restores_original_state_when_body_raises_on_real_pty():
    """Restore must run on exception — otherwise an uncaught error in the drive
    loop would leave the user's terminal in cbreak mode."""
    master_fd, slave_fd = pty.openpty()
    try:
        stream = os.fdopen(slave_fd, "r+b", buffering=0)
        try:
            before = termios.tcgetattr(slave_fd)
            with pytest.raises(RuntimeError, match="boom"):
                with _raw_tty(stream):  # type: ignore[arg-type]
                    raise RuntimeError("boom")
            after = termios.tcgetattr(slave_fd)
            assert after == before
        finally:
            stream.close()
    finally:
        os.close(master_fd)


def test_raw_tty_is_noop_for_non_tty_fd():
    """Pipes are not tty fds; _raw_tty must yield cleanly without raising.

    Observed by the round-trip test driving stdin via a pipe.
    """
    r_fd, w_fd = os.pipe()
    try:
        stream = os.fdopen(r_fd, "rb", buffering=0)
        try:
            # No exception is the contract — there is no "tty state" to
            # observe on a pipe.
            with _raw_tty(stream):  # type: ignore[arg-type]
                pass
        finally:
            stream.close()
    finally:
        os.close(w_fd)


def test_raw_tty_is_noop_for_stream_without_fileno():
    """StringIO has no fd; _raw_tty must short-circuit and yield without
    raising rather than propagating an OSError."""
    with _raw_tty(io.StringIO()):
        pass


# ---------------------------------------------------------------------------
# End-to-end round-trip: argv -> _run_drive -> in-process LocomotionService
# ---------------------------------------------------------------------------


class _RecordingLocomotion(LocomotionBase):
    """In-process server that captures every command for assertion.

    ``reset`` is also implemented because ``_run_drive`` calls it on
    graceful exit (the bridge is stateful; ending the stream does not
    by itself neutralise the avatar). The reset stub echoes the
    request flags back as the summary so the CLI's post-drive reset
    succeeds without affecting the captured drive frames.
    """

    def __init__(self) -> None:
        self.received: list[LocomotionCommand] = []
        self.reset_requests: list[LocomotionResetRequest] = []
        # Counts how many distinct Drive RPCs the server has handled.
        # The default-path probe (_wait_for_bridge_ready) opens its own
        # short-lived stream, so the probe-vs-no-probe contrast is
        # directly observable here.
        self.drive_call_count: int = 0

    async def drive(
        self, messages: AsyncIterator[LocomotionCommand]
    ) -> LocomotionDriveSummary:
        self.drive_call_count += 1
        async for msg in messages:
            self.received.append(msg)
        return LocomotionDriveSummary(
            received_count=len(self.received),
            dropped_count=0,
            unix_nanos=time.time_ns(),
        )

    async def reset(self, message: LocomotionResetRequest) -> LocomotionResetSummary:
        self.reset_requests.append(message)
        # Echo wire flags verbatim. The "all-false → full reset" service
        # expansion is covered by the C# Core tests; this stub stays
        # minimal so CLI tests assert only the proto-wire shape.
        return LocomotionResetSummary(
            move=message.move,
            look=message.look,
            crouch=message.crouch,
            jump=message.jump,
            unix_nanos=time.time_ns(),
        )


async def test_drive_round_trip_via_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """End-to-end: argv -> Drive RPC -> server -> stdout summary.

    Drives the full pipeline: argparse + ``_run_drive`` + ``LocomotionClient``
    + an in-process server. ``os.pipe()`` feeds the canned key sequence so
    no real tty is needed; ``_raw_tty`` no-ops on the pipe fd, which is
    the same shape SSH-piped invocations end up using.
    """
    socket_path = tmp_path / "rio-loco.sock"
    fake = _RecordingLocomotion()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))

        read_fd, write_fd = os.pipe()
        try:
            fake_stdin = os.fdopen(read_fd, "rb", buffering=0)
            monkeypatch.setattr("sys.stdin", fake_stdin)

            # Key sequence (sent paced so the stdin reader does not
            # drain the whole buffer in one callback and race ahead of
            # the event-driven producer — in particular, `q` must
            # arrive after the producer has had a chance to emit the
            # earlier state changes, otherwise the stop event trips
            # before they reach the wire):
            #   w           : forward                       -> move_y = +1
            #   t           : sprint on                     -> velocity = 2.0
            #   space       : jump pulse (one tick only)    -> jump = True once
            #   ESC [ A     : look up                       -> pitch_rate = +1.0
            #   x           : stop all                      -> neutral
            #   q           : exit, drive RPC summary       -> received_count > 0
            async def feed_keys() -> None:
                key_chunks = [b"w", b"t", b" ", b"\x1b[A", b"x", b"q"]
                # Give the drive loop time to start and emit the
                # initial neutral command before the first keypress.
                await asyncio.sleep(0.05)
                for chunk in key_chunks:
                    os.write(write_fd, chunk)
                    # 50 ms between keystrokes is generous enough for
                    # the event loop to wake `commands()`, emit, and
                    # block again under CI jitter.
                    await asyncio.sleep(0.05)

            try:
                args = _build_parser().parse_args(
                    [
                        "locomotion",
                        "drive",
                        "--no-wait",
                        "--sprint",
                        "2.0",
                        "--look-rate",
                        "1.0",
                    ]
                )
                feeder = asyncio.create_task(feed_keys())
                try:
                    rc = await asyncio.wait_for(_amain(args), timeout=5.0)
                finally:
                    feeder.cancel()
                    try:
                        await feeder
                    except (asyncio.CancelledError, OSError):
                        pass
                assert rc == 0
            finally:
                fake_stdin.close()  # closes read_fd
        finally:
            # write_fd is owned here regardless of feeder progress.
            try:
                os.close(write_fd)
            except OSError:
                pass
    finally:
        server.close()
        await server.wait_closed()

    # At least the initial neutral + the four state-changing keys produced
    # ticks before `q` was processed. Exact count is loop-pacing dependent.
    assert len(fake.received) >= 4, (
        f"expected several ticks before exit, got {len(fake.received)}"
    )

    # Forward toggle landed at some tick.
    assert any(c.move_y == 1.0 for c in fake.received), (
        "no command had move_y=1.0 after `w` keypress"
    )
    # Sprint toggle: at some point move_y=+1 with velocity=2.0.
    assert any(c.move_y == 1.0 and c.velocity == 2.0 for c in fake.received), (
        "no command had velocity=2.0 after `t` keypress"
    )
    # Jump pulse: exactly one tick carries jump=True.
    jump_count = sum(1 for c in fake.received if c.jump)
    assert jump_count == 1, f"jump pulse should fire exactly once, got {jump_count}"
    # Look up: at some point pitch_rate=+1.0.
    assert any(c.pitch_rate == 1.0 for c in fake.received), (
        "no command had pitch_rate=+1.0 after UP arrow keypress"
    )
    # Last command was emitted after `x` (stop-all) and before `q` (exit),
    # so it must be neutral.
    last = fake.received[-1]
    assert last.move_x == 0.0
    assert last.move_y == 0.0
    assert last.yaw_rate == 0.0
    assert last.pitch_rate == 0.0
    assert last.jump is False
    assert last.crouch == 0.0
    # reset() also clears sprint_on, so neutral velocity is 1.0.
    assert last.velocity == 1.0

    # Graceful exit (q) must trigger an explicit Locomotion.reset RPC so
    # the bridge does not keep the last state alive forever.
    assert len(fake.reset_requests) == 1
    reset_req = fake.reset_requests[0]
    # All-false request shape is the "reset everything" signal per
    # LocomotionClient.reset() contract.
    assert reset_req.move is False
    assert reset_req.look is False
    assert reset_req.crouch is False
    assert reset_req.jump is False

    captured = capsys.readouterr()
    # Drive summary lands on stdout, formatted for grep / scripting.
    assert "received_count=" in captured.out
    assert f"received_count={len(fake.received)}" in captured.out


async def _run_drive_with_immediate_quit(
    socket_path: Path,
    *,
    no_wait: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    """Shared driver: hook stdin to a pipe pre-loaded with ``q`` and let
    ``_run_drive`` exit on the first key. Used by the contrast pair
    below to observe whether the bridge-readiness probe ran."""
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"q")
        fake_stdin = os.fdopen(read_fd, "rb", buffering=0)
        monkeypatch.setattr("sys.stdin", fake_stdin)
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        argv = ["locomotion", "drive"]
        if no_wait:
            argv.append("--no-wait")
        try:
            args = _build_parser().parse_args(argv)
            return await asyncio.wait_for(_run_drive(args), timeout=5.0)
        finally:
            fake_stdin.close()
    finally:
        try:
            os.close(write_fd)
        except OSError:
            pass


async def test_no_wait_skips_neutral_probe_on_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """`--no-wait` must short-circuit ``_wait_for_bridge_ready``. The probe
    opens its own Drive stream and sends one neutral command; skipping it means
    the server sees exactly **one** Drive RPC — the main drive loop that
    immediately exits on the queued ``q``.

    Paired with ``test_default_path_sends_neutral_probe_on_wire`` to
    show the behaviour differs only by the presence of the probe.
    """
    socket_path = tmp_path / "rio-loco.sock"
    fake = _RecordingLocomotion()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_drive_with_immediate_quit(
            socket_path, no_wait=True, monkeypatch=monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    # Only the main drive stream ran — no probe stream preceded it.
    assert fake.drive_call_count == 1, (
        f"--no-wait should suppress the readiness probe; got "
        f"{fake.drive_call_count} Drive RPCs"
    )


async def test_default_path_sends_neutral_probe_on_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Without ``--no-wait``, ``_run_drive`` invokes ``_wait_for_bridge_ready``
    which opens a short-lived Drive stream and sends one neutral
    ``LocomotionCommand`` before the main drive loop. The server therefore
    observes **two** Drive RPCs: the probe, then the main loop.

    The contrast against ``test_no_wait_skips_neutral_probe_on_wire``
    pins the externally observable contract of the ``--no-wait`` flag
    without resorting to mocking the internal helper.
    """
    socket_path = tmp_path / "rio-loco.sock"
    fake = _RecordingLocomotion()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_drive_with_immediate_quit(
            socket_path, no_wait=False, monkeypatch=monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    # Probe stream + main drive stream = 2 RPCs.
    assert fake.drive_call_count == 2, (
        f"default path should send a neutral readiness probe before the "
        f"main drive stream; got {fake.drive_call_count} Drive RPCs"
    )
    # The neutral probe is the first command on the wire: all motion
    # axes at 0 and jump cleared. ``velocity`` rides ``LocomotionCmd``'s
    # 1.0 default (the wrapper documents why — bridge multiplies Move
    # by velocity, so 0 would freeze the avatar on the next real cmd).
    # That default is part of the public contract, not noise — pin it
    # explicitly so a default-flip would surface here.
    assert len(fake.received) >= 1
    probe = fake.received[0]
    assert probe.move_x == 0.0
    assert probe.move_y == 0.0
    assert probe.yaw_rate == 0.0
    assert probe.pitch_rate == 0.0
    assert probe.velocity == 1.0
    assert probe.crouch == 0.0
    assert probe.jump is False


async def test_wait_for_bridge_ready_returns_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A bridge that accepts the neutral probe must let the wait return."""
    socket_path = tmp_path / "rio-loco.sock"
    fake = _RecordingLocomotion()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        # Bridge is happy: returns from the first attempt immediately.
        await asyncio.wait_for(
            _wait_for_bridge_ready(None, timeout_s=2.0, interval_s=0.05),
            timeout=2.0,
        )
        # One neutral probe was sent and recorded.
        assert len(fake.received) == 1
        assert fake.received[0].move_y == 0.0
    finally:
        server.close()
        await server.wait_closed()
