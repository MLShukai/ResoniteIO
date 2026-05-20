"""``resoio mic`` subcommand: stream mono audio into the Resonite mic input.

Symmetric counterpart of :mod:`resoio.cli.record` (which records Speaker
output). The wire format is fixed at 48 kHz / Mono / float32 LE
(see :mod:`resoio.microphone`); inputs that do not already match are
either converted (stereo down-mix, int16 → float32 normalisation) or
rejected with a clear error.

Input modes:

* ``-i <path.wav>``: parse a WAV file with stdlib :mod:`wave`. Accepted:
  ``sampwidth == 4`` (treated as float32 — note the stdlib gives no way
  to distinguish int32 from float32, so we deliberately assume float32
  here; format probing is left to a future pass) and ``sampwidth == 2``
  (int16, normalised to float32 by dividing by ``32768.0``). Mono is
  passed through, stereo is averaged to mono, > 2 channels is rejected.
  Sample rate ≠ 48000 is rejected (no resampler — use
  ``ffmpeg ... | resoio mic -i -``).
* ``-i -``: read raw float32 LE mono PCM from stdin. No header, no
  validation — the caller is responsible for the format.

Frames are chunked at 1024 samples each (≈ 21.3 ms at 48 kHz). The
remainder shorter than a full chunk at EOF is discarded rather than
zero-padded to keep frame boundaries clean on the server side.
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


# 1024 samples ≈ 21.3 ms per frame at 48 kHz. Close enough to the 20 ms
# Opus encoder frame default (the engine re-frames anyway) that no
# alignment headache crosses the wire boundary.
_CHUNK_SAMPLES = 1024

_BRIDGE_READY_TIMEOUT_S = 120.0
_BRIDGE_READY_RETRY_INTERVAL_S = 2.0


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``mic`` subparser on the top-level parser.

    Flat command (``resoio mic`` rather than nesting under a hypothetical
    ``resoio voice``) matches :mod:`resoio.cli.record` (the Speaker side)
    so the input/output symmetry is visible at the CLI surface.
    """
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
        required=True,
        dest="input",
        help=(
            'Input audio source. A path to a ``.wav`` file, or "-" to read '
            "raw float32 LE mono PCM from stdin."
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
    """Raised for user-facing input format problems (rc=2).

    Distinct from generic exceptions so the dispatcher knows whether to
    emit rc=2 (format) vs rc=1 (other). The message is surfaced to
    stderr verbatim.
    """


def _load_wav(path: str) -> NDArray[np.float32]:
    """Load a WAV file and return mono float32 samples in ``[-1.0, 1.0]``.

    See module docstring for the supported format envelope. Stereo is
    down-mixed via simple ``(L+R)/2`` average; > 2 channels is an error
    (no canonical down-mix for arbitrary layouts without losing spatial
    intent). Sample rate ≠ 48000 is an error rather than auto-resampled
    because adding a resampler dep (or rolling one) is out of scope for
    this CLI.
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
        # No reliable way to distinguish int32 vs float32 via stdlib
        # ``wave`` (it only reports byte width); we commit to float32
        # here so the common ffmpeg-produced output works out of the box.
        samples = np.frombuffer(raw, dtype=np.float32)
    elif sampwidth == 2:
        # int16 → float32 in [-1, 1). Division by 32768.0 keeps the most
        # negative int16 (-32768) on the [-1, 1] interval without
        # clipping the positive side.
        int16 = np.frombuffer(raw, dtype=np.int16)
        samples = int16.astype(np.float32) / 32768.0
    else:
        raise _InputFormatError(
            f"unsupported sample width {sampwidth} bytes "
            f"(only 2 = int16 and 4 = float32 are accepted)."
        )

    if channels == 2:
        # Interleaved L,R → ``(N, 2)`` → mono via mean over the channel axis.
        samples = samples.reshape(-1, 2).mean(axis=1, dtype=np.float32)

    # Force the canonical dtype so downstream callers can rely on it
    # without re-checking.
    return samples.astype(DTYPE, copy=False)


async def _wait_for_bridge_ready(
    socket_path: str | None,
    timeout_s: float = _BRIDGE_READY_TIMEOUT_S,
    interval_s: float = _BRIDGE_READY_RETRY_INTERVAL_S,
) -> None:
    """Block until ``Microphone.StreamAudio`` no longer raises
    ``FAILED_PRECONDITION``.

    Same shape as :func:`resoio.cli.locomotion._wait_for_bridge_ready`:
    open a fresh client, send an empty stream, and accept either a clean
    summary or ``FAILED_PRECONDITION`` as a retry signal. Anything else
    propagates immediately. The duplicate-of-locomotion form is
    deliberate per the implementation plan; consolidation is left to a
    later pass.
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
                    # An empty stream is enough to provoke the bridge's
                    # not-ready precondition without sending any samples.
                    return
                    yield  # pragma: no cover - unreachable, marks generator

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

    The trailing remainder shorter than ``_CHUNK_SAMPLES`` is dropped
    rather than zero-padded; padding would inject silence the caller
    didn't ask for. ``max_samples`` (from ``--duration``) caps the total
    output sample count and lands on the same chunk boundary.
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

    ``stream`` is the underlying binary buffer (e.g. ``sys.stdin.buffer``);
    a short read at EOF is discarded if it does not align to a full chunk
    so callers that need every last sample should zero-pad upstream.

    Reads run inside ``asyncio.to_thread`` so the event loop stays
    responsive (the gRPC stream is still being awaited concurrently).
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
                # EOF (or short read on a pipe). Drop the partial tail
                # rather than padding it with silence the user didn't
                # ask for.
                return
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

    Format / argument errors → rc=2 (+ stderr message). Broken pipe
    (downstream closed stdin) → rc=0. Any other unexpected exception
    propagates and the entry point translates it to rc=1.
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
        # stdin pipe closed mid-stream (e.g. ``head -c N | resoio mic -i -``).
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
