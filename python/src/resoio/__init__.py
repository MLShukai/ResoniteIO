"""resoio: Python client for Resonite IO."""

from importlib.metadata import version as _version

from resoio.camera import CameraClient, Frame
from resoio.display import DisplayClient, DisplayInfo
from resoio.locomotion import DriveSummary, LocomotionClient, LocomotionCmd
from resoio.session import (
    AmbiguousSocketError,
    SessionClient,
    SocketNotFoundError,
)

__version__: str = _version("resoio")

__all__ = [
    "AmbiguousSocketError",
    "CameraClient",
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "Frame",
    "LocomotionClient",
    "LocomotionCmd",
    "SessionClient",
    "SocketNotFoundError",
    "__version__",
]
