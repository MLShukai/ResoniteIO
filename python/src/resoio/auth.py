"""Client for the Resonite IO ``Auth`` modality (cloud login / logout /
status).

Unary RPCs covering Resonite cloud authentication: ``login`` signs in with a
credential + password (and an optional TOTP), ``logout`` ends the session, and
``status`` reads the current authentication state back. All three RPCs return
the unified :class:`AuthStatus` snapshot.

The login password is a plaintext secret: this module never logs it and never
puts it (or any credential) into a log line, exception message, or other
output. ``remember_me=True`` delegates session persistence to the Resonite
engine -- this client stores no credentials on disk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthStatus as _PbAuthStatus,
    AuthStatusRequest,
    AuthStub,
)

__all__ = [
    "AuthClient",
    "AuthStatus",
]

_logger = logging.getLogger("resoio.auth")


@dataclass(frozen=True, slots=True)
class AuthStatus:
    """Snapshot of the Resonite cloud authentication state.

    ``user_id`` / ``user_name`` are empty and ``session_expires_unix_nanos``
    is ``0`` when not logged in.
    """

    logged_in: bool
    user_id: str
    user_name: str
    session_expires_unix_nanos: int


def _status_from_proto(pb: _PbAuthStatus) -> AuthStatus:
    return AuthStatus(
        logged_in=pb.logged_in,
        user_id=pb.user_id,
        user_name=pb.user_name,
        session_expires_unix_nanos=pb.session_expires_unix_nanos,
    )


class AuthClient(_BaseClient[AuthStub]):
    """Async client for the Resonite IO ``Auth`` service over a UDS.

    Use as an async context manager so the gRPC channel closes
    deterministically.

    The password passed to :meth:`login` is a plaintext secret and is never
    logged. ``remember_me=True`` asks the engine to persist the session; this
    client itself stores nothing on disk.
    """

    _logger = _logger
    _log_label = "Auth"

    @override
    def _make_stub(self, channel: Channel) -> AuthStub:
        return AuthStub(channel)

    async def login(
        self,
        credential: str,
        password: str,
        *,
        totp: str | None = None,
        remember_me: bool = True,
    ) -> AuthStatus:
        """Sign in to Resonite cloud and return the resulting status.

        ``credential`` is a username, email, or user ID (``U-xxx``);
        ``password`` is the plaintext secret (never logged). Pass ``totp`` for
        2FA-enabled accounts; omitting it on such an account makes the server
        return gRPC ``FailedPrecondition``. Bad credentials return
        ``Unauthenticated``. ``remember_me=True`` delegates session
        persistence to the engine.
        """
        stub = self._require_stub()
        request = AuthLoginRequest(
            credential=credential,
            password=password,
            totp=totp,
            remember_me=remember_me,
        )
        return _status_from_proto(await stub.login(request))

    async def logout(self) -> AuthStatus:
        """Log out of the current session; returns the updated status.

        Idempotent: returns ``logged_in=False`` even if no session was active.
        """
        stub = self._require_stub()
        return _status_from_proto(await stub.logout(AuthLogoutRequest()))

    async def status(self) -> AuthStatus:
        """Return the current authentication status without modifying it."""
        stub = self._require_stub()
        return _status_from_proto(await stub.status(AuthStatusRequest()))
