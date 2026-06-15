"""E2E: drive the Auth modality against a live, gh-auth-like Resonite client.

Exercises the real ``FrooxEngineAuthBridge`` over the live UDS. Auth has no
visual state, so there is no screenshot step; the contract is purely the
:class:`AuthStatus` snapshot returned by each unary RPC.

Two tiers, both gated by the shared ``require_host_agent`` autouse fixture:

* ``test_status_is_safe`` always runs under e2e. It calls
  :meth:`AuthClient.status` once and pins the *shape* of the returned
  ``AuthStatus``: it is read-only, never mutates the live session, and its
  fields are internally consistent (logged-in => populated ids; logged-out =>
  empty ids + zero expiry). It deliberately does NOT assert a particular
  ``logged_in`` value: whether the running client is signed in is an external
  fact about the machine, not something this test should fix.

* ``test_logout_then_login_roundtrip`` is DESTRUCTIVE to the live cloud
  session (it logs the running client out and back in). It is opt-in only:
  the credential + password come from env, and the destructive path must be
  explicitly armed via ``RESONITE_IO_E2E_AUTH_DESTRUCTIVE=1``. Absent any of
  those it ``pytest.skip``s with a clear reason. Credentials are NEVER
  hardcoded and the password is NEVER printed (it stays in the env -> wire
  request path and is not echoed by any assertion or message here).

Env vars for the destructive path:

* ``RESONITE_IO_E2E_AUTH_DESTRUCTIVE`` -- set to ``1`` to arm the
  logout/login roundtrip. Unset/anything else => skip.
* ``RESONITE_IO_E2E_CREDENTIAL`` -- username / email / ``U-`` user id.
* ``RESONITE_IO_E2E_PASSWORD`` -- plaintext secret (never logged).
* ``RESONITE_IO_E2E_TOTP`` -- optional 2FA code for TOTP-enabled accounts.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live Resonite client; the
``require_host_agent`` autouse fixture skips when the agent is absent.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import grpclib
import pytest
from grpclib.const import Status

from resoio.auth import AuthClient, AuthStatus
from tests.helpers import mark_e2e

# UDS bind can precede cloud/engine readiness: while the engine is still
# booting the Auth bridge may be unregistered (UNAVAILABLE) or report
# FAILED_PRECONDITION. ``status`` itself is a null-safe read that returns a
# logged-out snapshot rather than raising, but the brief boot window can still
# surface a transient transport-level failure, so poll like the sibling
# harnesses (session.py / world.py / cursor.py).
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0

_DESTRUCTIVE_ENV = "RESONITE_IO_E2E_AUTH_DESTRUCTIVE"
_CREDENTIAL_ENV = "RESONITE_IO_E2E_CREDENTIAL"
_PASSWORD_ENV = "RESONITE_IO_E2E_PASSWORD"
_TOTP_ENV = "RESONITE_IO_E2E_TOTP"


def _assert_status_shape(status: AuthStatus) -> None:
    """Pin the internal consistency of an :class:`AuthStatus` snapshot.

    Does not assert a particular ``logged_in`` value (that is an external
    fact about the running client); only that the fields agree with it.
    """
    assert isinstance(status, AuthStatus)
    assert isinstance(status.logged_in, bool)
    assert isinstance(status.user_id, str)
    assert isinstance(status.user_name, str)
    assert isinstance(status.session_expires_unix_nanos, int)
    if status.logged_in:
        # Logged in => the engine resolved an identity for the session.
        assert status.user_id, "logged-in status must carry a non-empty user_id"
        assert status.user_name, "logged-in status must carry a non-empty user_name"
    else:
        # Logged out => the empty/zero contract documented on AuthStatus.
        assert status.user_id == ""
        assert status.user_name == ""
        assert status.session_expires_unix_nanos == 0


async def _wait_for_status_ready() -> AuthStatus:
    """Block until ``status`` returns cleanly, returning the first snapshot.

    Retries only the transient boot-window failures (UNAVAILABLE while
    the bridge is not yet registered, FAILED_PRECONDITION while the
    cloud manager is still coming up); anything else propagates
    immediately.
    """
    deadline = time.monotonic() + _READY_TIMEOUT_S
    transient = {Status.UNAVAILABLE, Status.FAILED_PRECONDITION}
    while True:
        try:
            async with AuthClient() as client:
                return await client.status()
        except grpclib.exceptions.GRPCError as e:
            if e.status not in transient or time.monotonic() > deadline:
                raise
            await asyncio.sleep(_READY_RETRY_INTERVAL_S)


class TestAuth:
    @mark_e2e
    def test_status_is_safe(self, resonite_session: Path) -> None:
        """Read-only: ``status`` returns a well-formed AuthStatus and does
        not mutate the live session (calling it twice is stable)."""
        del resonite_session  # fixture only manages Resonite lifecycle

        async def run() -> None:
            first = await _wait_for_status_ready()
            _assert_status_shape(first)

            # Idempotent read: a second call must not change login state.
            async with AuthClient() as client:
                second = await client.status()
            _assert_status_shape(second)
            assert second.logged_in == first.logged_in
            assert second.user_id == first.user_id

        asyncio.run(run())

    @mark_e2e
    def test_logout_then_login_roundtrip(self, resonite_session: Path) -> None:
        """DESTRUCTIVE: log the live client out, then back in.

        Opt-in only; skips cleanly unless armed via env. The password is
        read from env straight into the wire request and is never printed.
        """
        del resonite_session  # fixture only manages Resonite lifecycle

        if os.environ.get(_DESTRUCTIVE_ENV) != "1":
            pytest.skip(
                "destructive auth roundtrip not armed; set "
                f"{_DESTRUCTIVE_ENV}=1 (plus {_CREDENTIAL_ENV} / {_PASSWORD_ENV}) "
                "to run it. It logs the live Resonite client OUT and back in."
            )
        credential = os.environ.get(_CREDENTIAL_ENV)
        password = os.environ.get(_PASSWORD_ENV)
        if not credential or not password:
            pytest.skip(
                f"destructive auth roundtrip needs both {_CREDENTIAL_ENV} and "
                f"{_PASSWORD_ENV} in the environment (password is never logged)."
            )
        totp = os.environ.get(_TOTP_ENV) or None

        async def run() -> None:
            # Confirm the bridge is up before mutating anything.
            await _wait_for_status_ready()

            # logout: ends the session (idempotent even if already out).
            async with AuthClient() as client:
                logged_out = await client.logout()
            _assert_status_shape(logged_out)
            assert logged_out.logged_in is False

            # login: signs back in with the env credential + secret.
            async with AuthClient() as client:
                logged_in = await client.login(credential, password, totp=totp)
            _assert_status_shape(logged_in)
            assert logged_in.logged_in is True
            assert logged_in.user_id, "login should populate user_id"
            assert logged_in.user_name, "login should populate user_name"

            # Cross-RPC confirmation: a fresh status read agrees.
            async with AuthClient() as client:
                after = await client.status()
            assert after.logged_in is True
            assert after.user_id == logged_in.user_id

        asyncio.run(run())
