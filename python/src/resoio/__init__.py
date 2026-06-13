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
    DashAmbiguousMatchError,
    DashClient,
    DashControl,
    DashNoMatchError,
    DashState,
    DashTab,
)
from resoio.display import DisplayClient, DisplayInfo
from resoio.grabber import GrabberClient, GrabResult, GrabState
from resoio.info import ServerInfo, ServerPlatform, get_server_info
from resoio.inventory import (
    InventoryClient,
    InventoryEntry,
    InventoryEntryKind,
    InventoryListing,
    InventoryMutationResult,
    InventorySpawnResult,
    InventoryThumbnail,
)
from resoio.lifecycle import LifecycleClient, terminate
from resoio.locomotion import (
    DriveSummary,
    LocomotionClient,
    ResetSummary,
)
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
    "DashAmbiguousMatchError",
    "DashClient",
    "DashControl",
    "DashNoMatchError",
    "DashState",
    "DashTab",
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "FetchThumbnailResponse",
    "Frame",
    "GrabResult",
    "GrabState",
    "GrabberClient",
    "InventoryClient",
    "InventoryEntry",
    "InventoryEntryKind",
    "InventoryListing",
    "InventoryMutationResult",
    "InventorySpawnResult",
    "InventoryThumbnail",
    "LifecycleClient",
    "ListRecordsResponse",
    "ListSessionsResponse",
    "LocomotionClient",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "OpenWorld",
    "RecordSort",
    "RecordSortDirection",
    "RecordSource",
    "ResetSummary",
    "ServerInfo",
    "ServerPlatform",
    "SessionFilter",
    "SocketNotFoundError",
    "SpeakerChunk",
    "SpeakerClient",
    "WorldClient",
    "WorldRecord",
    "WorldSession",
    "__version__",
    "get_server_info",
    "terminate",
]
