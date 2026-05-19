"""``resoio locomotion drive`` subcommand: interactive WASD drive.

Phase 1A: only the pure logic layer (``_DriveState`` / ``_KeyParser`` /
``_apply_key`` / ``_format_status``). The async runtime, raw-tty
context manager, Bridge-ready retry, and subcommand registration are
added in a follow-up commit; until then this module is not wired into
:data:`resoio.cli._COMMAND_MODULES`, so the CLI cannot reach it.
"""

from __future__ import annotations

from dataclasses import dataclass

from resoio.locomotion import LocomotionCmd

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
