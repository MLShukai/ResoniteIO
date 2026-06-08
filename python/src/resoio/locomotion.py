"""Client for the Resonite IO ``Locomotion`` gRPC streaming service.

The bridge on the mod side is a **stateful repeater**: it holds the full
locomotion state and re-injects it into the engine every update tick.
Callers therefore only need to send the fields that *changed* — a call to
:meth:`LocomotionClient.send` with some kwargs left as ``None`` omits those
fields on the wire and the bridge keeps its previous value for them. The
``velocity`` unit (``1.0``, normal walk) comes from the bridge's initial
state, so an avatar does not stop just because the first ``send()`` left
``velocity`` unset.

Disconnect semantics are split:

* a graceful close (the context manager exits) leaves the bridge state in
  place — the avatar keeps doing whatever the last command said;
* an ungraceful disconnect (Ctrl-C, UDS drop, gRPC cancellation) triggers a
  full reset on the bridge so the avatar returns to neutral;
* :meth:`LocomotionClient.reset` lets the client explicitly clear bridge
  state mid-stream.

The ``Drive`` RPC is client-streaming: the first :meth:`send` lazily opens
the stream and starts a background task draining an internal queue; the
:class:`DriveSummary` returned by the server is available from
:attr:`LocomotionClient.drive_summary` after the context manager exits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    LocomotionCommand,
    LocomotionResetRequest,
    LocomotionStub,
)

__all__ = [
    "DriveSummary",
    "LocomotionClient",
    "ResetSummary",
]

_logger = logging.getLogger(__name__)


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


class LocomotionClient(_BaseClient[LocomotionStub]):
    """Async client for the Resonite IO ``Locomotion`` service over a UDS.

    Use as an async context manager so the gRPC channel — and the
    ``Drive`` stream opened lazily by :meth:`send` — are closed
    deterministically. Socket resolution mirrors
    :class:`resoio.ConnectionClient`.
    """

    _logger = _logger
    _log_label = "Locomotion"

    @override
    def _make_stub(self, channel: Channel) -> LocomotionStub:
        return LocomotionStub(channel)

    def __init__(self, socket_path: str | None = None) -> None:
        super().__init__(socket_path)
        self._queue: asyncio.Queue[LocomotionCommand | None] = asyncio.Queue()
        self._drive_task: asyncio.Task[DriveSummary] | None = None
        self._drive_summary: DriveSummary | None = None

    @property
    def drive_summary(self) -> DriveSummary | None:
        """The :class:`DriveSummary` resolved after the context exits.

        ``None`` until the async context manager has exited (or if
        :meth:`send` was never called, so no ``Drive`` stream was opened).
        """
        return self._drive_summary

    async def send(
        self,
        *,
        move_forward: float | None = None,
        move_right: float | None = None,
        move_up: float | None = None,
        yaw_rate: float | None = None,
        pitch_rate: float | None = None,
        jump: bool | None = None,
        velocity: float | None = None,
        crouch: float | None = None,
    ) -> None:
        """Send a partial locomotion update to the bridge.

        Only the kwargs that are not ``None`` are set on the wire; omitted
        fields keep their previous value on the (stateful) bridge. The
        first call lazily opens the ``Drive`` client-streaming RPC and
        starts the background drain task; subsequent calls enqueue onto it.
        ``unix_nanos`` is stamped here at send time; callers should not set
        it. gRPC failures surface (from the awaited stream) as
        :class:`grpclib.exceptions.GRPCError` when the context exits.
        """
        command = LocomotionCommand(
            move_forward=move_forward,
            move_right=move_right,
            move_up=move_up,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            jump=jump,
            velocity=velocity,
            crouch=crouch,
            unix_nanos=time.time_ns(),
        )
        if self._drive_task is None:
            stub = self._require_stub()
            self._drive_task = asyncio.create_task(self._run_drive(stub))
        await self._queue.put(command)

    async def _run_drive(self, stub: LocomotionStub) -> DriveSummary:
        """Drain the queue into the ``Drive`` RPC and decode the summary."""
        summary = await stub.drive(self._queue_iter())
        return DriveSummary(
            received_count=summary.received_count,
            dropped_count=summary.dropped_count,
            unix_nanos=summary.unix_nanos,
        )

    async def _queue_iter(self) -> AsyncIterator[LocomotionCommand]:
        """Yield queued commands until the sentinel (``None``) is dequeued."""
        while True:
            command = await self._queue.get()
            if command is None:
                return
            yield command

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self._drive_task is not None:
                await self._queue.put(None)
                try:
                    self._drive_summary = await self._drive_task
                finally:
                    self._drive_task = None
        finally:
            # Always close the channel, even when awaiting the drive task
            # re-raises (e.g. a mid-stream GRPCError); otherwise the leaked
            # channel would outlive the context and stall teardown.
            await super().__aexit__(exc_type, exc, tb)

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
        ``move_forward`` / ``move_right`` / ``move_up`` / ``velocity``
        back to ``(0, 0, 0, 1.0)``, ``look`` → ``yaw_rate`` /
        ``pitch_rate`` to ``0``, ``crouch``
        → ``0``, ``jump`` → drop an un-consumed pulse. Calling with all
        defaults (every flag ``False``) means "reset everything"; the
        service canonicalises that to all-true because proto3 cannot
        distinguish "unset" from "explicit false". The returned
        :class:`ResetSummary` echoes that canonicalised request. Safe
        to call concurrently with an in-flight :meth:`send` stream.
        ``unix_nanos`` is stamped here at send time. gRPC failures
        surface as :class:`grpclib.exceptions.GRPCError`.
        """
        stub = self._require_stub()
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
