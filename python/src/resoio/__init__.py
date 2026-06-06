"""resoio: Python client for Resonite IO."""

from importlib.metadata import version as _version

from resoio.camera import CameraClient, Frame
from resoio.context_menu import (
    ContextMenuClient,
    ContextMenuItem,
    ContextMenuState,
)
from resoio.dash import (
    DashActionResult,
    DashClient,
    DashElement,
    DashRect,
    DashState,
    DashTree,
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
    "DashActionResult",
    "DashClient",
    "DashElement",
    "DashRect",
    "DashState",
    "DashTree",
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "Frame",
    "LocomotionClient",
    "LocomotionCmd",
    "MicrophoneAudioChunk",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "ResetSummary",
    "SessionClient",
    "SocketNotFoundError",
    "SpeakerClient",
    "__version__",
]
