"""``resoio info`` subcommand: print static server info over the UDS."""

from __future__ import annotations

import argparse
import sys


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``info`` subparser on the top-level parser.

    ``common`` carries flags shared by every subcommand (e.g.
    ``-s/--socket``) and is attached via ``parents=[common]``.
    """
    parser = subparsers.add_parser(
        "info",
        parents=[common],
        help="Print server info (mod/engine version, platform, Wine flag).",
        description=(
            "Call Info.GetServerInfo over the Resonite IO UDS and print the "
            "running mod version, engine version, OS platform, and whether "
            "the client runs under Wine/Proton."
        ),
    )
    parser.set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Defer heavy imports to keep `resoio --help` and shell completion fast.
    from grpclib.const import Status
    from grpclib.exceptions import GRPCError

    from resoio.info import get_server_info

    try:
        info = await get_server_info(args.socket)
    except GRPCError as exc:
        if exc.status is Status.UNIMPLEMENTED:
            print(
                "error: mod does not support Info (update the mod)",
                file=sys.stderr,
            )
            return 1
        raise

    print(f"mod_version={info.mod_version}")
    print(f"engine_version={info.engine_version}")
    print(f"platform={info.platform.value}")
    print(f"is_wine={'true' if info.is_wine else 'false'}")
    return 0
