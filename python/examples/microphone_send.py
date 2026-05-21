"""Minimal Microphone streaming example.

Generates a 440 Hz / 3 s mono sine via numpy and streams it as
1024-sample chunks to the Resonite IO virtual microphone. Select the
virtual mic in Resonite Settings -> Audio Input to hear the result.

Run from inside the dev container:

    uv run python python/examples/microphone_send.py
"""

import asyncio
import time
from collections.abc import AsyncIterator

import grpclib.exceptions
import numpy as np
from grpclib.const import Status

from resoio import DTYPE, SAMPLE_RATE, MicrophoneAudioChunk, MicrophoneClient
from resoio.microphone import paced

SOCKET_PATH: str | None = None
FREQ_HZ = 440.0
DURATION_S = 3.0
CHUNK_SAMPLES = 1024
AMPLITUDE = 0.3
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


def build_sine() -> np.ndarray:
    """Build a 1-D float32 sine in [-1, 1].

    samples must be 1-D float32 in [-1, 1]; MicrophoneClient does no
    dtype coercion.
    """
    n = int(DURATION_S * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    return (AMPLITUDE * np.sin(2 * np.pi * FREQ_HZ * t)).astype(DTYPE, copy=False)


async def iter_chunks(samples: np.ndarray) -> AsyncIterator[MicrophoneAudioChunk]:
    """Slice samples into 1024-sample chunks; trailing remainder is dropped.

    1024 samples ~ 21.3 ms matches the CLI default and the bridge's
    preferred frame size.
    """
    full_chunks = samples.shape[0] // CHUNK_SAMPLES
    for i in range(full_chunks):
        start = i * CHUNK_SAMPLES
        end = start + CHUNK_SAMPLES
        yield MicrophoneAudioChunk(samples=samples[start:end], frame_id=i)


async def wait_for_ready() -> None:
    """Block until Microphone.StreamAudio accepts an empty stream.

    Retries FAILED_PRECONDITION while the engine cold-boots.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with MicrophoneClient(SOCKET_PATH) as client:

                async def empty() -> AsyncIterator[MicrophoneAudioChunk]:
                    return
                    yield  # pragma: no cover - makes this a generator

                await client.stream(empty())
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Microphone did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    samples = build_sine()
    # paced() pre-yields then sleeps the natural chunk duration so the
    # bridge's 2 s ring buffer never overflows on multi-second inputs.
    async with MicrophoneClient(SOCKET_PATH) as client:
        summary = await client.stream(paced(iter_chunks(samples)))
    print(
        f"received_frames={summary.received_frames} "
        f"received_samples={summary.received_samples} "
        f"dropped_frames={summary.dropped_frames} "
        f"unix_nanos={summary.unix_nanos}"
    )


if __name__ == "__main__":
    asyncio.run(main())
