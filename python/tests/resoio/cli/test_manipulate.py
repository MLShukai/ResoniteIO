"""CLI tests for ``resoio manipulate``.

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`ManipulationBase` over a real UDS (no mocking
of grpclib/betterproto2). Each test asserts that the chosen action invokes
the correct RPC with the correct ``hand`` (and ``radius`` for ``grab`` —
grab always targets the desktop cursor-ray hit point, there is no
``--point``) and that key result fields are printed.

Flat dispatch via a positional ``action`` in
{grab, release, state, interactive}. The interactive raw-tty loop is out of
scope (hard to drive deterministically) and is not exercised here.
"""

from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    ManipulationBase,
    ManipulationGetStateRequest,
    ManipulationGrabRequest,
    ManipulationGrabResult as PbManipulationGrabResult,
    ManipulationGrabState as PbManipulationGrabState,
    ManipulationHand,
    ManipulationReleaseRequest,
)
from resoio.cli import _amain, _build_parser

# Exactly representable in float32 so the printed values are stable across
# the proto round-trip.
_RADIUS = 0.5


class _EchoManipulation(ManipulationBase):
    """In-process fake recording each request and echoing it into the reply."""

    def __init__(self) -> None:
        self.grab_requests: list[ManipulationGrabRequest] = []
        self.release_requests: list[ManipulationReleaseRequest] = []
        self.get_state_requests: list[ManipulationGetStateRequest] = []

    async def grab(self, message: ManipulationGrabRequest) -> PbManipulationGrabResult:
        self.grab_requests.append(message)
        return PbManipulationGrabResult(
            grabbed=True,
            state=PbManipulationGrabState(
                hand=message.hand,
                is_holding=True,
                object_names=["Cube"],
                unix_nanos=1234,
            ),
        )

    async def release(
        self, message: ManipulationReleaseRequest
    ) -> PbManipulationGrabState:
        self.release_requests.append(message)
        return PbManipulationGrabState(
            hand=message.hand,
            is_holding=False,
            object_names=[],
            unix_nanos=5678,
        )

    async def get_state(
        self, message: ManipulationGetStateRequest
    ) -> PbManipulationGrabState:
        self.get_state_requests.append(message)
        return PbManipulationGrabState(
            hand=message.hand,
            is_holding=True,
            object_names=["Cube", "Sphere"],
            unix_nanos=9012,
        )


async def test_grab_forwards_radius_and_hand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-manipulation.sock"
    fake = _EchoManipulation()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["manipulate", "grab", "--radius", "0.5", "--hand", "left"]
        )
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.grab_requests) == 1
        wire = fake.grab_requests[0]
        assert wire.hand == ManipulationHand.LEFT
        assert wire.radius == _RADIUS

        out = capsys.readouterr().out
        # Key result fields surface in the printed output.
        assert "True" in out  # grabbed / is_holding
        assert "Cube" in out
    finally:
        server.close()
        await server.wait_closed()


async def test_grab_defaults_to_primary_hand_and_zero_radius(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-manipulation.sock"
    fake = _EchoManipulation()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["manipulate", "grab"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.grab_requests) == 1
        # No --hand given -> default primary.
        assert fake.grab_requests[0].hand == ManipulationHand.PRIMARY
        # No --radius given -> 0.0 travels verbatim; resolving <=0 to the
        # server default (0.1m) is a C#-Core concern.
        assert fake.grab_requests[0].radius == 0.0
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.api_contract
def test_grab_rejects_removed_point_flag():
    """Contract pin, not a behaviour test: ``--point`` was removed when grab
    became cursor-ray based (Part B, breaking).

    argparse must reject it with
    ``SystemExit`` — this detects a silent reintroduction of the flag.
    """
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["manipulate", "grab", "--point", "1", "2", "3"])


async def test_release_invokes_release_rpc_with_hand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-manipulation.sock"
    fake = _EchoManipulation()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["manipulate", "release", "--hand", "right"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.release_requests) == 1
        assert fake.release_requests[0].hand == ManipulationHand.RIGHT
        # release must not grab or read state.
        assert fake.grab_requests == []
        assert fake.get_state_requests == []

        out = capsys.readouterr().out
        assert "False" in out  # is_holding=False after release
    finally:
        server.close()
        await server.wait_closed()


async def test_state_invokes_get_state_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-manipulation.sock"
    fake = _EchoManipulation()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["manipulate", "state"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.get_state_requests) == 1
        assert fake.get_state_requests[0].hand == ManipulationHand.PRIMARY
        # state must be read-only.
        assert fake.grab_requests == []
        assert fake.release_requests == []

        out = capsys.readouterr().out
        assert "Cube" in out
        assert "Sphere" in out
    finally:
        server.close()
        await server.wait_closed()


async def test_socket_flag_routes_to_get_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """``-s SOCK`` is the sole socket route (env var would mask intent)."""
    socket_path = tmp_path / "rio-manipulation.sock"
    fake = _EchoManipulation()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        args = _build_parser().parse_args(
            ["manipulate", "state", "-s", str(socket_path)]
        )
        rc = await _amain(args)
        assert rc == 0
        assert len(fake.get_state_requests) == 1
    finally:
        server.close()
        await server.wait_closed()
