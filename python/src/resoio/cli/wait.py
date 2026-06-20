"""``resoio wait`` subcommand: block until the server answers
Connection.Ping."""

from __future__ import annotations

import argparse
import sys


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``wait`` subparser on the top-level parser.

    ``common`` carries flags shared by every subcommand (e.g.
    ``-s/--socket``) and is attached via ``parents=[common]``.
    """
    parser = subparsers.add_parser(
        "wait",
        parents=[common],
        help="Block until the server answers Connection.Ping (startup readiness).",
        description=(
            "Poll the Resonite IO UDS until Connection.Ping succeeds, then print "
            "the resolved socket path. Sockets whose owning engine PID is gone are "
            "skipped, so this waits for a live, ready engine. Pass a pid to target "
            "<dir>/resonite-{pid}.sock instead of the auto-resolved socket."
        ),
    )
    parser.add_argument(
        "pid",
        type=int,
        nargs="?",
        default=None,
        help=(
            "Engine host PID to target (resonite-{pid}.sock). Omit to wait for the "
            "socket resolved via -s/--socket / env. Mutually exclusive with "
            "-s/--socket."
        ),
    )
    parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        default=30.0,
        help="Max seconds to wait before failing (default: 30; <=0 tries once).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.1,
        help="Seconds between attempts (default: 0.1).",
    )
    parser.set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Defer heavy imports to keep `resoio --help` and shell completion fast.
    from grpclib.exceptions import GRPCError

    from resoio._client import AmbiguousSocketError, socket_path_for_pid
    from resoio.connection import wait_for_ready

    if args.pid is not None and args.socket is not None:
        print(
            "resoio wait: give either a pid or -s/--socket, not both",
            file=sys.stderr,
        )
        return 2

    target = socket_path_for_pid(args.pid) if args.pid is not None else args.socket
    try:
        resolved = await wait_for_ready(
            target, timeout=args.timeout, interval=args.interval
        )
    except TimeoutError as exc:
        print(f"resoio wait: {exc}", file=sys.stderr)
        return 1
    except (AmbiguousSocketError, GRPCError) as exc:
        print(f"resoio wait: {exc}", file=sys.stderr)
        return 1

    print(resolved)
    return 0
