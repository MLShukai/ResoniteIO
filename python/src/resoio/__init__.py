"""resoio: Python client for Resonite IO."""

from importlib.metadata import version as _version

from resoio.camera import CameraClient, Frame
from resoio.connection import (
    AmbiguousSocketError,
    ConnectionClient,
    SocketNotFoundError,
)
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
    LocomotionCmd,
    ResetSummary,
)
from resoio.manipulation import GrabResult, GrabState, ManipulationClient
from resoio.microphone import (
    MicrophoneAudioChunk,
    MicrophoneClient,
    MicrophoneStreamSummary,
)
from resoio.speaker import (
    CHANNELS,
    DTYPE,
    SAMPLE_RATE,
    AudioChunk,
    SpeakerClient,
)
from resoio.world import (
    OpenWorld,
    RecordPage,
    RecordSort,
    RecordSortDirection,
    RecordSource,
    SessionFilter,
    SessionPage,
    Thumbnail,
    WorldClient,
    WorldRecord,
    WorldSession,
)

# Distribution name on PyPI is `resonite-io`; the import package is `resoio`.
__version__: str = _version("resonite-io")

__all__ = [
    "CHANNELS",
    "DTYPE",
    "SAMPLE_RATE",
    "AmbiguousSocketError",
    "AudioChunk",
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
    "Frame",
    "GrabResult",
    "GrabState",
    "InventoryClient",
    "InventoryEntry",
    "InventoryEntryKind",
    "InventoryListing",
    "InventoryMutationResult",
    "InventorySpawnResult",
    "LocomotionClient",
    "LocomotionCmd",
    "ManipulationClient",
    "MicrophoneAudioChunk",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "OpenWorld",
    "RecordPage",
    "RecordSort",
    "RecordSortDirection",
    "RecordSource",
    "ResetSummary",
    "SessionFilter",
    "SessionPage",
    "SocketNotFoundError",
    "SpeakerClient",
    "Thumbnail",
    "WorldClient",
    "WorldRecord",
    "WorldSession",
    "__version__",
]
