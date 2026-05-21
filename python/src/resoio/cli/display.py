"""``resoio display`` subcommand: read or apply window resolution / fps cap.

Flat dispatch (no nested ``apply`` / ``get`` subcommands): with no
display-affecting flags the command reads the current snapshot and
prints it; with any of ``--width`` / ``--height`` / ``--max-fps`` set
the command applies a partial config (silent OK, exit 0). ``-s/--socket``
alone counts as "no flags" so ``resoio display -s SOCK`` still reads.

``default=None`` sentinels make "flag absent" vs. "flag passed with
value ``0``" distinguishable. The server's "0 = unchanged" (proto3
default) is a separate semantic layer: an explicit ``--max-fps 0`` is
*forwarded* to the server, where it then collapses to a no-op.
"""

from __future__ import annotations

import argparse


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the flat ``display`` subparser.

    Dispatch rules (no nested subcommands) live in the module docstring.
    """
    parser = subparsers.add_parser(
        "display",
        parents=[common],
        help="Read or apply engine-side display settings (resolution, fps cap).",
        description=(
            "Drive the Resonite IO Display service from the shell. With no "
            "flags the current snapshot is printed; supplying any of "
            "--width / --height / --max-fps applies a partial config and "
            "exits silently (rc=0). Unset fields are sent as the proto3 "
            "default (0 / 0.0), which the server treats as 'leave unchanged'."
        ),
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Set window width in pixels (omit to leave unchanged).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=None,
        help="Set window height in pixels (omit to leave unchanged).",
    )
    parser.add_argument(
        "--max-fps",
        type=float,
        default=None,
        dest="max_fps",
        help=(
            "Set the background fps cap (omit to leave unchanged). The "
            "foreground cap is not exposed by this CLI."
        ),
    )
    parser.set_defaults(func=_run)


def _format_info(width: int, height: int, max_fps: float) -> str:
    return f"width={width} height={height} max_fps={max_fps}"


async def _run(args: argparse.Namespace) -> int:
    """Dispatch on flag presence: any of width/height/max_fps → apply, else get."""
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.display import DisplayClient

    apply_requested = any(
        v is not None for v in (args.width, args.height, args.max_fps)
    )

    async with DisplayClient(args.socket) as client:
        if apply_requested:
            # Unset flags collapse to 0 / 0.0 (proto3 default = server-side
            # "leave unchanged"). Explicit `--max-fps 0` is forwarded as-is.
            await client.apply(
                width=args.width if args.width is not None else 0,
                height=args.height if args.height is not None else 0,
                max_fps=args.max_fps if args.max_fps is not None else 0.0,
            )
            return 0
        info = await client.get()
    print(_format_info(info.width, info.height, info.max_fps))
    return 0
