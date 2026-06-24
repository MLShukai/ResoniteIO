"""``resoio display <subcommand>``: read or apply window resolution / fps cap.

Nested subcommands mirror ``resoio world``: a ``display`` parent parser
holds the ``get`` / ``set`` leaves, each with the shared ``-s/--socket``
parent re-attached (argparse does not inherit it) and its own handler
set via ``set_defaults(func=...)``. ``set`` applies a partial config — a
resolution preset / ``WIDTHxHEIGHT[@FPS]`` positional and/or ``-W/-H/-F``
flags (the flags override the spec) — and then prints the post-apply
snapshot best-effort: the engine applies the config on its own thread, so
the snapshot may briefly lag the request.
"""

from __future__ import annotations

import argparse

from resoio.cli import output

_RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "hd": (1280, 720),
    "fhd": (1920, 1080),
    "qhd": (2560, 1440),
    "uhd": (3840, 2160),
}


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


def _parse_spec(raw: str) -> tuple[int, int, float | None]:
    """Parse a ``display set`` resolution spec into ``(width, height, fps)``.

    The spec is ``<resolution>[@<fps>]`` where ``<resolution>`` is either a
    case-insensitive preset name (``hd`` / ``fhd`` / ``qhd`` / ``uhd``) or an
    explicit ``WIDTHxHEIGHT`` (e.g. ``1280x720``), and the optional ``@<fps>``
    suffix sets the background fps cap. ``fps`` is ``None`` when ``@`` is
    omitted, so the caller can tell "no fps requested" from an explicit value.
    The ``-W/-H/-F`` flags override the parsed fields in :func:`_run_set`.

    Examples:
        ``fhd`` -> ``(1920, 1080, None)``
        ``fhd@30`` -> ``(1920, 1080, 30.0)``
        ``1280x720@60`` -> ``(1280, 720, 60.0)``

    Raises:
        argparse.ArgumentTypeError: on an unknown preset, malformed
            ``WIDTHxHEIGHT``, non-positive dimensions, or a non-positive /
            non-numeric ``@fps``.
    """
    resolution, sep, fps_text = raw.partition("@")

    fps: float | None = None
    if sep:
        try:
            fps = float(fps_text)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"invalid spec {raw!r}: expected a number after '@'"
            ) from None
        if fps <= 0.0:
            raise argparse.ArgumentTypeError(
                f"invalid spec {raw!r}: fps after '@' must be positive"
            )

    key = resolution.lower()
    if key in _RESOLUTION_PRESETS:
        width, height = _RESOLUTION_PRESETS[key]
        return width, height, fps

    width_text, x_sep, height_text = key.partition("x")
    if not x_sep:
        presets = "/".join(_RESOLUTION_PRESETS)
        raise argparse.ArgumentTypeError(
            f"invalid resolution {resolution!r}: expected a preset "
            f"({presets}) or WIDTHxHEIGHT"
        )
    try:
        width, height = int(width_text), int(height_text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid resolution {resolution!r}: WIDTHxHEIGHT must be integers"
        ) from None
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(
            f"invalid resolution {resolution!r}: width and height must be positive"
        )
    return width, height, fps


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
            "Apply a partial display config. Resolution can be given as a "
            "positional spec (a preset hd/fhd/qhd/uhd or WIDTHxHEIGHT, with an "
            "optional @FPS suffix); the -W/-H/-F flags override the matching "
            "spec field. Omitted fields are sent as the proto3 default "
            "(0 / 0.0), which the server treats as 'leave unchanged'. At least "
            "one of the spec or a flag is required."
        ),
    )
    parser.add_argument(
        "spec",
        nargs="?",
        type=_parse_spec,
        default=None,
        metavar="RESOLUTION",
        help=(
            "Resolution preset (hd/fhd/qhd/uhd) or WIDTHxHEIGHT, with an "
            "optional @FPS suffix (e.g. 'fhd', '1280x720', 'fhd@30'). The "
            "-W/-H/-F flags override the matching field."
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

    if (
        args.spec is None
        and args.width is None
        and args.height is None
        and args.max_fps is None
    ):
        set_parser: argparse.ArgumentParser = args._set_parser
        set_parser.error(
            "at least one of RESOLUTION, -W/--width, -H/--height, -F/--max-fps "
            "is required"
        )

    # The spec supplies base values; each flag overrides its field. Fields left
    # unset by both collapse to 0 / 0.0 (proto3 default = server-side "leave
    # unchanged"). Explicit `--max-fps 0` is forwarded as-is.
    spec_width, spec_height, spec_fps = (
        args.spec if args.spec is not None else (0, 0, None)
    )
    width = args.width if args.width is not None else spec_width
    height = args.height if args.height is not None else spec_height
    if args.max_fps is not None:
        max_fps = args.max_fps
    elif spec_fps is not None:
        max_fps = spec_fps
    else:
        max_fps = 0.0

    async with DisplayClient(args.socket) as client:
        await client.apply(width=width, height=height, max_fps=max_fps)
        info = await client.get()
    _emit_info(info.width, info.height, info.max_fps, args.format)
    return 0
