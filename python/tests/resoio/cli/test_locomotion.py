from resoio.cli.locomotion import (
    _apply_key,
    _DriveState,
    _format_status,
    _KeyParser,
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
