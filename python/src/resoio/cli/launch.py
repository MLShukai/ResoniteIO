"""``resoio launch`` subcommand: start Resonite (engine + renderer) via umu.

Spawns the umu-launcher chain (no gRPC), waits for the engine and renderer
processes to appear, and prints their host PIDs. The mod must already be
installed in the profile (``MOD_PATH`` / ``--profile``); use ``--vanilla`` to
launch without any mod. The printed ``resonite_pid`` / ``renderer_pid`` are the
handles ``resoio terminate`` takes to stop the client.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from resoio.cli import output


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``launch`` subparser on the top-level parser."""
    parser = subparsers.add_parser(
        "launch",
        parents=[common],
        help="Launch Resonite (engine + renderer) via umu-launcher; prints both PIDs.",
        description=(
            "Start the Resonite client through umu-launcher with the ResoniteIO "
            "mod loaded, then print the engine (resonite_pid) and renderer "
            "(renderer_pid) host PIDs. Resonite.exe comes from --exe / RESONITE_EXE "
            "(default: the Steam install); the mod profile from --profile / MOD_PATH "
            "(must have the ResoniteIO mod deployed). Use --vanilla to launch with no "
            "mod. Pass extra Resonite arguments after '--'."
        ),
    )
    parser.add_argument(
        "-e",
        "--exe",
        default=None,
        help="Path to Resonite.exe (default: RESONITE_EXE, then the Steam install).",
    )
    parser.add_argument(
        "-p",
        "--profile",
        default=None,
        help="Gale profile dir holding the ResoniteIO mod (default: MOD_PATH).",
    )
    parser.add_argument(
        "--vanilla",
        action="store_true",
        help="Launch without loading any mod (skips the mod-profile checks).",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Wine prefix dir (WINEPREFIX). Default: umu's (~/Games/umu/$GAMEID).",
    )
    parser.add_argument(
        "--proton-path",
        default=None,
        help=(
            "Proton build (PROTONPATH); a compat-tools name like GE-Proton or a "
            "path. Default: GE-Proton."
        ),
    )
    parser.add_argument(
        "--data-path",
        default=None,
        help="Resonite database directory (-DataPath).",
    )
    parser.add_argument(
        "--cache-path",
        default=None,
        help="Resonite cache directory (-CachePath).",
    )
    parser.add_argument(
        "--logs-path",
        default=None,
        help="Resonite log files directory (-LogsPath).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for the engine/renderer to appear (default: 60).",
    )
    parser.add_argument(
        "args",
        nargs="*",
        help=(
            "Extra Resonite arguments forwarded verbatim (use '--' to separate); "
            "the escape hatch for options without a dedicated flag."
        ),
    )
    output.add_format_argument(parser)
    parser.set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Defer the heavy import (psutil) to keep `resoio --help` fast.
    from resoio.launcher import LauncherError, launch
    from resoio.resonite_options import ResoniteOptions

    options = ResoniteOptions(
        data_path=args.data_path,
        cache_path=args.cache_path,
        logs_path=args.logs_path,
    )
    try:
        # launch() is blocking (it polls the process table); run it off the loop.
        result = await asyncio.to_thread(
            launch,
            resonite_exe=args.exe,
            mod_path=args.profile,
            vanilla=args.vanilla,
            options=options,
            extra_args=args.args,
            prefix=args.prefix,
            proton_path=args.proton_path,
            wait_timeout=args.timeout,
        )
    except LauncherError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if output.is_structured(args.format):
        # LaunchResult is a dataclass -> {"resonite_pid": ..., "renderer_pid": ...}.
        output.emit(result, args.format)
    else:
        print(f"resonite_pid={result.resonite_pid}")
        print(f"renderer_pid={result.renderer_pid}")
    return 0
