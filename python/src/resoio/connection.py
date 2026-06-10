"""Client for the Resonite IO ``Connection`` modality (liveness / version).

Bidirectional unary RPCs: ``ping`` round-trips a liveness echo and
``get_mod_version`` reports the running mod build, both over the UDS.
"""

from __future__ import annotations

import logging
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    ConnectionStub,
    GetModVersionRequest,
    PingRequest,
    PingResponse,
)

__all__ = [
    "ConnectionClient",
]

_logger = logging.getLogger(__name__)


class ConnectionClient(_BaseClient[ConnectionStub]):
    """Async client for the Resonite IO ``Connection`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. With ``socket_path=None`` the path is resolved on
    ``__aenter__`` via ``RESONITE_IO_SOCKET`` →
    ``RESONITE_IO_SOCKET_DIR`` → ``~/.resonite-io/``; resolution may
    raise :class:`SocketNotFoundError` or :class:`AmbiguousSocketError`.
    """

    _logger = _logger
    _log_label = "Connection"

    @override
    def _make_stub(self, channel: Channel) -> ConnectionStub:
        return ConnectionStub(channel)

    async def ping(self, message: str) -> PingResponse:
        """Round-trip a liveness check and return the server's echo.

        A healthy mod echoes ``message`` back unchanged, so callers can use
        the round trip as a connectivity probe before opening other
        modality streams.

        Returns:
            The :class:`PingResponse` carrying the echoed ``message`` and
            the server-side response timestamp.

        Raises:
            grpclib.exceptions.GRPCError: The RPC failed at the transport
                or server layer (e.g. the mod went away mid-call).
        """
        stub = self._require_stub()
        return await stub.ping(PingRequest(message=message))

    async def get_mod_version(self) -> str:
        """Return the running C# Mod's version string (csproj
        ``<Version>``)."""
        stub = self._require_stub()
        response = await stub.get_mod_version(GetModVersionRequest())
        return response.version
