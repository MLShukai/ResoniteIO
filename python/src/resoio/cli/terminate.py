"""``resoio terminate`` subcommand: stop Resonite by killing its processes.

Sends ``SIGTERM`` (then ``SIGKILL`` after a grace period) to the engine and
renderer processes. Takes the ``resonite_pid`` and ``renderer_pid`` printed by
``resoio launch``; with no PIDs it auto-detects the single running instance.
This is the forceful counterpart to ``resoio shutdown`` (the cooperative gRPC
quit) — use it to guarantee the client is stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``terminate`` subparser on the top-level parser."""
    parser = subparsers.add_parser(
        "terminate",
        parents=[common],
        help="Stop Resonite by killing the engine + renderer (SIGTERM -> SIGKILL).",
        description=(
            "Force-stop the Resonite client by signalling its engine and renderer "
            "processes. Pass the resonite_pid and renderer_pid printed by "
            "'resoio launch', or pass neither to auto-detect the single running "
            "instance. Idempotent (already-dead PIDs are skipped); detecting more "
            "than one instance is an error. For a cooperative quit use "
            "'resoio shutdown' instead."
        ),
    )
    parser.add_argument(
        "resonite_pid",
        nargs="?",
        type=int,
        default=None,
        help="Engine host PID to kill (resonite_pid from 'resoio launch').",
    )
    parser.add_argument(
        "renderer_pid",
        nargs="?",
        type=int,
        default=None,
        help="Renderer host PID to kill (renderer_pid from 'resoio launch').",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="Seconds to wait after SIGTERM before SIGKILL (default: 3).",
    )
    parser.set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Mixing one explicit PID with auto-detection is ambiguous: require both or
    # neither (neither = auto-detect the single running instance).
    if (args.resonite_pid is None) != (args.renderer_pid is None):
        print(
            "error: pass both resonite_pid and renderer_pid, or neither "
            "(neither auto-detects the running instance).",
            file=sys.stderr,
        )
        return 2

    # Defer the heavy import (psutil) to keep `resoio --help` fast.
    from resoio.launcher import LauncherError, terminate

    try:
        result = await asyncio.to_thread(
            terminate, args.resonite_pid, args.renderer_pid, timeout=args.timeout
        )
    except LauncherError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if result.resonite_pid == 0 and result.renderer_pid == 0:
        print("resonite not running")
        return 0
    if result.resonite_pid:
        print(f"resonite_pid={result.resonite_pid}")
    if result.renderer_pid:
        print(f"renderer_pid={result.renderer_pid}")
    return 0
