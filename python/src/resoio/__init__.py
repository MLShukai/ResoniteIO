"""resoio: Python client for Resonite IO."""

from importlib.metadata import version as _version

from resoio.camera import CameraClient, Frame
from resoio.context_menu import (
    ContextMenuClient,
    ContextMenuItem,
    ContextMenuState,
)
from resoio.display import DisplayClient, DisplayInfo
from resoio.locomotion import (
    DriveSummary,
    LocomotionClient,
    LocomotionCmd,
    ResetSummary,
)
from resoio.microphone import (
    MicrophoneAudioChunk,
    MicrophoneClient,
    MicrophoneStreamSummary,
)
from resoio.session import (
    AmbiguousSocketError,
    SessionClient,
    SocketNotFoundError,
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

__version__: str = _version("resoio")

__all__ = [
    "CHANNELS",
    "DTYPE",
    "SAMPLE_RATE",
    "AmbiguousSocketError",
    "AudioChunk",
    "CameraClient",
    "ContextMenuClient",
    "ContextMenuItem",
    "ContextMenuState",
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "Frame",
    "LocomotionClient",
    "LocomotionCmd",
    "MicrophoneAudioChunk",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "OpenWorld",
    "RecordPage",
    "RecordSort",
    "RecordSortDirection",
    "RecordSource",
    "ResetSummary",
    "SessionClient",
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
