"""``resoio display`` subcommand: apply / get window resolution and fps cap."""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``display`` subparser with nested ``apply`` / ``get``.

    ``common`` is re-attached on each leaf (not just the ``display`` node)
    because argparse does not inherit shared flags from a parent subparser
    to its children; ``resoio display apply -s SOCK`` would otherwise drop
    ``-s`` on the leaf's namespace.
    """
    parser = subparsers.add_parser(
        "display",
        parents=[common],
        help="Apply or read engine-side display settings (resolution, fps cap).",
        description=(
            "Drive the Resonite IO Display service from the shell. Use "
            "`display apply` to push a (partial) config and `display get` "
            "to read the current snapshot."
        ),
    )
    display_subs = parser.add_subparsers(dest="display_command", required=True)

    apply_parser = display_subs.add_parser(
        "apply",
        parents=[common],
        help="Apply a partial display config and print the resulting snapshot.",
        description=(
            "Send a DisplayConfig to the engine. Fields left at 0 / 0.0 "
            "are treated as 'leave unchanged' (proto3 default semantics). "
            "At least one of --width / --height / --max-fps must be given."
        ),
    )
    apply_parser.add_argument(
        "--width",
        type=int,
        default=0,
        help="Window width in pixels (0 = leave unchanged).",
    )
    apply_parser.add_argument(
        "--height",
        type=int,
        default=0,
        help="Window height in pixels (0 = leave unchanged).",
    )
    apply_parser.add_argument(
        "--max-fps",
        type=float,
        default=0.0,
        dest="max_fps",
        help="Background fps cap (0.0 = leave unchanged).",
    )
    apply_parser.set_defaults(func=_make_run_apply(apply_parser))

    get_parser = display_subs.add_parser(
        "get",
        parents=[common],
        help="Print the current engine-side display snapshot.",
        description="Read the current DisplayState without modifying it.",
    )
    get_parser.set_defaults(func=_run_get)


def _format_info(width: int, height: int, max_fps: float) -> str:
    return f"width={width} height={height} max_fps={max_fps}"


def _make_run_apply(
    parser: argparse.ArgumentParser,
) -> Callable[[argparse.Namespace], Awaitable[int]]:
    """Bind ``parser`` so the handler can emit argparse-style errors."""

    async def _run_apply(args: argparse.Namespace) -> int:
        # All-zero apply would just echo current state — that's `display get`.
        if not (args.width or args.height or args.max_fps):
            parser.error("specify at least one of --width / --height / --max-fps")

        # Deferred to keep `resoio --help` and shell completion fast.
        from resoio.display import DisplayClient

        async with DisplayClient(args.socket) as client:
            # Apply は値を返さない (`-> None`)。stdout は空のままにし、新しい snapshot を
            # 見たい呼び出し側は別途 `resoio display get` を実行する契約。Commit B で
            # CLI 自体を flat 化する際にこの dispatch も整理する。
            await client.apply(
                width=args.width,
                height=args.height,
                max_fps=args.max_fps,
            )
        return 0

    return _run_apply


async def _run_get(args: argparse.Namespace) -> int:
    from resoio.display import DisplayClient

    async with DisplayClient(args.socket) as client:
        info = await client.get()
    print(_format_info(info.width, info.height, info.max_fps))
    return 0
