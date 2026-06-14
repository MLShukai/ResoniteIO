"""Client for the Resonite IO ``Lifecycle`` modality (graceful shutdown).

A single unary RPC: ``shutdown`` asks the running engine to quit gracefully
(FrooxEngine ``Engine.RequestShutdown``), the same path the in-app Quit button
takes. The engine schedules the shutdown on its update thread and ACKs
immediately, then exits asynchronously — the RPC does not wait for the process
to die. Steam/Proton reaps the renderer and launch wrappers when the engine
exits, so a graceful shutdown is sufficient to stop the whole client; no OS
signals are sent. The :func:`shutdown` convenience wraps this with PID
reporting (``terminate`` is its deprecated former name).
"""

from __future__ import annotations

import logging
import warnings
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    LifecycleStub,
    ShutdownRequest,
    ShutdownResponse,
)

__all__ = [
    "LifecycleClient",
    "shutdown",
    "terminate",
]

_logger = logging.getLogger(__name__)


class LifecycleClient(_BaseClient[LifecycleStub]):
    """Async client for the Resonite IO ``Lifecycle`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. With ``socket_path=None`` the path is resolved on
    ``__aenter__`` via ``RESONITE_IO_SOCKET`` →
    ``RESONITE_IO_SOCKET_DIR`` → ``~/.resonite-io/``; resolution may
    raise :class:`SocketNotFoundError` or :class:`AmbiguousSocketError`.
    """

    _logger = _logger
    _log_label = "Lifecycle"

    @override
    def _make_stub(self, channel: Channel) -> LifecycleStub:
        return LifecycleStub(channel)

    async def shutdown(self) -> ShutdownResponse:
        """Ask the engine to quit gracefully and return the ACK.

        The engine schedules ``Engine.RequestShutdown`` on its update thread
        and ACKs before the process tears down, so this returns promptly. It
        does **not** wait for the engine to exit; poll liveness (e.g. via
        :class:`resoio.ConnectionClient`) if you need to confirm the process is
        gone, or use :func:`shutdown` for a one-call stop that also reports the
        engine PID.

        Returns:
            The :class:`ShutdownResponse` whose ``accepted`` is ``True`` when
            the shutdown was scheduled, or ``False`` when the engine had already
            begun shutting down (idempotent no-op).

        Raises:
            grpclib.exceptions.GRPCError: The RPC failed at the transport or
                server layer. Note that the connection may drop right after a
                successful schedule as the engine exits — callers that only want
                "make it stop" can treat a post-ACK disconnect as success.
        """
        stub = self._require_stub()
        return await stub.shutdown(ShutdownRequest())


async def shutdown(*, socket_path: str | None = None) -> int | None:
    """Stop the running Resonite client gracefully and return the engine's PID.

    Reads the engine's host PID from the ``Info`` RPC (for reporting), then
    sends ``Lifecycle.Shutdown``. The engine schedules its own shutdown and
    exits asynchronously; Steam/Proton reaps the renderer and launch wrappers,
    so no OS signals are needed. Because this is a pure gRPC call it works from
    anywhere the UDS is reachable (no host-native requirement).

    Args:
        socket_path: Explicit UDS path for the ``Info`` / ``Lifecycle`` RPCs;
            ``None`` resolves it via the usual env order.

    Returns:
        The engine's host PID, or ``None`` when no engine was reachable.
    """
    # Lazy import keeps the module import graph acyclic (info pulls in _client).
    from resoio.info import get_server_info

    try:
        pid = (await get_server_info(socket_path)).resonite_pid
    except Exception as exc:
        _logger.info("No reachable Resonite engine to shut down (%s).", exc)
        return None

    try:
        async with LifecycleClient(socket_path) as client:
            outcome = await client.shutdown()
        _logger.info("Lifecycle.Shutdown accepted=%s", outcome.accepted)
    except Exception as exc:
        # The engine commonly drops the connection as it exits right after
        # ACKing the schedule — benign. We already have the PID to report.
        _logger.info("Lifecycle.Shutdown connection ended (%s); engine exiting.", exc)

    return pid or None


async def terminate(*, socket_path: str | None = None) -> int | None:
    """Deprecated former name of :func:`shutdown`.

    Renamed to :func:`shutdown` to match Resonite's terminology and the
    ``Lifecycle.Shutdown`` RPC. This alias still forwards to :func:`shutdown`
    but is **no longer maintained** and will be removed in a future release;
    migrate to :func:`shutdown`.

    .. deprecated::
        Use :func:`shutdown` instead.

    Args:
        socket_path: Forwarded to :func:`shutdown`.

    Returns:
        The engine's host PID, or ``None`` when no engine was reachable.
    """
    warnings.warn(
        "resoio.terminate is deprecated and no longer maintained; use "
        "resoio.shutdown instead. It will be removed in a future release.",
        DeprecationWarning,
        stacklevel=2,
    )
    return await shutdown(socket_path=socket_path)
