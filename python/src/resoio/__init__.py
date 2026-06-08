"""resoio: Python client for Resonite IO."""

from importlib.metadata import version as _version

from resoio._client import AmbiguousSocketError, SocketNotFoundError
from resoio.camera import CameraClient, Frame
from resoio.connection import ConnectionClient
from resoio.context_menu import (
    ContextMenuClient,
    ContextMenuItem,
    ContextMenuState,
)
from resoio.cursor import CursorClient, CursorState
from resoio.dash import (
    DashActionResult,
    DashClient,
    DashElement,
    DashRect,
    DashScreen,
    DashState,
    DashTree,
)
from resoio.display import DisplayClient, DisplayInfo
from resoio.inventory import (
    InventoryClient,
    InventoryEntry,
    InventoryEntryKind,
    InventoryListing,
    InventoryMutationResult,
    InventorySpawnResult,
)
from resoio.locomotion import (
    DriveSummary,
    LocomotionClient,
    ResetSummary,
)
from resoio.manipulation import GrabResult, GrabState, ManipulationClient
from resoio.microphone import (
    MicrophoneClient,
    MicrophoneStreamSummary,
)
from resoio.speaker import SpeakerChunk, SpeakerClient
from resoio.world import (
    FetchThumbnailResponse,
    ListRecordsResponse,
    ListSessionsResponse,
    OpenWorld,
    RecordSort,
    RecordSortDirection,
    RecordSource,
    SessionFilter,
    WorldClient,
    WorldRecord,
    WorldSession,
)

# Distribution name on PyPI is `resonite-io`; the import package is `resoio`.
__version__: str = _version("resonite-io")

__all__ = [
    "AmbiguousSocketError",
    "CameraClient",
    "ConnectionClient",
    "ContextMenuClient",
    "ContextMenuItem",
    "ContextMenuState",
    "CursorClient",
    "CursorState",
    "DashActionResult",
    "DashClient",
    "DashElement",
    "DashRect",
    "DashScreen",
    "DashState",
    "DashTree",
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "FetchThumbnailResponse",
    "Frame",
    "GrabResult",
    "GrabState",
    "InventoryClient",
    "InventoryEntry",
    "InventoryEntryKind",
    "InventoryListing",
    "InventoryMutationResult",
    "InventorySpawnResult",
    "ListRecordsResponse",
    "ListSessionsResponse",
    "LocomotionClient",
    "ManipulationClient",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "OpenWorld",
    "RecordSort",
    "RecordSortDirection",
    "RecordSource",
    "ResetSummary",
    "SessionFilter",
    "SocketNotFoundError",
    "SpeakerChunk",
    "SpeakerClient",
    "WorldClient",
    "WorldRecord",
    "WorldSession",
    "__version__",
]
