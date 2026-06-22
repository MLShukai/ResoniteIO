"""CLI tests for ``resoio grabber`` (renamed from ``resoio grab``).

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`GrabberBase` over a real UDS (no mocking of
grpclib/betterproto2). Each test asserts that the chosen subaction invokes
the correct RPC with the correct ``hand`` (and ``radius`` for ``grab`` —
grab always targets the desktop cursor-ray hit point, there is no
``--point``) and that key result fields are printed.

Contract under test (CLI restructure spec):

* the action positional is **required** — bare ``resoio grabber`` errors
  with the argparse usage code (the old implicit-``grab`` default is gone)
* ``resoio grabber grab`` / ``release`` / ``state`` / ``interactive`` select
  the action explicitly
* ``--hand`` / ``--radius`` / ``-s/--socket`` are accepted both before and
  after the subaction
* an unknown subaction exits with the argparse usage code (2)
* output format and RPC semantics are unchanged from ``resoio grab``

The interactive raw-tty loop is out of scope (hard to drive
deterministically) and is not exercised here.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    GrabberBase,
    GrabberButton,
    GrabberDequipRequest,
    GrabberEquipRequest,
    GrabberGetStateRequest,
    GrabberGrabRequest,
    GrabberGrabResult as PbGrabberGrabResult,
    GrabberGrabState as PbGrabberGrabState,
    GrabberHand,
    GrabberReleaseRequest,
    GrabberUnuseRequest,
    GrabberUseRequest,
)
from resoio.cli import _amain, _build_parser

# Exactly representable in float32 so the printed values are stable across
# the proto round-trip.
_RADIUS = 0.5

_ARGPARSE_USAGE_EXIT_CODE = 2


class _EchoGrabber(GrabberBase):
    """In-process fake recording each request and echoing it into the reply."""

    def __init__(self) -> None:
        self.grab_requests: list[GrabberGrabRequest] = []
        self.release_requests: list[GrabberReleaseRequest] = []
        self.get_state_requests: list[GrabberGetStateRequest] = []
        self.use_requests: list[GrabberUseRequest] = []
        self.unuse_requests: list[GrabberUnuseRequest] = []
        self.equip_requests: list[GrabberEquipRequest] = []
        self.dequip_requests: list[GrabberDequipRequest] = []

    async def grab(self, message: GrabberGrabRequest) -> PbGrabberGrabResult:
        self.grab_requests.append(message)
        return PbGrabberGrabResult(
            grabbed=True,
            state=PbGrabberGrabState(
                hand=message.hand,
                is_holding=True,
                object_names=["Cube"],
                unix_nanos=1234,
            ),
        )

    async def release(self, message: GrabberReleaseRequest) -> PbGrabberGrabState:
        self.release_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=False,
            object_names=[],
            unix_nanos=5678,
        )

    async def get_state(self, message: GrabberGetStateRequest) -> PbGrabberGrabState:
        self.get_state_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=True,
            object_names=["Cube", "Sphere"],
            unix_nanos=9012,
        )

    async def use(self, message: GrabberUseRequest) -> PbGrabberGrabState:
        self.use_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=True,
            object_names=["Cube"],
            unix_nanos=2468,
            held_buttons=[message.button],
        )

    async def unuse(self, message: GrabberUnuseRequest) -> PbGrabberGrabState:
        self.unuse_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=True,
            object_names=["Cube"],
            unix_nanos=1357,
            held_buttons=[],
        )

    async def equip(self, message: GrabberEquipRequest) -> PbGrabberGrabState:
        self.equip_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=False,
            object_names=[],
            unix_nanos=3690,
            is_tool_equipped=True,
            equipped_tool_name="Pen",
        )

    async def dequip(self, message: GrabberDequipRequest) -> PbGrabberGrabState:
        self.dequip_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=False,
            object_names=[],
            unix_nanos=4812,
            is_tool_equipped=False,
            equipped_tool_name="",
        )


@pytest.fixture
async def grabber_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[_EchoGrabber]:
    """Real grpclib server on a real UDS, exported via RESONITE_IO_SOCKET."""
    socket_path = tmp_path / "rio-grabber.sock"
    fake = _EchoGrabber()
    server = Server([fake])
    await server.start(path=str(socket_path))
    monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
    try:
        yield fake
    finally:
        server.close()
        await server.wait_closed()


async def _invoke(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    return await _amain(args)


# --- action is required (no implicit-grab default) ------------------------


def test_no_action_exits_with_usage_code():
    """The action positional is required: bare ``resoio grabber`` errors.

    Removing the old implicit-``grab`` default is a breaking change, so the
    parser must reject a missing action with the argparse usage code (2)
    rather than silently grabbing.
    """
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["grabber"])
    assert excinfo.value.code == _ARGPARSE_USAGE_EXIT_CODE


async def test_grab_subaction_performs_grab(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "grab"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    # grab must not release or read state.
    assert grabber_server.release_requests == []
    assert grabber_server.get_state_requests == []

    out = capsys.readouterr().out
    assert "True" in out  # grabbed / is_holding
    assert "Cube" in out


async def test_grab_defaults_to_primary_hand_and_zero_radius(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grabber", "grab"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    # No --hand given -> default primary.
    assert grabber_server.grab_requests[0].hand == GrabberHand.PRIMARY
    # No --radius given -> 0.0 travels verbatim; resolving <=0 to the
    # server default (0.1m) is a C#-Core concern.
    assert grabber_server.grab_requests[0].radius == 0.0


# --- flag placement: before or after the subaction -------------------------


async def test_grab_flags_after_subaction_forward_hand_and_radius(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grabber", "grab", "--radius", "0.5", "--hand", "left"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    wire = grabber_server.grab_requests[0]
    assert wire.hand == GrabberHand.LEFT
    assert wire.radius == _RADIUS


async def test_grab_flags_before_subaction_forward_hand_and_radius(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grabber", "--radius", "0.5", "--hand", "left", "grab"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    wire = grabber_server.grab_requests[0]
    assert wire.hand == GrabberHand.LEFT
    assert wire.radius == _RADIUS


async def test_release_accepts_hand_flag_before_subaction(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grabber", "--hand", "left", "release"])
    assert rc == 0

    assert len(grabber_server.release_requests) == 1
    assert grabber_server.release_requests[0].hand == GrabberHand.LEFT
    assert grabber_server.grab_requests == []


# --- release / state semantics ---------------------------------------------


async def test_release_invokes_release_rpc_with_hand(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "release", "--hand", "right"])
    assert rc == 0

    assert len(grabber_server.release_requests) == 1
    assert grabber_server.release_requests[0].hand == GrabberHand.RIGHT
    # release must not grab or read state.
    assert grabber_server.grab_requests == []
    assert grabber_server.get_state_requests == []

    out = capsys.readouterr().out
    assert "False" in out  # is_holding=False after release


async def test_state_invokes_get_state_rpc(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "state"])
    assert rc == 0

    assert len(grabber_server.get_state_requests) == 1
    assert grabber_server.get_state_requests[0].hand == GrabberHand.PRIMARY
    # state must be read-only.
    assert grabber_server.grab_requests == []
    assert grabber_server.release_requests == []

    out = capsys.readouterr().out
    assert "Cube" in out
    assert "Sphere" in out


# --- socket flag placement --------------------------------------------------


async def test_socket_flag_after_subaction_routes_to_get_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """``-s SOCK`` is the sole socket route (env var would mask intent)."""
    socket_path = tmp_path / "rio-grabber.sock"
    fake = _EchoGrabber()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        rc = await _invoke(["grabber", "state", "-s", str(socket_path)])
        assert rc == 0
        assert len(fake.get_state_requests) == 1
    finally:
        server.close()
        await server.wait_closed()


async def test_socket_flag_before_subaction_routes_to_get_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    socket_path = tmp_path / "rio-grabber.sock"
    fake = _EchoGrabber()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        rc = await _invoke(["grabber", "-s", str(socket_path), "state"])
        assert rc == 0
        assert len(fake.get_state_requests) == 1
    finally:
        server.close()
        await server.wait_closed()


# --- error handling / contract pins -----------------------------------------


def test_unknown_subaction_exits_with_usage_code():
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["grabber", "bogus"])
    assert excinfo.value.code == _ARGPARSE_USAGE_EXIT_CODE


@pytest.mark.api_contract
def test_retired_top_level_command_names_are_rejected():
    """Contract pin, not a behaviour test: the top-level command was renamed
    ``manipulate`` -> ``grab`` -> ``grabber`` (CLI restructure, breaking).

    argparse must reject the retired top-level names so a rename cannot
    silently regress into an alias. ``grab`` survives only as the positional
    *action* under ``grabber`` (``resoio grabber grab``), never as a command.
    """
    for retired in ("manipulate", "grab"):
        with pytest.raises(SystemExit) as excinfo:
            _build_parser().parse_args([retired, "grab"])
        assert excinfo.value.code == _ARGPARSE_USAGE_EXIT_CODE


@pytest.mark.api_contract
def test_grab_rejects_removed_point_flag():
    """Contract pin, not a behaviour test: ``--point`` was removed when grab
    became cursor-ray based (breaking).

    argparse must reject it with
    ``SystemExit`` — this detects a silent reintroduction of the flag.
    """
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["grabber", "grab", "--point", "1", "2", "3"])


# --- --format json --------------------------------------------------------
#
# ``--format json`` emits a single machine-readable document on stdout.
# ``grabber grab`` flattens GrabResult + GrabState into one object; ``grabber
# release`` / ``grabber state`` emit the GrabState shape directly. ``hand`` is
# the resolved string label ("primary"/"left"/"right"), object_names is an
# array, and unix_nanos round-trips as an exact integer.


def _sole_json_document(out: str) -> object:
    """Parse ``out`` as exactly one JSON document and return it.

    Pins the "stdout holds exactly ONE json document" contract: the
    captured output must decode as a single top-level value with nothing
    but trailing whitespace after it.
    """
    decoded, end = json.JSONDecoder().raw_decode(out)
    assert out[end:].strip() == ""
    return decoded


async def test_grab_json_flattens_result_and_state_into_one_object(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "grab", "--format", "json"])
    assert rc == 0

    payload = _sole_json_document(capsys.readouterr().out)
    # GrabResult + GrabState flattened; default hand resolves to "primary".
    assert payload == {
        "grabbed": True,
        "hand": "primary",
        "is_holding": True,
        "object_names": ["Cube"],
        "is_tool_equipped": False,
        "equipped_tool_name": "",
        "held_buttons": [],
        "unix_nanos": 1234,
    }


async def test_grab_json_reports_requested_hand_label(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "grab", "--hand", "left", "--format", "json"])
    assert rc == 0

    payload = _sole_json_document(capsys.readouterr().out)
    assert isinstance(payload, dict)
    # The hand echoed by the server surfaces as its string label, not an int.
    assert payload["hand"] == "left"


async def test_grab_release_json_emits_grab_state_shape(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "release", "--hand", "right", "--format", "json"])
    assert rc == 0

    payload = _sole_json_document(capsys.readouterr().out)
    assert payload == {
        "hand": "right",
        "is_holding": False,
        "object_names": [],
        "unix_nanos": 5678,
        "is_tool_equipped": False,
        "equipped_tool_name": "",
        "held_buttons": [],
    }


async def test_grab_state_json_emits_grab_state_shape(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "state", "--format", "json"])
    assert rc == 0

    payload = _sole_json_document(capsys.readouterr().out)
    assert payload == {
        "hand": "primary",
        "is_holding": True,
        "object_names": ["Cube", "Sphere"],
        "unix_nanos": 9012,
        "is_tool_equipped": False,
        "equipped_tool_name": "",
        "held_buttons": [],
    }


# --- use / unuse / click / equip / dequip ----------------------------------


async def test_use_invokes_use_rpc_with_hand_and_default_primary_button(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "use", "--hand", "left"])
    assert rc == 0

    assert len(grabber_server.use_requests) == 1
    wire = grabber_server.use_requests[0]
    assert wire.hand == GrabberHand.LEFT
    # No --button -> default primary (left-click).
    assert wire.button == GrabberButton.PRIMARY
    # use must not grab / release / read state.
    assert grabber_server.grab_requests == []
    assert grabber_server.unuse_requests == []

    out = capsys.readouterr().out
    assert "held=[primary]" in out


async def test_use_forwards_secondary_button(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grabber", "use", "--button", "secondary", "--hand", "right"])
    assert rc == 0

    assert len(grabber_server.use_requests) == 1
    wire = grabber_server.use_requests[0]
    assert wire.hand == GrabberHand.RIGHT
    assert wire.button == GrabberButton.SECONDARY


async def test_unuse_invokes_unuse_rpc_with_button(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grabber", "unuse", "--button", "secondary"])
    assert rc == 0

    assert len(grabber_server.unuse_requests) == 1
    assert grabber_server.unuse_requests[0].button == GrabberButton.SECONDARY
    assert grabber_server.use_requests == []


async def test_use_default_strength_is_one(
    grabber_server: _EchoGrabber,
):
    # Spec FR-6: omitting --strength forwards the default 1.0 press strength.
    rc = await _invoke(["grabber", "use"])
    assert rc == 0

    assert len(grabber_server.use_requests) == 1
    assert grabber_server.use_requests[0].strength == 1.0


async def test_use_forwards_strength_flag(
    grabber_server: _EchoGrabber,
):
    # Spec FR-6: --strength on the use action reaches the wire as a float.
    rc = await _invoke(["grabber", "use", "--strength", "0.3"])
    assert rc == 0

    assert len(grabber_server.use_requests) == 1
    assert grabber_server.use_requests[0].strength == pytest.approx(0.3)


async def test_click_forwards_strength_flag(
    grabber_server: _EchoGrabber,
):
    # Spec FR-6: --strength applies to the click action too (forwarded to use).
    rc = await _invoke(["grabber", "click", "--strength", "0.3"])
    assert rc == 0

    assert len(grabber_server.use_requests) == 1
    assert grabber_server.use_requests[0].strength == pytest.approx(0.3)


async def test_invalid_strength_exits_with_usage_code():
    # Spec FR-6 / §10.3: a non-numeric --strength is rejected by argparse's
    # float type with the standard usage exit code (2); the CLI adds no custom
    # handling.
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["grabber", "use", "--strength", "abc"])
    assert excinfo.value.code == _ARGPARSE_USAGE_EXIT_CODE


async def test_click_invokes_use_then_unuse(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grabber", "click", "--hand", "left", "--button", "secondary"])
    assert rc == 0

    # click is a convenience: use (press) then unuse (release), same hand+button.
    assert len(grabber_server.use_requests) == 1
    assert len(grabber_server.unuse_requests) == 1
    assert grabber_server.use_requests[0].hand == GrabberHand.LEFT
    assert grabber_server.use_requests[0].button == GrabberButton.SECONDARY
    assert grabber_server.unuse_requests[0].hand == GrabberHand.LEFT
    assert grabber_server.unuse_requests[0].button == GrabberButton.SECONDARY


async def test_equip_invokes_equip_rpc_with_hand(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "equip", "--hand", "right"])
    assert rc == 0

    assert len(grabber_server.equip_requests) == 1
    assert grabber_server.equip_requests[0].hand == GrabberHand.RIGHT
    assert grabber_server.dequip_requests == []

    out = capsys.readouterr().out
    assert "equipped=True" in out
    assert "tool=Pen" in out


async def test_dequip_invokes_dequip_rpc_with_hand(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "dequip"])
    assert rc == 0

    assert len(grabber_server.dequip_requests) == 1
    assert grabber_server.dequip_requests[0].hand == GrabberHand.PRIMARY
    assert grabber_server.equip_requests == []

    out = capsys.readouterr().out
    assert "equipped=False" in out


async def test_use_json_emits_state_with_held_button_label(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "use", "--button", "secondary", "--format", "json"])
    assert rc == 0

    payload = _sole_json_document(capsys.readouterr().out)
    assert payload == {
        "hand": "primary",
        "is_holding": True,
        "object_names": ["Cube"],
        "unix_nanos": 2468,
        "is_tool_equipped": False,
        "equipped_tool_name": "",
        # held_buttons surfaces as the string label, not the wire enum int.
        "held_buttons": ["secondary"],
    }


async def test_equip_json_emits_tool_equipped_state(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grabber", "equip", "--format", "json"])
    assert rc == 0

    payload = _sole_json_document(capsys.readouterr().out)
    assert payload == {
        "hand": "primary",
        "is_holding": False,
        "object_names": [],
        "unix_nanos": 3690,
        "is_tool_equipped": True,
        "equipped_tool_name": "Pen",
        "held_buttons": [],
    }


async def test_invalid_button_exits_with_usage_code():
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["grabber", "use", "--button", "middle"])
    assert excinfo.value.code == _ARGPARSE_USAGE_EXIT_CODE


async def test_grab_interactive_rejects_structured_format(
    capsys: pytest.CaptureFixture[str],
):
    """``grabber interactive`` is a human-only carve-out.

    ``--format`` lives on the shared flat ``grabber`` parser (so grab/release/
    state can emit json), but the interactive loop has no structured output.
    Requesting ``--format json`` must fail with the usage exit code (2) and a
    stderr note rather than silently running the REPL. The guard returns
    before any stdin / RPC interaction, so no fake server or tty is needed.
    """
    rc = await _invoke(["grabber", "interactive", "--format", "json"])
    assert rc == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--format" in captured.err and "interactive" in captured.err
