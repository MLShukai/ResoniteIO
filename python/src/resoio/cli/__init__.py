"""Command-line entry point for the ``resoio`` package.

The CLI is intentionally thin: each subcommand lives in its own module
under ``resoio.cli`` and exposes ``register(subparsers)`` plus an async
``_run(args)`` handler. New commands are added by writing a module and
appending it to :data:`_COMMAND_MODULES`.

Heavy imports (gRPC stack, numpy, generated stubs) are deferred to each
command's ``_run`` so ``resoio --help`` and shell completion stay snappy.
"""

# PYTHON_ARGCOMPLETE_OK

from __future__ import annotations

import argparse
import asyncio
from importlib import metadata
from types import ModuleType

import argcomplete

from resoio.cli import (
    context_menu,
    dash,
    display,
    inventory,
    locomotion,
    manipulate,
    mic,
    ping,
    record,
    world,
)

__all__ = ["main"]

_COMMAND_MODULES: list[ModuleType] = [
    ping,
    display,
    context_menu,
    dash,
    locomotion,
    manipulate,
    mic,
    record,
    world,
    inventory,
]


def _resolve_version() -> str:
    try:
        return metadata.version("resoio")
    except metadata.PackageNotFoundError:  # pragma: no cover - editable edge
        return "0+unknown"


def _build_common_parent() -> argparse.ArgumentParser:
    """Build the parent parser holding flags shared by every subcommand.

    Subcommand modules consume this via ``parents=[common]`` so the option
    surface (e.g. ``-s/--socket``) stays in lock-step across commands.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "-s",
        "--socket",
        default=None,
        help=(
            "UDS path override. Falls back to RESONITE_IO_SOCKET, then "
            "RESONITE_IO_SOCKET_DIR, then ~/.resonite-io/."
        ),
    )
    return parent


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``resoio`` argument parser.

    Each module in :data:`_COMMAND_MODULES` registers one subparser via
    ``module.register(subparsers, common)``; ``common`` is a parent parser
    whose flags are reused by every subcommand.
    """
    parser = argparse.ArgumentParser(
        prog="resoio",
        description="Resonite IO CLI client",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_resolve_version()}",
    )
    common = _build_common_parent()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in _COMMAND_MODULES:
        module.register(subparsers, common)
    return parser


async def _amain(args: argparse.Namespace) -> int:
    """Dispatch to the subcommand handler set on ``args.func``."""
    handler = args.func
    return await handler(args)


def main(argv: list[str] | None = None) -> int:
    """Synchronous entry point used by the ``resoio`` console script."""
    parser = _build_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 130
