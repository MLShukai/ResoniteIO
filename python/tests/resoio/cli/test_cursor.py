"""CLI tests for ``resoio cursor``.

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`CursorBase` over a real UDS (no mocking of
grpclib/betterproto2). Each test asserts that the chosen action invokes the
correct RPC with the correct coordinates and that the resulting cursor
state is printed in the documented format
(``x={x} y={y} window={w}x{h} held={held}``, with ``held`` rendered as the
Python bool repr). ``release`` is a new action that drops the hold
established by ``set`` / ``center``.

Per the subparser contract, ``cursor set`` takes two required float
positionals: a missing/non-numeric coordinate, a missing subcommand, or an
unknown subcommand is an argparse usage error (SystemExit with code 2 at
``parse_args`` time). The [0,1] range check is pinned by exit code only
(``_run_cli`` normalizes parse-time SystemExit and runtime return codes).
"""

from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    CursorBase,
    CursorGetPositionRequest,
    CursorReleaseRequest,
    CursorSetPositionRequest,
    CursorState as PbCursorState,
)
from resoio.cli import _amain, _build_parser


async def _run_cli(argv: list[str]) -> int:
    """Run the CLI and return its exit code.

    Normalizes the two contractual error loci: an argparse usage error
    (SystemExit raised by ``parse_args``) and a runtime return code from
    ``_amain``. The contract pins the exit code, not the locus.
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        assert isinstance(exc.code, int)
        return exc.code
    return await _amain(args)


def _parse_error_code(argv: list[str]) -> int:
    """Return the SystemExit code raised by ``parse_args`` for ``argv``."""
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(argv)
    assert isinstance(excinfo.value.code, int)
    return excinfo.value.code


class _FakeCursor(CursorBase):
    """In-process fake recording each request and returning a fixed state.

    Per the hold contract, ``set_position`` echoes the requested position
    with ``held=True``, ``get_position`` reports an unheld cursor, and
    ``release`` reports ``held=False``.
    """

    def __init__(self) -> None:
        self.set_requests: list[CursorSetPositionRequest] = []
        self.get_requests: list[CursorGetPositionRequest] = []
        self.release_requests: list[CursorReleaseRequest] = []

    async def set_position(self, message: CursorSetPositionRequest) -> PbCursorState:
        self.set_requests.append(message)
        return PbCursorState(
            x=message.x, y=message.y, window_width=1920, window_height=1080, held=True
        )

    async def get_position(self, message: CursorGetPositionRequest) -> PbCursorState:
        self.get_requests.append(message)
        return PbCursorState(
            x=0.5, y=0.25, window_width=1920, window_height=1080, held=False
        )

    async def release(self, message: CursorReleaseRequest) -> PbCursorState:
        self.release_requests.append(message)
        return PbCursorState(
            x=0.5, y=0.25, window_width=1920, window_height=1080, held=False
        )


async def test_set_forwards_xy_and_prints_held_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["cursor", "set", "0.5", "0.25"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.set_requests) == 1
        assert fake.set_requests[0].x == pytest.approx(0.5)
        assert fake.set_requests[0].y == pytest.approx(0.25)

        out = capsys.readouterr().out.strip()
        assert out == "x=0.5 y=0.25 window=1920x1080 held=True"
    finally:
        server.close()
        await server.wait_closed()


async def test_center_moves_to_half_half(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["cursor", "center"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.set_requests) == 1
        assert fake.set_requests[0].x == pytest.approx(0.5)
        assert fake.set_requests[0].y == pytest.approx(0.5)
    finally:
        server.close()
        await server.wait_closed()


async def test_get_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["cursor", "get"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.get_requests) == 1
        assert fake.set_requests == []
        assert fake.release_requests == []

        out = capsys.readouterr().out.strip()
        assert out == "x=0.5 y=0.25 window=1920x1080 held=False"
    finally:
        server.close()
        await server.wait_closed()


async def test_release_issues_release_rpc_and_prints_unheld_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``release`` drops the hold without moving or reading the cursor."""
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["cursor", "release"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.release_requests) == 1
        assert fake.set_requests == []
        assert fake.get_requests == []

        out = capsys.readouterr().out.strip()
        assert out == "x=0.5 y=0.25 window=1920x1080 held=False"
    finally:
        server.close()
        await server.wait_closed()


async def test_socket_flag_routes_to_get_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """``-s SOCK`` is the sole socket route (env var would mask intent)."""
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        args = _build_parser().parse_args(["cursor", "get", "-s", str(socket_path)])
        rc = await _amain(args)
        assert rc == 0
        assert len(fake.get_requests) == 1
    finally:
        server.close()
        await server.wait_closed()


def test_set_without_coordinates_is_a_parse_error():
    """``set`` requires x and y positionals; omitting both exits 2 at parse."""
    assert _parse_error_code(["cursor", "set"]) == 2


def test_set_with_only_x_is_a_parse_error():
    """``set`` requires both coordinates; a lone x exits 2 at parse."""
    assert _parse_error_code(["cursor", "set", "0.5"]) == 2


def test_set_with_non_numeric_coordinate_is_a_parse_error():
    """Coordinates are argparse floats; non-numeric input exits 2 at parse."""
    assert _parse_error_code(["cursor", "set", "abc", "0.5"]) == 2


async def test_set_out_of_range_exits_2():
    """Coordinates outside [0,1] are rejected with exit code 2."""
    assert await _run_cli(["cursor", "set", "1.5", "0.5"]) == 2


def test_missing_subcommand_is_a_parse_error():
    """``cursor`` without a subcommand is a usage error (exit 2)."""
    assert _parse_error_code(["cursor"]) == 2


def test_unknown_subcommand_is_a_parse_error():
    """An unknown ``cursor`` subcommand is a usage error (exit 2)."""
    assert _parse_error_code(["cursor", "warp"]) == 2
