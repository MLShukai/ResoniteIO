"""Client for the Resonite IO ``Display`` unary RPCs (window resolution + fps
cap)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    DisplayConfig,
    DisplayGetRequest,
    DisplayState,
    DisplayStub,
)

__all__ = [
    "DisplayClient",
    "DisplayInfo",
]

_logger = logging.getLogger("resoio.display")


@dataclass(frozen=True, slots=True)
class DisplayInfo:
    """Snapshot of engine-side display settings.

    ``max_fps`` is the *background* fps cap; foreground control is not
    exposed by the engine public Settings API.
    """

    width: int
    height: int
    max_fps: float


def _info_from_state(state: DisplayState) -> DisplayInfo:
    return DisplayInfo(
        width=state.width,
        height=state.height,
        max_fps=state.max_fps,
    )


class DisplayClient(_BaseClient[DisplayStub]):
    """Async client for the Resonite IO ``Display`` service over a UDS.

    Use as an async context manager so the gRPC channel closes
    deterministically.
    """

    _logger = _logger
    _log_label = "Display"

    @override
    def _make_stub(self, channel: Channel) -> DisplayStub:
        return DisplayStub(channel)

    async def apply(
        self,
        *,
        width: int = 0,
        height: int = 0,
        max_fps: float = 0.0,
    ) -> None:
        """Apply a partial display config; ``0`` / ``0.0`` mean "leave
        unchanged".

        Returns ``None`` by contract — engine settings dispatch hops to the
        engine thread, so the post-apply snapshot is not reliable in the
        same RPC. Call :meth:`get` afterwards if you need the new state
        (see ``display.proto`` for the full rationale).
        """
        stub = self._require_stub()
        request = DisplayConfig(width=width, height=height, max_fps=max_fps)
        await stub.apply(request)

    async def get(self) -> DisplayInfo:
        """Return the engine-side display state without modifying it."""
        stub = self._require_stub()
        state = await stub.get(DisplayGetRequest())
        return _info_from_state(state)
