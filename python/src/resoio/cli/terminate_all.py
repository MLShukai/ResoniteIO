"""``resoio terminate-all`` subcommand: stop every running Resonite instance.

The multi-instance counterpart to ``resoio terminate`` (which targets a single
instance). Detects all engine + renderer processes for the configured install
and stages ``SIGTERM`` -> ``SIGKILL`` on each, printing the engine/renderer pairs
it signalled. Unlike the pid-only ``terminate``, this returns a *list* and so
carries ``--format human|json`` for machine-readable output.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from resoio.cli import output


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``terminate-all`` subparser on the top-level parser."""
    parser = subparsers.add_parser(
        "terminate-all",
        parents=[common],
        help="Stop every running Resonite instance (SIGTERM -> SIGKILL); lists pairs.",
        description=(
            "Force-stop all running Resonite clients by signalling each engine and "
            "renderer process. The multi-instance counterpart to 'resoio terminate'. "
            "Idempotent (already-dead PIDs are skipped). Prints one engine/renderer "
            "pair per instance signalled, or 'no running Resonite instances found'."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="Seconds to wait after SIGTERM before SIGKILL, per PID (default: 3).",
    )
    output.add_format_argument(parser)
    parser.set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Defer the heavy import (psutil) to keep `resoio --help` fast.
    from resoio.launcher import LauncherError, terminate_all

    try:
        results = await asyncio.to_thread(terminate_all, timeout=args.timeout)
    except LauncherError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if output.is_structured(args.format):
        # list[LaunchResult] -> [{"resonite_pid": .., "renderer_pid": ..}, ...].
        output.emit(results, args.format)
        return 0

    if not results:
        print("no running Resonite instances found")
        return 0
    for result in results:
        print(f"resonite_pid={result.resonite_pid} renderer_pid={result.renderer_pid}")
    print(f"terminated {len(results)} instance(s)")
    return 0
