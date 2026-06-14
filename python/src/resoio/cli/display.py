"""``resoio display <subcommand>``: read or apply window resolution / fps cap.

Nested subcommands mirror ``resoio world``: a ``display`` parent parser
holds the ``get`` / ``set`` leaves, each with the shared ``-s/--socket``
parent re-attached (argparse does not inherit it) and its own handler
set via ``set_defaults(func=...)``. ``set`` applies a partial config and
then prints the post-apply snapshot best-effort: the engine applies the
config on its own thread, so the snapshot may briefly lag the request.
"""

from __future__ import annotations

import argparse

from resoio.cli import output


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``display`` subparser with its ``get`` / ``set`` leaves."""
    parser = subparsers.add_parser(
        "display",
        parents=[common],
        help="Read or apply engine-side display settings (resolution, fps cap).",
        description=(
            "Drive the Resonite IO Display service from the shell. 'get' "
            "prints the current snapshot; 'set' applies a partial config "
            "(unset flags are sent as the proto3 default 0 / 0.0, which the "
            "server treats as 'leave unchanged') and prints the post-apply "
            "snapshot."
        ),
    )
    display_subs = parser.add_subparsers(dest="display_command", required=True)

    fmt = output.build_format_parent()
    _register_get(display_subs, common, fmt)
    _register_set(display_subs, common, fmt)


def _register_get(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
    fmt: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "get",
        parents=[common, fmt],
        help="Print the current display snapshot.",
    )
    parser.set_defaults(func=_run_get)


def _register_set(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
    fmt: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "set",
        parents=[common, fmt],
        help="Apply a partial display config, then print the snapshot.",
        description=(
            "Apply a partial display config. Omitted flags are sent as the "
            "proto3 default (0 / 0.0), which the server treats as 'leave "
            "unchanged'. At least one flag is required."
        ),
    )
    parser.add_argument(
        "-W",
        "--width",
        type=int,
        default=None,
        help="Set window width in pixels (omit to leave unchanged).",
    )
    parser.add_argument(
        "-H",
        "--height",
        type=int,
        default=None,
        help="Set window height in pixels (omit to leave unchanged).",
    )
    parser.add_argument(
        "-F",
        "--max-fps",
        type=float,
        default=None,
        dest="max_fps",
        help=(
            "Set the background fps cap (omit to leave unchanged). The "
            "foreground cap is not exposed by this CLI."
        ),
    )
    parser.set_defaults(func=_run_set, _set_parser=parser)


def _format_info(width: int, height: int, max_fps: float) -> str:
    return f"width={width} height={height} max_fps={max_fps}"


def _emit_info(width: int, height: int, max_fps: float, fmt: str) -> None:
    if output.is_structured(fmt):
        output.emit({"width": width, "height": height, "max_fps": max_fps}, fmt)
    else:
        print(_format_info(width, height, max_fps))


async def _run_get(args: argparse.Namespace) -> int:
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.display import DisplayClient

    async with DisplayClient(args.socket) as client:
        info = await client.get()
    _emit_info(info.width, info.height, info.max_fps, args.format)
    return 0


async def _run_set(args: argparse.Namespace) -> int:
    """Apply the partial config, then print the post-apply snapshot.

    The snapshot is best-effort: the engine applies the config on its own
    thread, so the printed values may briefly lag the requested ones.
    """
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.display import DisplayClient

    if args.width is None and args.height is None and args.max_fps is None:
        set_parser: argparse.ArgumentParser = args._set_parser
        set_parser.error(
            "at least one of -W/--width, -H/--height, -F/--max-fps is required"
        )

    async with DisplayClient(args.socket) as client:
        # Unset flags collapse to 0 / 0.0 (proto3 default = server-side
        # "leave unchanged"). Explicit `--max-fps 0` is forwarded as-is.
        await client.apply(
            width=args.width if args.width is not None else 0,
            height=args.height if args.height is not None else 0,
            max_fps=args.max_fps if args.max_fps is not None else 0.0,
        )
        info = await client.get()
    _emit_info(info.width, info.height, info.max_fps, args.format)
    return 0
