"""``resoio auth <action>``: log in / out of Resonite cloud and read status.

Modelled on ``gh auth``: a ``auth`` parent parser holds the ``login`` /
``logout`` / ``status`` leaves, each re-attaching the shared ``-s/--socket``
parent (argparse does not inherit it) plus the ``--format`` parent (all three
produce an :class:`~resoio.auth.AuthStatus`). The heavy ``from resoio.auth
import ...`` (and ``prompt_toolkit``) are deferred into the handlers so
``resoio --help`` stays fast.

The login password is a plaintext secret: it is **never** accepted as a CLI
flag (which would leak via ``ps`` / shell history), never logged, and never
placed in any output. It comes only from ``RESONITE_IO_PASSWORD``, stdin (when
piped), or a hidden interactive prompt.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING

from resoio.cli import output

if TYPE_CHECKING:
    from resoio.auth import AuthStatus


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``auth`` subparser with its ``login`` / ``logout`` /
    ``status`` leaves."""
    parser = subparsers.add_parser(
        "auth",
        parents=[common],
        help="Log in / out of Resonite cloud and read the auth status.",
        description=(
            "Authenticate against Resonite cloud via the Resonite IO Auth "
            "service. 'login' signs in with a credential + password (the "
            "password is read from RESONITE_IO_PASSWORD, piped stdin, or a "
            "hidden prompt -- never a CLI flag); 'logout' ends the session; "
            "'status' reads the current state. No credentials are stored on "
            "disk -- --no-remember aside, persistence is delegated to the "
            "engine."
        ),
    )
    auth_subs = parser.add_subparsers(dest="auth_command", required=True)

    # All three leaves return an AuthStatus, so --format lands on each of them.
    fmt = output.build_format_parent()

    login_parser = auth_subs.add_parser(
        "login",
        parents=[common, fmt],
        help="Sign in to Resonite cloud.",
        description=(
            "Sign in to Resonite cloud. The credential (username / email / "
            "user id) is the optional positional; if omitted it is prompted "
            "interactively when stdin is a tty. The password is NEVER a CLI "
            "flag: it is read from RESONITE_IO_PASSWORD, then from piped "
            "stdin, then from a hidden prompt. For 2FA accounts pass --totp "
            "(or answer the interactive prompt on retry)."
        ),
    )
    login_parser.add_argument(
        "credential",
        nargs="?",
        default=None,
        help="Username, email, or user id (U-xxx). Prompted if omitted.",
    )
    login_parser.add_argument(
        "--totp",
        default=None,
        help="2FA one-time code (for accounts with two-factor enabled).",
    )
    login_parser.add_argument(
        "--no-remember",
        dest="remember_me",
        action="store_false",
        default=True,
        help="Do not ask the engine to persist the session.",
    )
    login_parser.set_defaults(func=_run_login)

    logout_parser = auth_subs.add_parser(
        "logout",
        parents=[common, fmt],
        help="Log out of the current Resonite cloud session.",
    )
    logout_parser.set_defaults(func=_run_logout)

    status_parser = auth_subs.add_parser(
        "status",
        parents=[common, fmt],
        help="Print the current Resonite cloud authentication status.",
    )
    status_parser.set_defaults(func=_run_status)


# ---------------------------------------------------------------------------
# Credential / password resolution
# ---------------------------------------------------------------------------

_PASSWORD_ENV = "RESONITE_IO_PASSWORD"


def _resolve_credential(positional: str | None) -> str | None:
    """Resolve the login credential.

    The positional wins when given. Otherwise, if stdin is a tty, prompt
    ``Username: ``. With no positional and a non-tty stdin there is no way to
    obtain it (stdin is reserved for the password), so return ``None`` and let
    the caller error with exit 2.
    """
    if positional is not None:
        return positional
    if sys.stdin.isatty():
        # プロンプト文字列は stderr に出す (stdout は結果 payload 専用。--format json の
        # 1 ドキュメント契約を壊さないため)。
        print("Username: ", end="", file=sys.stderr, flush=True)
        try:
            return input()
        except EOFError:
            return None
    return None


async def _resolve_password() -> str:
    """Resolve the login password without ever exposing it as a CLI flag.

    Resolution order:

    1. ``RESONITE_IO_PASSWORD`` if set and non-empty.
    2. If stdin is **not** a tty, read one line from stdin and strip the
       trailing newline (so ``echo "$pw" | resoio auth login`` works).
    3. Otherwise an interactive hidden prompt via ``prompt_toolkit``.
    """
    env = os.environ.get(_PASSWORD_ENV)
    if env:
        return env
    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        # Strip only the trailing newline; a password may contain spaces.
        return line.rstrip("\n")
    # Deferred so `resoio --help` and shell completion stay fast.
    from prompt_toolkit import PromptSession

    session: PromptSession[str] = PromptSession()
    return await session.prompt_async("Password: ", is_password=True)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _emit_status(status: AuthStatus, fmt: str) -> None:
    """Emit ``status`` in the requested format.

    json: emit the four ``AuthStatus`` fields plus a derived
    ``session_expires_iso`` (an ISO-8601 UTC string, ``null`` when there is no
    expiry); the exact ``session_expires_unix_nanos`` is kept for precision.

    human (gh-auth-like): one ``Logged in as ...`` line plus, when the session
    has an expiry, a ``Session expires at <UTC datetime>`` line; otherwise
    ``Not logged in``.
    """
    if output.is_structured(fmt):
        expires = status.session_expires
        output.emit(
            {
                "logged_in": status.logged_in,
                "user_id": status.user_id,
                "user_name": status.user_name,
                "session_expires_unix_nanos": status.session_expires_unix_nanos,
                "session_expires_iso": None if expires is None else expires.isoformat(),
            },
            fmt,
        )
        return
    if status.logged_in:
        print(f"Logged in as {status.user_name} ({status.user_id})")
        expires = status.session_expires
        if expires is not None:
            print(f"Session expires at {expires:%Y-%m-%d %H:%M:%S} UTC")
    else:
        print("Not logged in")


# ---------------------------------------------------------------------------
# 2FA retry
# ---------------------------------------------------------------------------


def _is_totp_required(message: str) -> bool:
    """Whether a FAILED_PRECONDITION message indicates a missing TOTP code."""
    lowered = message.lower()
    return "totp" in lowered or "two-factor" in lowered or "two factor" in lowered


def _totp_required_error() -> int:
    """Print the missing-2FA-code hint to stderr and return exit code 1."""
    print(
        "error: two-factor code required; pass --totp <code>",
        file=sys.stderr,
    )
    return 1


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _run_login(args: argparse.Namespace) -> int:
    # Deferred to keep `resoio --help` and shell completion fast.
    from grpclib.const import Status
    from grpclib.exceptions import GRPCError

    from resoio.auth import AuthClient

    credential = _resolve_credential(args.credential)
    if credential is None:
        print(
            "error: no credential given and stdin is not a tty "
            "(pass it as a positional argument)",
            file=sys.stderr,
        )
        return 2

    password = await _resolve_password()
    totp: str | None = args.totp

    async with AuthClient(args.socket) as client:
        try:
            status = await client.login(
                credential,
                password,
                totp=totp,
                remember_me=args.remember_me,
            )
        except GRPCError as exc:
            # 2FA: the server reports a missing code as FAILED_PRECONDITION.
            # Retry once with a code when we can prompt for one; otherwise
            # hint at --totp. The exception message carries no secret.
            if (
                exc.status is Status.FAILED_PRECONDITION
                and totp is None
                and _is_totp_required(exc.message or "")
            ):
                if not sys.stdin.isatty():
                    return _totp_required_error()
                # プロンプト文字列は stderr に出す (stdout は結果 payload 専用)。
                print("Two-factor code: ", end="", file=sys.stderr, flush=True)
                try:
                    code = input()
                except EOFError:
                    return _totp_required_error()
                status = await client.login(
                    credential,
                    password,
                    totp=code,
                    remember_me=args.remember_me,
                )
            else:
                raise

    _emit_status(status, args.format)
    return 0


async def _run_logout(args: argparse.Namespace) -> int:
    from resoio.auth import AuthClient

    async with AuthClient(args.socket) as client:
        status = await client.logout()
    _emit_status(status, args.format)
    return 0


async def _run_status(args: argparse.Namespace) -> int:
    from resoio.auth import AuthClient

    async with AuthClient(args.socket) as client:
        status = await client.status()
    _emit_status(status, args.format)
    return 0
