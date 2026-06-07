"""``resoio ping`` subcommand: round-trip Connection.Ping over the UDS."""

from __future__ import annotations

import argparse
import asyncio
import sys


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``ping`` subparser on the top-level parser.

    ``common`` carries flags shared by every subcommand (e.g.
    ``-s/--socket``) and is attached via ``parents=[common]``.
    """
    parser = subparsers.add_parser(
        "ping",
        parents=[common],
        help="Send Connection.Ping over the UDS and report the RTT.",
        description=(
            "Send one or more Connection.Ping requests over the Resonite IO UDS "
            "and print the echoed message plus the round-trip time."
        ),
    )
    parser.add_argument(
        "-m",
        "--message",
        default="ping",
        help='Payload string sent in PingRequest.message (default: "ping").',
    )
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Number of pings to send (default: 1).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-ping timeout in seconds (default: 5.0).",
    )
    parser.set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Defer heavy imports to keep `resoio --help` and shell completion fast.
    import time

    from resoio.connection import ConnectionClient

    async with ConnectionClient(args.socket) as client:
        for _ in range(args.count):
            # monotonic_ns: immune to wall-clock jumps (NTP step, DST) that
            # would otherwise produce negative or inflated RTTs.
            t0 = time.monotonic_ns()
            try:
                resp = await asyncio.wait_for(
                    client.ping(args.message), timeout=args.timeout
                )
            except TimeoutError:
                print(
                    f"ping timed out after {args.timeout:.3f}s",
                    file=sys.stderr,
                )
                return 1
            t1 = time.monotonic_ns()
            rtt_ms = (t1 - t0) / 1e6
            print(
                f"message={resp.message} "
                f"server_unix_nanos={resp.server_unix_nanos} "
                f"rtt_ms={rtt_ms:.3f}"
            )
    return 0
