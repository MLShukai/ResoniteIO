"""``resoio terminate`` subcommand: deprecated alias of ``resoio shutdown``.

Renamed to ``shutdown`` to match Resonite's terminology and the
``Lifecycle.Shutdown`` RPC. This alias still works but is no longer maintained
and will be removed in a future release; it prints a deprecation notice to
stderr and otherwise behaves exactly like ``resoio shutdown``.
"""

from __future__ import annotations

import argparse
import sys

_DEPRECATION_NOTICE = (
    "warning: 'resoio terminate' is deprecated and no longer maintained; use "
    "'resoio shutdown' instead. It will be removed in a future release."
)


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the deprecated ``terminate`` subparser on the top-level parser.

    ``common`` carries flags shared by every subcommand (e.g.
    ``-s/--socket``) and is attached via ``parents=[common]``.
    """
    subparsers.add_parser(
        "terminate",
        parents=[common],
        help="Deprecated alias of 'shutdown' (no longer maintained).",
        description=(
            "DEPRECATED: use 'resoio shutdown' instead. This alias still asks "
            "the engine to quit gracefully over Lifecycle.Shutdown, but is no "
            "longer maintained and will be removed in a future release."
        ),
    ).set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Defer heavy imports to keep `resoio --help` and shell completion fast.
    from resoio.lifecycle import shutdown

    print(_DEPRECATION_NOTICE, file=sys.stderr)
    pid = await shutdown(socket_path=args.socket)
    if pid is None:
        print("resonite not running")
        return 0
    print(f"resonite_pid={pid}")
    return 0
