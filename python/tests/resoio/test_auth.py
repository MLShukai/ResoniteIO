"""Behaviour tests for :class:`resoio.auth.AuthClient`.

These are spec tests for the Auth modality (Resonite cloud login /
logout / status, gh-auth-like). They follow the canonical "grpclib
end-to-end round-trip" harness from testing-strategy: a real
``grpclib.server.Server`` listens on a real Unix Domain Socket with an
in-process, self-owned :class:`AuthBase` fake, and the ``AuthClient``
connects over the real wire. No grpclib / asyncio / betterproto
internals are mocked -- the only fake is the self-owned servicer ABC.

The recurring proof in this file is two-fold. First, *wire mapping*:
``login`` carries credential / password / totp / remember_me onto the
deserialized request the fake observes over the socket. Second, *proto3
optional presence* for ``totp``: a ``None`` kwarg must not appear on the
wire (the fake observes ``None``) while a concrete value must (the fake
observes the string). Because each request crosses a real socket,
presence and mapping are verified against the message the server
actually received, not the object the client built.

The password is a plaintext secret; the tests assert it rides on the
wire (the server needs it) but the client / module are responsible for
never logging it -- that is covered at the layers that emit output, not
here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest

from resoio._generated.resonite_io.v1 import (
    AuthBase,
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthStatus as PbAuthStatus,
    AuthStatusRequest,
)
from resoio.auth import AuthClient, AuthStatus

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


# ---------------------------------------------------------------------------
# In-process fake (self-owned AuthBase ABC).
# ---------------------------------------------------------------------------


class _FakeAuth(AuthBase):
    """Records each request and serves configurable canned AuthStatus."""

    def __init__(
        self,
        *,
        login_status: PbAuthStatus | None = None,
        logout_status: PbAuthStatus | None = None,
        status: PbAuthStatus | None = None,
    ) -> None:
        # NB: explicit `is None` checks, never `x or default`. An all-default
        # protobuf message is *falsy*, so `status or ...` would silently
        # replace a caller's "all zeros" snapshot (e.g. a logged_in=False
        # status) with the default -- masking the very case under test.
        self._login_status = (
            login_status if login_status is not None else PbAuthStatus()
        )
        self._logout_status = (
            logout_status if logout_status is not None else PbAuthStatus()
        )
        self._status = status if status is not None else PbAuthStatus()

        self.last_login: AuthLoginRequest | None = None
        self.last_logout: AuthLogoutRequest | None = None
        self.last_status: AuthStatusRequest | None = None

    async def login(self, message: AuthLoginRequest) -> PbAuthStatus:
        self.last_login = message
        return self._login_status

    async def logout(self, message: AuthLogoutRequest) -> PbAuthStatus:
        self.last_logout = message
        return self._logout_status

    async def status(self, message: AuthStatusRequest) -> PbAuthStatus:
        self.last_status = message
        return self._status


# ===========================================================================
# login: credential / password / totp / remember_me onto the wire request.
#
# Verified against the deserialized request the fake received over the real
# socket, not the object the client built.
# ===========================================================================


class TestLoginRequestMapping:
    async def test_forwards_credential_and_password(self, uds_server: UdsServer):
        """The credential and the plaintext password must both ride on the
        wire -- the server needs the password to authenticate."""
        fake = _FakeAuth()
        await uds_server(fake)
        async with AuthClient() as client:
            await client.login("alice", "s3cret")
        assert fake.last_login is not None
        assert fake.last_login.credential == "alice"
        assert fake.last_login.password == "s3cret"

    async def test_totp_none_stays_off_the_wire(self, uds_server: UdsServer):
        """``totp=None`` (the default) means "no 2FA code"; ``totp`` is proto3
        ``optional``, so the field must stay off the wire and the server
        observes ``None`` rather than an empty string."""
        fake = _FakeAuth()
        await uds_server(fake)
        async with AuthClient() as client:
            await client.login("alice", "pw")  # totp omitted
        assert fake.last_login is not None
        assert fake.last_login.totp is None

    async def test_totp_value_rides_on_the_wire(self, uds_server: UdsServer):
        """A concrete ``totp`` must cross the wire so the server can complete
        2FA -- distinct from the ``None`` absence above."""
        fake = _FakeAuth()
        await uds_server(fake)
        async with AuthClient() as client:
            await client.login("alice", "pw", totp="123456")
        assert fake.last_login is not None
        assert fake.last_login.totp == "123456"

    async def test_remember_me_defaults_true_on_the_wire(self, uds_server: UdsServer):
        """``remember_me`` defaults to True (CLI default): the proto3 bool
        default is False, so the client must put the True intent on the wire
        for the engine to persist the session."""
        fake = _FakeAuth()
        await uds_server(fake)
        async with AuthClient() as client:
            await client.login("alice", "pw")  # remember_me omitted -> True
        assert fake.last_login is not None
        assert fake.last_login.remember_me is True

    async def test_remember_me_false_rides_on_the_wire(self, uds_server: UdsServer):
        """``remember_me=False`` (the ``--no-remember`` intent) must cross the
        wire as False, distinct from the default True -- the engine must not
        persist the session."""
        fake = _FakeAuth()
        await uds_server(fake)
        async with AuthClient() as client:
            await client.login("alice", "pw", remember_me=False)
        assert fake.last_login is not None
        assert fake.last_login.remember_me is False

    async def test_full_request_carries_every_field(self, uds_server: UdsServer):
        """All four fields ride together with distinct values, catching a
        copy/paste swap that identical placeholders would mask."""
        fake = _FakeAuth()
        await uds_server(fake)
        async with AuthClient() as client:
            await client.login(
                "U-abc",
                "p@ss",
                totp="999000",
                remember_me=False,
            )
        assert fake.last_login is not None
        assert fake.last_login.credential == "U-abc"
        assert fake.last_login.password == "p@ss"
        assert fake.last_login.totp == "999000"
        assert fake.last_login.remember_me is False


# ===========================================================================
# login: wire AuthStatus -> AuthStatus dataclass mapping.
# ===========================================================================


class TestLoginResult:
    async def test_maps_every_status_field_into_the_dataclass(
        self, uds_server: UdsServer
    ):
        """Distinct values in every field catch a field wired to the wrong
        source attribute (a copy/paste swap)."""
        await uds_server(
            _FakeAuth(
                login_status=PbAuthStatus(
                    logged_in=True,
                    user_id="U-1",
                    user_name="alice",
                    session_expires_unix_nanos=1_700_000_000_000_000_000,
                )
            )
        )
        async with AuthClient() as client:
            status = await client.login("alice", "pw")
        assert status == AuthStatus(
            logged_in=True,
            user_id="U-1",
            user_name="alice",
            session_expires_unix_nanos=1_700_000_000_000_000_000,
        )

    async def test_raises_when_not_connected(self):
        client = AuthClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.login("alice", "pw")


# ===========================================================================
# logout: empty request body + wire AuthStatus -> dataclass mapping.
# ===========================================================================


class TestLogout:
    async def test_sends_request_and_returns_logged_out_status(
        self, uds_server: UdsServer
    ):
        """``logout`` returns the engine's post-logout snapshot
        (``logged_in=False`` with cleared identity), mapped to the
        dataclass."""
        fake = _FakeAuth(
            logout_status=PbAuthStatus(
                logged_in=False,
                user_id="",
                user_name="",
                session_expires_unix_nanos=0,
            )
        )
        await uds_server(fake)
        async with AuthClient() as client:
            status = await client.logout()
        assert fake.last_logout is not None
        assert status == AuthStatus(
            logged_in=False,
            user_id="",
            user_name="",
            session_expires_unix_nanos=0,
        )

    async def test_raises_when_not_connected(self):
        client = AuthClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.logout()


# ===========================================================================
# status: empty request body + wire AuthStatus -> dataclass mapping.
# ===========================================================================


class TestStatus:
    async def test_sends_request_and_returns_current_status(
        self, uds_server: UdsServer
    ):
        fake = _FakeAuth(
            status=PbAuthStatus(
                logged_in=True,
                user_id="U-7",
                user_name="bob",
                session_expires_unix_nanos=42,
            )
        )
        await uds_server(fake)
        async with AuthClient() as client:
            status = await client.status()
        assert fake.last_status is not None
        assert status == AuthStatus(
            logged_in=True,
            user_id="U-7",
            user_name="bob",
            session_expires_unix_nanos=42,
        )

    async def test_logged_out_status_maps_to_dataclass(self, uds_server: UdsServer):
        """A logged-out snapshot is all-default; the dataclass must reflect
        ``logged_in=False`` with empty identity (not be masked by a falsy
        message check)."""
        await uds_server(_FakeAuth(status=PbAuthStatus()))
        async with AuthClient() as client:
            status = await client.status()
        assert status == AuthStatus(
            logged_in=False,
            user_id="",
            user_name="",
            session_expires_unix_nanos=0,
        )

    async def test_raises_when_not_connected(self):
        client = AuthClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.status()
