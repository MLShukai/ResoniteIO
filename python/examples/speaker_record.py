"""Minimal Speaker stream example.

Captures DURATION_S seconds of the Resonite final audio mix, prints
peak amplitude and chunk count, then writes the raw float32 LE samples
to ``speaker_output.raw`` next to this file. Decode with::

    ffplay -f f32le -ar 48000 -ac 2 speaker_output.raw

Assumes a Resonite client with the ResoniteIO mod loaded is running on
the host.

Run from inside the dev container:

    uv run python python/examples/speaker_record.py
"""

import asyncio
import time
from pathlib import Path

import grpclib.exceptions
import numpy as np
from grpclib.const import Status

from resoio import SpeakerClient
from resoio.speaker import CHANNELS, DTYPE, SAMPLE_RATE

SOCKET_PATH: str | None = None
DURATION_S = 5.0
OUTPUT_PATH = Path(__file__).with_name("speaker_output.raw")
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until Speaker yields one chunk.

    Cold-boot gap surfaces as FAILED_PRECONDITION (UDS bound before
    AudioSystem.PrimaryOutput is wired); retry until READY_TIMEOUT_S.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with SpeakerClient(SOCKET_PATH) as spk:
                async for _ in spk.stream():
                    return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Speaker did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    chunks: list[np.ndarray] = []
    t0 = 0.0
    async with SpeakerClient(SOCKET_PATH) as client:
        async for chunk in client.stream():
            if not chunks:
                t0 = time.monotonic()
            chunks.append(chunk.samples)
            if time.monotonic() - t0 >= DURATION_S:
                break

    # chunk.samples is (N, 2) float32 interleaved LR; concatenation
    # along axis 0 preserves the channel layout. tobytes() emits
    # native little-endian on all supported platforms (x86_64, arm64).
    samples = np.concatenate(chunks, axis=0)
    peak = float(np.max(np.abs(samples)))
    # Raw float32 LE on disk — no WAV header to keep stdlib-only;
    # decode with ffplay -f f32le -ar 48000 -ac 2.
    OUTPUT_PATH.write_bytes(samples.astype(DTYPE, copy=False).tobytes())
    print(
        f"chunks={len(chunks)} samples={samples.shape[0]} "
        f"seconds={samples.shape[0] / SAMPLE_RATE:.3f} "
        f"channels={CHANNELS} peak={peak:.6f} path={OUTPUT_PATH}"
    )


if __name__ == "__main__":
    asyncio.run(main())
