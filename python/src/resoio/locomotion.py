"""Client for the Resonite IO ``Locomotion`` gRPC streaming service."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from grpclib.client import Channel

from resoio._generated.resonite_io.v1 import (
    LocomotionCommand,
    LocomotionStub,
)
from resoio._socket import resolve_socket_path

__all__ = [
    "DriveSummary",
    "LocomotionClient",
    "LocomotionCmd",
]

_logger = logging.getLogger("resoio.locomotion")


@dataclass(frozen=True, slots=True)
class LocomotionCmd:
    """One desktop-style locomotion command (Python API view).

    ``velocity`` defaults to ``1.0`` (the multiplicative identity) so a
    bare ``LocomotionCmd(move_y=1.0)`` walks at the engine's natural
    speed; the server multiplies ``Move`` by this scalar verbatim.
    ``pitch_rate`` is "up = positive" (the bridge handles the engine's
    sign flip). Other field semantics are canonical in
    ``proto/resonite_io/v1/locomotion.proto``.
    """

    move_x: float = 0.0
    move_y: float = 0.0
    yaw_rate: float = 0.0
    pitch_rate: float = 0.0
    jump: bool = False
    velocity: float = 1.0
    crouch: float = 0.0


@dataclass(frozen=True, slots=True)
class DriveSummary:
    """Server-side summary returned when a ``Drive`` stream ends.

    ``dropped_count`` is reserved for a future non-blocking bridge and
    is always ``0`` today.
    """

    received_count: int
    dropped_count: int
    unix_nanos: int


class LocomotionClient:
    """Async client for the Resonite IO ``Locomotion`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.SessionClient`.
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: LocomotionStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        _logger.debug("Opening Locomotion channel on UDS path: %s", path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = LocomotionStub(channel)
        self._resolved_path = path
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        channel = self._channel
        self._channel = None
        self._stub = None
        self._resolved_path = None
        if channel is not None:
            channel.close()

    async def drive(self, commands: AsyncIterable[LocomotionCmd]) -> DriveSummary:
        """Stream locomotion commands to the server and await the summary.

        ``unix_nanos`` is stamped here at send time (callers do not set it
        on :class:`LocomotionCmd`). gRPC-level failures (e.g.
        ``FAILED_PRECONDITION`` while the engine bridge is not ready)
        surface as :class:`grpclib.exceptions.GRPCError`.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "LocomotionClient is not connected. "
                "Use `async with LocomotionClient(): ...`."
            )

        async def _wire() -> AsyncIterator[LocomotionCommand]:
            async for cmd in commands:
                yield LocomotionCommand(
                    move_x=cmd.move_x,
                    move_y=cmd.move_y,
                    yaw_rate=cmd.yaw_rate,
                    pitch_rate=cmd.pitch_rate,
                    jump=cmd.jump,
                    velocity=cmd.velocity,
                    crouch=cmd.crouch,
                    unix_nanos=time.time_ns(),
                )

        summary = await stub.drive(_wire())
        return DriveSummary(
            received_count=summary.received_count,
            dropped_count=summary.dropped_count,
            unix_nanos=summary.unix_nanos,
        )
