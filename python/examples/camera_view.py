"""Minimal Camera stream example.

Streams RGBA frames for DURATION_S seconds, then prints the achieved
fps and basic luminance statistics of the final frame. No frames are
written to disk; numpy is the only non-stdlib dependency. Assumes a
Resonite client with the ResoniteIO mod loaded is running on the host.

Run from inside the dev container:

    uv run python python/examples/camera_view.py
"""

import asyncio
import time

import grpclib.exceptions
import numpy as np
from grpclib.const import Status

from resoio import CameraClient, Frame

SOCKET_PATH: str | None = None
DURATION_S = 5.0
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until the Camera bridge yields a frame.

    Cold-boot gap between UDS bind and LocalUser/FocusedWorld attach
    surfaces as FAILED_PRECONDITION; retry until ``READY_TIMEOUT_S``.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with CameraClient(SOCKET_PATH) as cam:
                await cam.shot()
                return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Camera did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    count = 0
    last: Frame | None = None
    t0 = 0.0
    elapsed = 0.0
    async with CameraClient(SOCKET_PATH) as client:
        async for frame in client.stream():
            if count == 0:
                t0 = time.monotonic()
            last = frame
            count += 1
            elapsed = time.monotonic() - t0
            if elapsed >= DURATION_S:
                break

    fps = count / elapsed if elapsed > 0 else 0.0
    print(f"frames={count} elapsed_s={elapsed:.3f} fps={fps:.2f}")
    if last is not None:
        # frame.pixels is a read-only RGBA8 view; row 0 is the image
        # top. astype(float32) makes a writable copy for arithmetic.
        rgb = last.pixels[..., :3].astype(np.float32)
        lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
        print(
            f"shape={last.pixels.shape} dtype={last.pixels.dtype} "
            f"lum_min={lum.min():.2f} lum_max={lum.max():.2f} "
            f"lum_mean={lum.mean():.2f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
