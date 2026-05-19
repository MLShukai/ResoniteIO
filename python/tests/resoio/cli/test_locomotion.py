import asyncio
import io
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_mock
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    LocomotionBase,
    LocomotionCommand,
    LocomotionDriveSummary,
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

# ---------------------------------------------------------------------------
# Move toggles (w/s, a/d)
# ---------------------------------------------------------------------------


def test_w_toggles_move_y_forward_and_back_to_neutral():
    state = _DriveState()
    assert _apply_key(state, "w", 1.0, 2.0) is False
    assert state.move_y == 1.0
    assert _apply_key(state, "w", 1.0, 2.0) is False
    assert state.move_y == 0.0


def test_s_cancels_held_w_then_flips_negative():
    state = _DriveState(move_y=1.0)
    assert _apply_key(state, "s", 1.0, 2.0) is False
    assert state.move_y == 0.0  # exclusive cancel
    assert _apply_key(state, "s", 1.0, 2.0) is False
    assert state.move_y == -1.0


def test_a_and_d_are_exclusive_on_move_x():
    state = _DriveState()
    _apply_key(state, "d", 1.0, 2.0)
    assert state.move_x == 1.0
    _apply_key(state, "a", 1.0, 2.0)
    assert state.move_x == 0.0  # d cancelled by a
    _apply_key(state, "a", 1.0, 2.0)
    assert state.move_x == -1.0


# ---------------------------------------------------------------------------
# Look toggles (UP/DOWN, LEFT/RIGHT)
# ---------------------------------------------------------------------------


def test_up_toggles_pitch_at_look_rate():
    state = _DriveState()
    _apply_key(state, "UP", 0.5, 2.0)
    assert state.pitch_rate == 0.5
    _apply_key(state, "UP", 0.5, 2.0)
    assert state.pitch_rate == 0.0


def test_down_cancels_up_then_flips_negative():
    state = _DriveState(pitch_rate=0.5)
    _apply_key(state, "DOWN", 0.5, 2.0)
    assert state.pitch_rate == 0.0
    _apply_key(state, "DOWN", 0.5, 2.0)
    assert state.pitch_rate == -0.5


def test_left_and_right_are_exclusive_on_yaw():
    state = _DriveState()
    _apply_key(state, "RIGHT", 0.5, 2.0)
    assert state.yaw_rate == 0.5
    _apply_key(state, "LEFT", 0.5, 2.0)
    assert state.yaw_rate == 0.0  # right cancelled by left
    _apply_key(state, "LEFT", 0.5, 2.0)
    assert state.yaw_rate == -0.5


# ---------------------------------------------------------------------------
# Sprint (t) and the velocity field on to_cmd()
# ---------------------------------------------------------------------------


def test_t_toggles_sprint_flag():
    state = _DriveState()
    _apply_key(state, "t", 1.0, 2.0)
    assert state.sprint_on is True
    _apply_key(state, "t", 1.0, 2.0)
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
    _apply_key(state, "c", 1.0, 2.0)
    assert state.crouch_on is True
    assert state.to_cmd(2.0).crouch == 1.0
    _apply_key(state, "c", 1.0, 2.0)
    assert state.crouch_on is False
    assert state.to_cmd(2.0).crouch == 0.0


# ---------------------------------------------------------------------------
# Jump pulse (Space) — drained after one to_cmd()
# ---------------------------------------------------------------------------


def test_space_emits_jump_on_next_cmd_then_drains():
    state = _DriveState()
    _apply_key(state, " ", 1.0, 2.0)
    assert state.jump_pending is True
    first = state.to_cmd(2.0)
    assert first.jump is True
    # Drained — a follow-up tick with no new input must emit jump=False.
    second = state.to_cmd(2.0)
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
    _apply_key(state, "x", 1.0, 2.0)
    assert state == _DriveState()


def test_zero_resets_all_axes_to_neutral():
    state = _DriveState(move_y=1.0, sprint_on=True)
    _apply_key(state, "0", 1.0, 2.0)
    assert state == _DriveState()


# ---------------------------------------------------------------------------
# Exit (q) and no-op keys
# ---------------------------------------------------------------------------


def test_q_returns_true_to_signal_exit():
    state = _DriveState(move_y=1.0)
    assert _apply_key(state, "q", 1.0, 2.0) is True
    # State is not touched by the exit key — caller handles teardown.
    assert state.move_y == 1.0


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
        assert _apply_key(state, key, 1.0, 2.0) is False
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


def test_drive_rejects_non_positive_rate():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["locomotion", "drive", "--rate", "0"])
    # argparse exits 2 when a type/value validator raises ArgumentTypeError.
    assert excinfo.value.code == 2


def test_drive_rejects_negative_rate():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["locomotion", "drive", "--rate", "-1"])
    assert excinfo.value.code == 2


def test_socket_flag_accepted_on_drive(tmp_path: Path):
    """`-s/--socket` must work on the leaf, mirroring `display`'s nesting."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    args = parser.parse_args(["locomotion", "drive", "-s", sock, "--no-wait"])
    assert args.socket == sock
    assert args.no_wait is True
    # Defaults for the optional knobs flow through.
    assert args.rate == 30.0
    assert args.sprint == 2.0
    assert args.look_rate == 1.0


# ---------------------------------------------------------------------------
# _raw_tty — restores tty state and tolerates non-tty fds
# ---------------------------------------------------------------------------


def test_raw_tty_restores_original_state_on_exit(mocker: pytest_mock.MockerFixture):
    fake_stream: Any = mocker.Mock()
    fake_stream.fileno.return_value = 7
    mocker.patch("resoio.cli.locomotion.os.isatty", return_value=True)
    original_state = mocker.sentinel.original
    tcgetattr = mocker.patch(
        "resoio.cli.locomotion.termios.tcgetattr", return_value=original_state
    )
    tcsetattr = mocker.patch("resoio.cli.locomotion.termios.tcsetattr")
    setcbreak = mocker.patch("resoio.cli.locomotion.tty.setcbreak")

    with _raw_tty(fake_stream):
        pass

    tcgetattr.assert_called_once_with(7)
    setcbreak.assert_called_once_with(7)
    # The whole point of the context manager is this exact restore call.
    tcsetattr.assert_called_once()
    fd_arg, when_arg, state_arg = tcsetattr.call_args.args
    assert fd_arg == 7
    # termios.TCSADRAIN is an int; assert by value via the module reference
    # to keep the test platform-agnostic.
    import termios as _termios

    assert when_arg == _termios.TCSADRAIN
    assert state_arg is original_state


def test_raw_tty_restores_even_when_body_raises(mocker: pytest_mock.MockerFixture):
    fake_stream: Any = mocker.Mock()
    fake_stream.fileno.return_value = 9
    mocker.patch("resoio.cli.locomotion.os.isatty", return_value=True)
    original_state = mocker.sentinel.original
    mocker.patch("resoio.cli.locomotion.termios.tcgetattr", return_value=original_state)
    tcsetattr = mocker.patch("resoio.cli.locomotion.termios.tcsetattr")
    mocker.patch("resoio.cli.locomotion.tty.setcbreak")

    with pytest.raises(RuntimeError, match="boom"):
        with _raw_tty(fake_stream):
            raise RuntimeError("boom")

    tcsetattr.assert_called_once()
    assert tcsetattr.call_args.args[2] is original_state


def test_raw_tty_is_noop_for_non_tty_fd(mocker: pytest_mock.MockerFixture):
    """Pipes and files must not crash _raw_tty — used by the round-trip
    test."""
    r_fd, w_fd = os.pipe()
    try:
        stream = os.fdopen(r_fd, "rb", buffering=0)
        tcgetattr = mocker.patch("resoio.cli.locomotion.termios.tcgetattr")
        tcsetattr = mocker.patch("resoio.cli.locomotion.termios.tcsetattr")
        try:
            with _raw_tty(stream):  # type: ignore[arg-type]
                pass
        finally:
            stream.close()
        tcgetattr.assert_not_called()
        tcsetattr.assert_not_called()
    finally:
        # stream.close() already closes r_fd; w_fd we own.
        os.close(w_fd)


def test_raw_tty_is_noop_for_stream_without_fileno(mocker: pytest_mock.MockerFixture):
    """StringIO-style streams report no fd and must short-circuit cleanly."""
    tcgetattr = mocker.patch("resoio.cli.locomotion.termios.tcgetattr")
    tcsetattr = mocker.patch("resoio.cli.locomotion.termios.tcsetattr")
    with _raw_tty(io.StringIO()):
        pass
    tcgetattr.assert_not_called()
    tcsetattr.assert_not_called()


# ---------------------------------------------------------------------------
# End-to-end round-trip: argv -> _run_drive -> in-process LocomotionService
# ---------------------------------------------------------------------------


class _RecordingLocomotion(LocomotionBase):
    """In-process server that captures every command for assertion."""

    def __init__(self) -> None:
        self.received: list[LocomotionCommand] = []

    async def drive(
        self, messages: AsyncIterator[LocomotionCommand]
    ) -> LocomotionDriveSummary:
        async for msg in messages:
            self.received.append(msg)
        return LocomotionDriveSummary(
            received_count=len(self.received),
            dropped_count=0,
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

            # Key sequence (sent paced so each key falls on a distinct
            # tick — otherwise the reader drains them all atomically and
            # `q` would exit before any command is yielded):
            #   w           : forward                       -> move_y = +1
            #   t           : sprint on                     -> velocity = 2.0
            #   space       : jump pulse (one tick only)    -> jump = True once
            #   ESC [ A     : look up                       -> pitch_rate = +1.0
            #   x           : stop all                      -> neutral
            #   q           : exit, drive RPC summary       -> received_count > 0
            async def feed_keys() -> None:
                key_chunks = [b"w", b"t", b" ", b"\x1b[A", b"x", b"q"]
                # Give the drive loop time to start and emit at least one
                # tick before the first keypress arrives.
                await asyncio.sleep(0.05)
                for chunk in key_chunks:
                    os.write(write_fd, chunk)
                    # Two periods at --rate 200 (5 ms / tick) keeps each
                    # keypress on its own tick reliably under CI jitter.
                    await asyncio.sleep(0.05)

            try:
                args = _build_parser().parse_args(
                    [
                        "locomotion",
                        "drive",
                        "--rate",
                        "200",
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
    # velocity is unchanged by `x` semantics by design? No — reset() also
    # clears sprint_on, so neutral velocity must be 1.0.
    assert last.velocity == 1.0

    captured = capsys.readouterr()
    # Drive summary lands on stdout, formatted for grep / scripting.
    assert "received_count=" in captured.out
    assert f"received_count={len(fake.received)}" in captured.out


async def test_no_wait_skips_bridge_ready_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """`--no-wait` must short-circuit the FAILED_PRECONDITION retry loop."""
    socket_path = tmp_path / "rio-loco.sock"
    fake = _RecordingLocomotion()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        wait_mock = mocker.patch(
            "resoio.cli.locomotion._wait_for_bridge_ready",
        )

        read_fd, write_fd = os.pipe()
        try:
            # `q` immediately so the run is short.
            os.write(write_fd, b"q")
            fake_stdin = os.fdopen(read_fd, "rb", buffering=0)
            monkeypatch.setattr("sys.stdin", fake_stdin)
            try:
                args = _build_parser().parse_args(
                    ["locomotion", "drive", "--rate", "200", "--no-wait"]
                )
                rc = await asyncio.wait_for(_run_drive(args), timeout=5.0)
                assert rc == 0
            finally:
                fake_stdin.close()
        finally:
            try:
                os.close(write_fd)
            except OSError:
                pass
        wait_mock.assert_not_called()
    finally:
        server.close()
        await server.wait_closed()


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
