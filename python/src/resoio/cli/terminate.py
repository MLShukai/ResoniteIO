"""``resoio terminate`` subcommand: ask the engine to quit gracefully."""

from __future__ import annotations

import argparse


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``terminate`` subparser on the top-level parser.

    ``common`` carries flags shared by every subcommand (e.g.
    ``-s/--socket``) and is attached via ``parents=[common]``.
    """
    subparsers.add_parser(
        "terminate",
        parents=[common],
        help="Ask the engine to quit gracefully (Lifecycle.Shutdown).",
        description=(
            "Stop the running Resonite client gracefully over Lifecycle.Shutdown "
            "(the engine quits itself; Steam/Proton reaps the renderer and launch "
            "wrappers). Prints the engine's host PID, or 'resonite not running' "
            "when no engine is reachable."
        ),
    ).set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Defer heavy imports to keep `resoio --help` and shell completion fast.
    from resoio.lifecycle import terminate

    pid = await terminate(socket_path=args.socket)
    if pid is None:
        print("resonite not running")
        return 0
    print(f"resonite_pid={pid}")
    return 0
