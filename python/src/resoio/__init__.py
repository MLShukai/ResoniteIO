"""resoio: Python client for Resonite IO."""

from importlib.metadata import version as _version

from resoio.camera import CameraClient, Frame
from resoio.display import DisplayClient, DisplayInfo
from resoio.locomotion import (
    DriveSummary,
    LocomotionClient,
    LocomotionCmd,
    ResetSummary,
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
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "Frame",
    "LocomotionClient",
    "LocomotionCmd",
    "ResetSummary",
    "SessionClient",
    "SocketNotFoundError",
    "SpeakerClient",
    "__version__",
]
