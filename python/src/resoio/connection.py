"""Client for the Resonite IO ``Connection`` modality (liveness).

The ``ping`` unary RPC round-trips a liveness echo over the UDS;
:func:`wait_for_ready` polls it to block until the server is reachable
(startup readiness). Server metadata (mod/engine version, platform) lives
in :mod:`resoio.info`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import override

from grpclib.client import Channel
from grpclib.const import Status
from grpclib.exceptions import GRPCError

from resoio._client import (
    SocketNotFoundError,
    _BaseClient,
    resolve_socket_path,
)
from resoio._generated.resonite_io.v1 import (
    ConnectionStub,
    PingRequest,
    PingResponse,
)

__all__ = [
    "ConnectionClient",
    "wait_for_ready",
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


async def wait_for_ready(
    socket_path: str | None = None,
    *,
    timeout: float | None = None,
    interval: float = 0.1,
) -> str:
    """Block until the Resonite IO server answers ``Connection.Ping``.

    The startup-readiness gate: during cold boot the socket may be absent,
    bound with no listener yet, or bound by an engine that has not finished
    initialising. Each of those is retried; a healthy ping ends the wait and
    the resolved UDS path is returned.

    With ``socket_path=None`` the path is re-resolved on every attempt via
    the usual env order (``RESONITE_IO_SOCKET`` → ``RESONITE_IO_SOCKET_DIR``
    → ``~/.resonite-io/``), so a socket that appears mid-wait is picked up
    and stale sockets whose owning engine PID is gone are skipped by the
    resolver. Connecting directly (bypassing the modality client) keeps the
    poll from firing the once-per-process version-mismatch probe each round.

    Args:
        socket_path: Explicit UDS path to wait on, or ``None`` to resolve it
            on each attempt.
        timeout: Maximum seconds to wait. ``None`` waits indefinitely;
            ``<= 0`` makes a single attempt.
        interval: Seconds to sleep between attempts (clamped so the wait
            never overshoots ``timeout``).

    Returns:
        The resolved UDS path that answered the ping.

    Raises:
        TimeoutError: ``timeout`` elapsed before a ping succeeded.
        AmbiguousSocketError: Multiple live sockets matched and no explicit
            path was given — waiting cannot disambiguate, so it propagates.
        grpclib.exceptions.GRPCError: The server answered with a
            non-retryable status. ``FAILED_PRECONDITION`` means "not ready
            yet" and is retried; every other status propagates.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    last_exc: Exception | None = None
    while True:
        try:
            path = socket_path or resolve_socket_path()
            channel = Channel(path=path)
            try:
                await ConnectionStub(channel).ping(PingRequest(message="wait"))
            finally:
                channel.close()
            return path
        except SocketNotFoundError as exc:
            last_exc = exc
        except OSError as exc:
            last_exc = exc
        except GRPCError as exc:
            if exc.status is not Status.FAILED_PRECONDITION:
                raise
            last_exc = exc

        if deadline is None:
            await asyncio.sleep(interval)
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Resonite IO socket did not become ready in "
                f"{timeout:.3f}s (last attempt: {last_exc})"
            ) from last_exc
        await asyncio.sleep(min(interval, remaining))
