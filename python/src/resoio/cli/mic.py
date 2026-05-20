"""``resoio mic`` subcommand: stream mono audio into the Resonite mic input.

The wire format is fixed at 48 kHz / Mono / float32 LE (see
:mod:`resoio.microphone`); inputs that do not already match are
converted where lossless (stereo → mono via average, int16 → float32
normalisation) or rejected. There is no resampler — sample rate ≠ 48000
is an error; pipe through ``ffmpeg`` and use ``-i -`` for raw PCM.

Frames are chunked at 1024 samples each (~21.3 ms at 48 kHz). The
remainder shorter than a full chunk at EOF is dropped rather than
zero-padded so the wire never carries silence the caller did not
provide.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from collections.abc import AsyncIterator
from typing import IO, TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from resoio.microphone import DTYPE, SAMPLE_RATE, MicrophoneAudioChunk

if TYPE_CHECKING:
    from resoio.microphone import MicrophoneStreamSummary


# ~21.3 ms per frame at 48 kHz. Close to the 20 ms Opus encoder frame
# default; the engine re-frames anyway, so the wire boundary stays clean.
_CHUNK_SAMPLES = 1024

_BRIDGE_READY_TIMEOUT_S = 120.0
_BRIDGE_READY_RETRY_INTERVAL_S = 2.0


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``mic`` subparser on the top-level parser."""
    parser = subparsers.add_parser(
        "mic",
        parents=[common],
        help="Stream mono audio into the Resonite microphone input.",
        description=(
            "Open a Microphone stream over the Resonite IO UDS and push the "
            "samples of a WAV file (or raw float32 LE mono PCM on stdin) as "
            "the local user's voice. The wire format is fixed at "
            "48 kHz / Mono / float32 LE; mismatched sample rates are rejected."
        ),
    )
    parser.add_argument(
        "-i",
        "--input",
        default="-",
        dest="input",
        help=(
            'Input audio source. A path to a ``.wav`` file, or "-" to read '
            'raw float32 LE mono PCM from stdin (default: "-").'
        ),
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help=(
            "Stop after this many seconds of audio (default: stream until "
            "EOF or end of file)."
        ),
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        dest="no_wait",
        help=(
            "Skip the Bridge-ready retry loop (default: retry "
            f"FAILED_PRECONDITION for up to {_BRIDGE_READY_TIMEOUT_S:.0f}s)."
        ),
    )
    parser.set_defaults(func=_run)


class _InputFormatError(Exception):
    """Distinct exception so ``_run`` can map format issues to rc=2 (vs
    rc=1)."""


def _load_wav(path: str) -> NDArray[np.float32]:
    """Load a WAV file and return mono float32 samples in ``[-1.0, 1.0]``.

    Stereo is down-mixed via ``(L+R)/2``; > 2 channels is rejected (no
    canonical down-mix for arbitrary layouts). Sample rate ≠ 48000 is
    rejected to keep this CLI free of a resampler dependency.
    """
    with wave.open(path, "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        n_frames = wav.getnframes()
        raw = wav.readframes(n_frames)

    if sample_rate != SAMPLE_RATE:
        raise _InputFormatError(
            f"sample rate {sample_rate} Hz is unsupported "
            f"(expected {SAMPLE_RATE} Hz). Resample upstream, e.g. "
            f"`ffmpeg -i in.wav -ar 48000 -ac 1 -f f32le - | resoio mic -i -`."
        )

    if channels > 2:
        raise _InputFormatError(
            f"channel count {channels} is unsupported (mono or stereo only)."
        )

    if sampwidth == 4:
        # stdlib ``wave`` cannot distinguish int32 from float32 (it only
        # reports byte width); commit to float32 so ffmpeg output works
        # out of the box.
        samples = np.frombuffer(raw, dtype=np.float32)
    elif sampwidth == 2:
        int16 = np.frombuffer(raw, dtype=np.int16)
        samples = int16.astype(np.float32) / 32768.0
    else:
        raise _InputFormatError(
            f"unsupported sample width {sampwidth} bytes "
            f"(only 2 = int16 and 4 = float32 are accepted)."
        )

    if channels == 2:
        samples = samples.reshape(-1, 2).mean(axis=1, dtype=np.float32)

    return samples.astype(DTYPE, copy=False)


async def _wait_for_bridge_ready(
    socket_path: str | None,
    timeout_s: float = _BRIDGE_READY_TIMEOUT_S,
    interval_s: float = _BRIDGE_READY_RETRY_INTERVAL_S,
) -> None:
    """Block until ``Microphone.StreamAudio`` accepts an empty stream.

    Sends an empty client-streaming call and treats ``FAILED_PRECONDITION``
    as a retry signal; any other status propagates immediately.
    """
    import time

    import grpclib.exceptions
    from grpclib.const import Status

    from resoio.microphone import MicrophoneClient

    deadline = time.monotonic() + timeout_s
    while True:
        try:
            async with MicrophoneClient(socket_path) as client:

                async def _empty() -> AsyncIterator[MicrophoneAudioChunk]:
                    return
                    yield  # pragma: no cover — marks this a generator

                await client.stream(_empty())
            return
        except grpclib.exceptions.GRPCError as exc:
            if exc.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"microphone bridge did not become ready in "
                    f"{timeout_s:.0f}s (last reason: {exc.message})"
                ) from exc
            await asyncio.sleep(interval_s)


def _iter_wav_chunks(
    samples: NDArray[np.float32],
    max_samples: int | None,
) -> AsyncIterator[MicrophoneAudioChunk]:
    """Slice a pre-loaded mono buffer into ``_CHUNK_SAMPLES``-sized frames.

    Trailing remainder shorter than a full chunk is dropped, not zero-
    padded — never inject silence the caller did not request.
    """

    if max_samples is not None:
        samples = samples[:max_samples]
    total = samples.shape[0]
    full_chunks = total // _CHUNK_SAMPLES

    async def _gen() -> AsyncIterator[MicrophoneAudioChunk]:
        for i in range(full_chunks):
            start = i * _CHUNK_SAMPLES
            end = start + _CHUNK_SAMPLES
            yield MicrophoneAudioChunk(
                samples=samples[start:end].astype(DTYPE, copy=False),
                frame_id=i,
            )

    return _gen()


def _iter_stdin_chunks(
    stream: IO[bytes],
    max_samples: int | None,
) -> AsyncIterator[MicrophoneAudioChunk]:
    """Read raw float32 LE mono PCM from ``stream`` in 1024-sample frames.

    Reads run inside ``asyncio.to_thread`` so the event loop keeps
    pumping the concurrent gRPC stream. EOF short reads are dropped (no
    zero-pad) — same contract as :func:`_iter_wav_chunks`.
    """
    chunk_bytes = _CHUNK_SAMPLES * DTYPE.itemsize

    async def _gen() -> AsyncIterator[MicrophoneAudioChunk]:
        frame_id = 0
        samples_emitted = 0
        while True:
            if max_samples is not None and samples_emitted >= max_samples:
                return
            remaining_bytes = chunk_bytes
            if max_samples is not None:
                remaining_samples = max_samples - samples_emitted
                remaining_bytes = min(chunk_bytes, remaining_samples * DTYPE.itemsize)
            data: bytes = await asyncio.to_thread(stream.read, remaining_bytes)
            if len(data) < remaining_bytes:
                return  # EOF or short pipe read — drop the partial tail.
            samples = np.frombuffer(data, dtype=DTYPE)
            yield MicrophoneAudioChunk(
                samples=samples,
                frame_id=frame_id,
            )
            frame_id += 1
            samples_emitted += samples.shape[0]

    return _gen()


async def _run(args: argparse.Namespace) -> int:
    """Open a Microphone stream and push samples from WAV file or stdin.

    Format / argument errors → rc=2; broken stdin pipe → rc=0; other
    unexpected exceptions propagate (entry point maps them to rc=1).
    """
    # Deferred to keep ``resoio --help`` and shell completion fast.
    import grpclib.exceptions

    from resoio.microphone import MicrophoneClient

    source: str = args.input
    duration: float | None = args.duration
    max_samples: int | None = (
        int(duration * SAMPLE_RATE) if duration is not None else None
    )

    if not args.no_wait:
        try:
            await _wait_for_bridge_ready(args.socket)
        except TimeoutError as exc:
            print(f"microphone bridge not ready: {exc}", file=sys.stderr)
            return 1
        except grpclib.exceptions.GRPCError as exc:
            print(
                f"microphone bridge error: {exc.status.name} {exc.message}",
                file=sys.stderr,
            )
            return 1

    try:
        chunks: AsyncIterator[MicrophoneAudioChunk]
        if source == "-":
            chunks = _iter_stdin_chunks(sys.stdin.buffer, max_samples)
        else:
            samples = _load_wav(source)
            chunks = _iter_wav_chunks(samples, max_samples)
    except _InputFormatError as exc:
        print(f"resoio mic: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"resoio mic: input not found: {exc}", file=sys.stderr)
        return 2
    except wave.Error as exc:
        print(f"resoio mic: WAV parse error: {exc}", file=sys.stderr)
        return 2

    summary: MicrophoneStreamSummary
    try:
        async with MicrophoneClient(args.socket) as client:
            summary = await client.stream(chunks)
    except BrokenPipeError:
        # Upstream closed stdin mid-stream (e.g. ``head -c N | resoio mic -i -``).
        return 0
    except grpclib.exceptions.GRPCError as exc:
        print(
            f"resoio mic: stream failed: {exc.status.name} {exc.message}",
            file=sys.stderr,
        )
        return 1

    print(
        f"received_frames={summary.received_frames} "
        f"received_samples={summary.received_samples} "
        f"dropped_frames={summary.dropped_frames} "
        f"unix_nanos={summary.unix_nanos}",
        file=sys.stderr,
    )
    return 0
