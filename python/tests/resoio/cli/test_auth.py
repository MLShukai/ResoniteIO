"""CLI surface tests for ``resoio auth <action>``.

The ``auth`` command group mirrors ``session``: a parent ``auth`` parser
holds the action leaves ``login`` / ``logout`` / ``status``. Each leaf
re-attaches the shared ``-s/--socket`` parent (argparse does not inherit
parent-subparser flags) and the ``--format`` parent (all three produce an
``AuthStatus`` result).

Two complementary layers, matching ``cli/test_session.py``:

1. Parser-only tests build the real parser via ``_build_parser`` and assert
   the group/leaf structure plus flag -> namespace mapping. The
   SECURITY-critical pin lives here: there is no ``--password`` flag (a
   password must never reach ``ps`` / shell history), so
   ``auth login --password x`` is an argparse usage error (exit 2).
2. End-to-end dispatch tests stand up an in-process recording
   :class:`AuthBase` server over a real UDS and drive ``_amain`` so the
   *request actually sent on the wire* proves the CLI selected the right RPC
   and mapped its flags / resolved the password from the documented sources
   (env, piped stdin). Real UDS + real grpclib round-trip (no mocks of
   grpclib / betterproto2 internals).

The interactive hidden-prompt branch (prompt_toolkit) needs a real tty and
is deliberately left untested here; both the env path and the piped-stdin
path keep ``stdin.isatty()`` False so the non-interactive branches are taken.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    AuthBase,
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthStatus as PbAuthStatus,
    AuthStatusRequest,
)
from resoio.cli import _amain, _build_parser

# ===========================================================================
# Parser-only tests: group/leaf structure + flag -> namespace mapping.
# ===========================================================================


def test_auth_group_without_action_is_rejected():
    """``auth`` is a parent with a required action leaf — naming the group
    alone must error (argparse exit code 2)."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["auth"])
    assert excinfo.value.code == 2


@pytest.mark.parametrize("action", ["login", "logout", "status"])
def test_auth_leaves_exist(action: str):
    """Each of login/logout/status parses to a dispatchable namespace."""
    parser = _build_parser()
    args = parser.parse_args(["auth", action])
    assert callable(args.func)


def test_auth_unknown_action_is_rejected():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["auth", "frobnicate"])
    assert excinfo.value.code == 2


def test_login_optional_positional_credential_lands_on_namespace():
    parser = _build_parser()
    args = parser.parse_args(["auth", "login", "alice@example.com"])
    assert args.credential == "alice@example.com"


def test_login_credential_defaults_to_none_when_omitted():
    """The positional credential is optional; absent it is None so the handler
    can fall back to env / stdin / interactive resolution."""
    parser = _build_parser()
    args = parser.parse_args(["auth", "login"])
    assert args.credential is None


def test_login_remember_me_defaults_true():
    """``remember_me`` defaults True (delegates persistence to the engine);
    omitting ``--no-remember`` keeps it True."""
    parser = _build_parser()
    args = parser.parse_args(["auth", "login", "alice"])
    assert args.remember_me is True


def test_login_no_remember_sets_remember_me_false():
    parser = _build_parser()
    args = parser.parse_args(["auth", "login", "alice", "--no-remember"])
    assert args.remember_me is False


def test_login_totp_lands_on_namespace():
    parser = _build_parser()
    args = parser.parse_args(["auth", "login", "alice", "--totp", "123456"])
    assert args.totp == "123456"


def test_login_totp_defaults_to_none():
    parser = _build_parser()
    args = parser.parse_args(["auth", "login", "alice"])
    assert args.totp is None


def test_login_rejects_password_flag():
    """SECURITY PIN: there is NO ``--password`` flag — a plaintext secret must
    never be passable on argv (it would leak via ``ps`` and shell history). The
    parser must reject it as an unknown option (argparse exit code 2)."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["auth", "login", "--password", "hunter2"])
    assert excinfo.value.code == 2


@pytest.mark.parametrize("action", ["login", "logout", "status"])
def test_socket_flag_accepted_on_each_leaf(action: str, tmp_path: Path):
    """``-s/--socket`` is re-attached on each leaf (argparse does not inherit
    parent-subparser flags)."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    args = parser.parse_args(["auth", action, "-s", sock])
    assert args.socket == sock


@pytest.mark.parametrize("action", ["login", "status"])
def test_format_flag_accepted_on_result_leaves(action: str):
    """All three leaves produce an ``AuthStatus`` result, so ``--format`` is a
    valid flag on the result-producing leaves."""
    parser = _build_parser()
    args = parser.parse_args(["auth", action, "--format", "json"])
    assert args.format == "json"


# ===========================================================================
# End-to-end dispatch: argv -> _amain -> in-process AuthBase server.
#
# A recording fake proves the CLI selected the right RPC, resolved the
# password from the documented source, and mapped flags into the request.
# Real UDS + real grpclib round-trip (no mocks).
# ===========================================================================


class _RecordingAuth(AuthBase):
    """In-process Auth server capturing each request for assertion.

    Each RPC returns a fixed logged-in/logged-out snapshot so the CLI's
    rendering path runs end to end; ``session_expires_unix_nanos`` is a large
    (~1.7e18) value so the json round-trip exactness can be asserted.
    """

    def __init__(self) -> None:
        self.login_requests: list[AuthLoginRequest] = []
        self.logout_requests: list[AuthLogoutRequest] = []
        self.status_requests: list[AuthStatusRequest] = []

    async def login(self, message: AuthLoginRequest) -> PbAuthStatus:
        self.login_requests.append(message)
        return PbAuthStatus(
            logged_in=True,
            user_id="U-alice",
            user_name="alice",
            session_expires_unix_nanos=1_700_000_000_123_456_789,
        )

    async def logout(self, message: AuthLogoutRequest) -> PbAuthStatus:
        self.logout_requests.append(message)
        return PbAuthStatus(
            logged_in=False,
            user_id="",
            user_name="",
            session_expires_unix_nanos=0,
        )

    async def status(self, message: AuthStatusRequest) -> PbAuthStatus:
        self.status_requests.append(message)
        return PbAuthStatus(
            logged_in=True,
            user_id="U-alice",
            user_name="alice",
            session_expires_unix_nanos=1_700_000_000_123_456_789,
        )


async def _serve(socket_path: Path) -> tuple[Server, _RecordingAuth]:
    fake = _RecordingAuth()
    server = Server([fake])
    await server.start(path=str(socket_path))
    return server, fake


async def _run_auth(
    argv: list[str],
    socket_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
    args = _build_parser().parse_args(argv)
    return await _amain(args)


def _pipe_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Replace ``sys.stdin`` with a non-tty ``StringIO`` carrying ``text``.

    ``io.StringIO().isatty()`` is False, so the credential / password
    resolution takes the piped (non-interactive) branch rather than the
    interactive prompt_toolkit branch.
    """
    import sys

    stream = io.StringIO(text)
    assert stream.isatty() is False
    monkeypatch.setattr(sys, "stdin", stream)


# --- password sources -------------------------------------------------------


async def test_login_password_from_env_is_forwarded_on_the_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Password from ``RESONITE_IO_PASSWORD`` (source 1) rides the wire
    request; the positional credential is forwarded alongside it."""
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "env-secret")
        rc = await _run_auth(
            ["auth", "login", "alice@example.com"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.login_requests) == 1
    req = fake.login_requests[0]
    assert req.credential == "alice@example.com"
    assert req.password == "env-secret"
    # Leaf selection, not a fallthrough into logout/status.
    assert fake.logout_requests == []
    assert fake.status_requests == []


async def test_login_password_from_stdin_is_forwarded_on_the_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """With no env password and a non-tty stdin (source 2), one line is read
    from stdin and the trailing newline stripped before it rides the wire."""
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        monkeypatch.delenv("RESONITE_IO_PASSWORD", raising=False)
        _pipe_stdin(monkeypatch, "stdin-secret\n")
        rc = await _run_auth(
            ["auth", "login", "alice@example.com"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.login_requests) == 1
    req = fake.login_requests[0]
    assert req.credential == "alice@example.com"
    # The trailing newline must be stripped, not forwarded.
    assert req.password == "stdin-secret"


async def test_login_env_password_takes_precedence_over_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Source order: a non-empty env password wins even when stdin would also
    supply one (env is checked first)."""
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "env-secret")
        _pipe_stdin(monkeypatch, "stdin-secret\n")
        rc = await _run_auth(
            ["auth", "login", "alice@example.com"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.login_requests) == 1
    assert fake.login_requests[0].password == "env-secret"


async def test_login_credential_from_positional_is_forwarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A positional credential is forwarded verbatim (no username prompt)."""
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "env-secret")
        rc = await _run_auth(["auth", "login", "U-bob"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.login_requests) == 1
    assert fake.login_requests[0].credential == "U-bob"


# --- flag mapping -----------------------------------------------------------


async def test_login_default_remember_me_true_on_the_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Default (no ``--no-remember``) sends ``remember_me=True`` on the
    wire."""
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "env-secret")
        rc = await _run_auth(["auth", "login", "alice"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.login_requests) == 1
    assert fake.login_requests[0].remember_me is True


async def test_login_no_remember_sends_remember_me_false_on_the_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "env-secret")
        rc = await _run_auth(
            ["auth", "login", "alice", "--no-remember"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.login_requests) == 1
    assert fake.login_requests[0].remember_me is False


async def test_login_totp_is_forwarded_on_the_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "env-secret")
        rc = await _run_auth(
            ["auth", "login", "alice", "--totp", "654321"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.login_requests) == 1
    assert fake.login_requests[0].totp == "654321"


async def test_login_without_totp_omits_it_on_the_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Without ``--totp`` the proto3 optional field is absent on the wire (the
    server tries a totp-less login)."""
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "env-secret")
        rc = await _run_auth(["auth", "login", "alice"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.login_requests) == 1
    assert fake.login_requests[0].totp is None


# --- logout / status dispatch ----------------------------------------------


async def test_logout_dispatches_logout_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_auth(["auth", "logout"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.logout_requests) == 1
    # Leaf selection, not a fallthrough into login/status.
    assert fake.login_requests == []
    assert fake.status_requests == []


async def test_status_dispatches_status_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-auth.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_auth(["auth", "status"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.status_requests) == 1
    assert fake.login_requests == []
    assert fake.logout_requests == []
    # The human output names the logged-in user.
    assert "alice" in capsys.readouterr().out


# ===========================================================================
# --format json: structured output on the result-producing leaves.
# All three RPCs return an AuthStatus; json emits one document with the four
# fields and the large session_expires_unix_nanos round-trips exactly.
# ===========================================================================


async def test_login_json_emits_status_object_with_exact_large_nanos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``auth login --format json`` emits ONE json object with the four
    ``AuthStatus`` fields; ``logged_in`` is a real json bool and the large
    ``session_expires_unix_nanos`` round-trips exactly (JSON has no int
    limit)."""
    socket_path = tmp_path / "rio-auth.sock"
    server, _fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "env-secret")
        rc = await _run_auth(
            ["auth", "login", "alice", "--format", "json"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = json.loads(capsys.readouterr().out)  # exactly one document
    assert isinstance(payload, dict)
    assert payload["logged_in"] is True
    assert payload["user_id"] == "U-alice"
    assert payload["user_name"] == "alice"
    assert payload["session_expires_unix_nanos"] == 1_700_000_000_123_456_789
    assert payload["session_expires_iso"] == "2023-11-14T22:13:20.123456+00:00"


async def test_status_json_emits_status_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-auth.sock"
    server, _fake = await _serve(socket_path)
    try:
        rc = await _run_auth(
            ["auth", "status", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert payload["logged_in"] is True
    assert payload["user_id"] == "U-alice"
    assert payload["user_name"] == "alice"
    assert payload["session_expires_unix_nanos"] == 1_700_000_000_123_456_789
    assert payload["session_expires_iso"] == "2023-11-14T22:13:20.123456+00:00"


async def test_login_json_password_never_appears_in_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """SECURITY: the plaintext password must never reach ``--format json``
    output (nor any human output) — only the AuthStatus snapshot is emitted."""
    socket_path = tmp_path / "rio-auth.sock"
    server, _fake = await _serve(socket_path)
    try:
        monkeypatch.setenv("RESONITE_IO_PASSWORD", "topsecret-xyz")
        rc = await _run_auth(
            ["auth", "login", "alice", "--format", "json"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    out = capsys.readouterr().out
    assert "topsecret-xyz" not in out
    # Sanity: the emitted document is still the real status payload.
    assert json.loads(out)["user_name"] == "alice"


async def test_status_human_renders_expiry_as_datetime_not_nanos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``auth status`` (human) renders the session expiry as a UTC datetime,
    not the raw unix-nanos integer."""
    socket_path = tmp_path / "rio-auth.sock"
    server, _fake = await _serve(socket_path)
    try:
        rc = await _run_auth(["auth", "status"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()
    out = capsys.readouterr().out
    # 1_700_000_000_123_456_789 ns -> 2023-11-14 22:13:20 UTC (microsecond floor).
    assert "Session expires at 2023-11-14 22:13:20 UTC" in out
    # The raw nanos integer must NOT appear in the human output.
    assert "1700000000123456789" not in out
