"""CLI tests for ``resoio grab`` (renamed from ``resoio manipulate``).

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`GrabberBase` over a real UDS (no mocking of
grpclib/betterproto2). Each test asserts that the chosen subaction invokes
the correct RPC with the correct ``hand`` (and ``radius`` for ``grab`` —
grab always targets the desktop cursor-ray hit point, there is no
``--point``) and that key result fields are printed.

Contract under test (CLI restructure spec):

* ``resoio grab`` with no subaction performs the grab action (default);
  ``resoio grab grab`` is the explicit synonym
* ``resoio grab release`` / ``resoio grab state`` / ``resoio grab
  interactive`` select the other actions
* ``--hand`` / ``--radius`` / ``-s/--socket`` are accepted both before and
  after the subaction
* an unknown subaction exits with the argparse usage code (2)
* output format and RPC semantics are unchanged from ``resoio manipulate``

The interactive raw-tty loop is out of scope (hard to drive
deterministically) and is not exercised here.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    GrabberBase,
    GrabberGetStateRequest,
    GrabberGrabRequest,
    GrabberGrabResult as PbGrabberGrabResult,
    GrabberGrabState as PbGrabberGrabState,
    GrabberHand,
    GrabberReleaseRequest,
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


# --- default subaction = grab ---------------------------------------------


async def test_grab_without_subaction_performs_grab(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grab"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    # No subaction means grab — release/state must not fire.
    assert grabber_server.release_requests == []
    assert grabber_server.get_state_requests == []

    out = capsys.readouterr().out
    assert "True" in out  # grabbed / is_holding
    assert "Cube" in out


async def test_grab_without_subaction_defaults_to_primary_hand_and_zero_radius(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grab"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    # No --hand given -> default primary.
    assert grabber_server.grab_requests[0].hand == GrabberHand.PRIMARY
    # No --radius given -> 0.0 travels verbatim; resolving <=0 to the
    # server default (0.1m) is a C#-Core concern.
    assert grabber_server.grab_requests[0].radius == 0.0


async def test_grab_with_explicit_grab_subaction_is_synonym_for_default(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grab", "grab"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    assert grabber_server.release_requests == []
    assert grabber_server.get_state_requests == []

    out = capsys.readouterr().out
    assert "Cube" in out


# --- flag placement: before or after the subaction -------------------------


async def test_grab_flags_after_subaction_forward_hand_and_radius(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grab", "grab", "--radius", "0.5", "--hand", "left"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    wire = grabber_server.grab_requests[0]
    assert wire.hand == GrabberHand.LEFT
    assert wire.radius == _RADIUS


async def test_grab_flags_before_subaction_forward_hand_and_radius(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grab", "--radius", "0.5", "--hand", "left", "grab"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    wire = grabber_server.grab_requests[0]
    assert wire.hand == GrabberHand.LEFT
    assert wire.radius == _RADIUS


async def test_grab_flags_with_no_subaction_apply_to_default_grab(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grab", "--hand", "left", "--radius", "0.5"])
    assert rc == 0

    assert len(grabber_server.grab_requests) == 1
    wire = grabber_server.grab_requests[0]
    assert wire.hand == GrabberHand.LEFT
    assert wire.radius == _RADIUS


async def test_release_accepts_hand_flag_before_subaction(
    grabber_server: _EchoGrabber,
):
    rc = await _invoke(["grab", "--hand", "left", "release"])
    assert rc == 0

    assert len(grabber_server.release_requests) == 1
    assert grabber_server.release_requests[0].hand == GrabberHand.LEFT
    assert grabber_server.grab_requests == []


# --- release / state semantics ---------------------------------------------


async def test_release_invokes_release_rpc_with_hand(
    grabber_server: _EchoGrabber,
    capsys: pytest.CaptureFixture[str],
):
    rc = await _invoke(["grab", "release", "--hand", "right"])
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
    rc = await _invoke(["grab", "state"])
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
        rc = await _invoke(["grab", "state", "-s", str(socket_path)])
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
        rc = await _invoke(["grab", "-s", str(socket_path), "state"])
        assert rc == 0
        assert len(fake.get_state_requests) == 1
    finally:
        server.close()
        await server.wait_closed()


# --- error handling / contract pins -----------------------------------------


def test_unknown_subaction_exits_with_usage_code():
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["grab", "bogus"])
    assert excinfo.value.code == _ARGPARSE_USAGE_EXIT_CODE


@pytest.mark.api_contract
def test_manipulate_command_name_is_retired():
    """Contract pin, not a behaviour test: the command was renamed
    ``manipulate`` -> ``grab`` (CLI restructure, breaking).

    argparse must reject the old name so the rename cannot silently
    regress into an alias.
    """
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["manipulate", "grab"])
    assert excinfo.value.code == _ARGPARSE_USAGE_EXIT_CODE


@pytest.mark.api_contract
def test_grab_rejects_removed_point_flag():
    """Contract pin, not a behaviour test: ``--point`` was removed when grab
    became cursor-ray based (breaking).

    argparse must reject it with
    ``SystemExit`` — this detects a silent reintroduction of the flag.
    """
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["grab", "grab", "--point", "1", "2", "3"])
