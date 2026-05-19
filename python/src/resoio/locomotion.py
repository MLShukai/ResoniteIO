"""Client for the Resonite IO ``Locomotion`` gRPC streaming service.

The bridge on the mod side is a **stateful repeater**: the latest
command sent through :meth:`LocomotionClient.drive` is held and
re-injected into the engine every update tick. Callers therefore only
need to send a new command when something changes — no keep-alive
loop is required. Disconnect semantics are split:

* a graceful ``CompleteAsync`` (i.e. the request iterator closes
  cleanly) leaves the bridge state in place — the avatar keeps doing
  whatever the last command said;
* an ungraceful disconnect (Ctrl-C, UDS drop, gRPC cancellation)
  triggers a full reset on the bridge so the avatar returns to
  neutral;
* :meth:`LocomotionClient.reset` lets the client explicitly clear
  bridge state mid-stream.
"""

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
    LocomotionResetRequest,
    LocomotionStub,
)
from resoio._socket import resolve_socket_path

__all__ = [
    "DriveSummary",
    "LocomotionClient",
    "LocomotionCmd",
    "ResetSummary",
]

_logger = logging.getLogger("resoio.locomotion")


@dataclass(frozen=True, slots=True)
class LocomotionCmd:
    """Python-side ``LocomotionCommand`` with a 1.0 ``velocity`` default.

    The ``velocity=1.0`` default is the whole point of this wrapper:
    proto3 would otherwise send wire default ``0`` and the bridge —
    which multiplies ``Move`` by ``velocity`` literally — would stop
    the avatar. Field semantics (including the ``jump`` consume-once
    pulse) are canon in ``proto/resonite_io/v1/locomotion.proto``.
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
    is always ``0`` today (the bridge applies commands serially).
    """

    received_count: int
    dropped_count: int
    unix_nanos: int


@dataclass(frozen=True, slots=True)
class ResetSummary:
    """Server-side echo of the canonicalised reset request.

    Returned by :meth:`LocomotionClient.reset`. Each bool reflects the
    request after the service canonicalises it (an all-false request is
    expanded into all-true), not whether the engine has already applied
    the reset — application happens on the next engine tick.
    """

    move: bool
    look: bool
    crouch: bool
    jump: bool
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

        Push a new :class:`LocomotionCmd` only when state changes; the
        bridge repeats the last value every engine tick. Stream
        lifecycle and disconnect semantics are documented on the
        module docstring. ``unix_nanos`` is stamped here at send time;
        callers should not set it. gRPC failures surface as
        :class:`grpclib.exceptions.GRPCError`.
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

    async def reset(
        self,
        *,
        move: bool = False,
        look: bool = False,
        crouch: bool = False,
        jump: bool = False,
    ) -> ResetSummary:
        """Reset selected locomotion fields on the bridge.

        Each flag clears the corresponding group: ``move`` →
        ``move_x`` / ``move_y`` / ``velocity`` back to ``(0, 0, 1.0)``,
        ``look`` → ``yaw_rate`` / ``pitch_rate`` to ``0``, ``crouch``
        → ``0``, ``jump`` → drop an un-consumed pulse. Calling with all
        defaults (every flag ``False``) means "reset everything"; the
        service canonicalises that to all-true because proto3 cannot
        distinguish "unset" from "explicit false". The returned
        :class:`ResetSummary` echoes that canonicalised request. Safe
        to call concurrently with an in-flight :meth:`drive` stream.
        ``unix_nanos`` is stamped here at send time. gRPC failures
        surface as :class:`grpclib.exceptions.GRPCError`.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "LocomotionClient is not connected. "
                "Use `async with LocomotionClient(): ...`."
            )

        request = LocomotionResetRequest(
            move=move,
            look=look,
            crouch=crouch,
            jump=jump,
            unix_nanos=time.time_ns(),
        )
        summary = await stub.reset(request)
        return ResetSummary(
            move=summary.move,
            look=summary.look,
            crouch=summary.crouch,
            jump=summary.jump,
            unix_nanos=summary.unix_nanos,
        )
