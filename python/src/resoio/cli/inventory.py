"""``resoio inventory`` subcommand: an interactive shell over the Inventory
service.

Running ``resoio inventory`` drops into a prompt_toolkit REPL holding an
in-memory cwd (default ``/Inventory``). ``cd`` / ``pwd`` are pure
client-side; ``ls`` / ``mkdir`` / ``cp`` / ``mv`` / ``rm`` / ``spawn``
resolve relative paths to absolute and call the server. The gRPC channel
stays open for the whole session.

Bash-like semantics: ``cp -r`` / ``rm -r`` are required to act on folders;
``mv`` handles folders without a flag. Tab completion offers command names,
the ``-r`` flag (for ``cp`` / ``rm``), and inventory paths for every
path-taking command (querying the server live).

The terminal I/O (prompt_toolkit ``PromptSession``) is a thin shell over
:class:`InventoryShell`, whose ``execute`` and ``complete`` carry all the
logic and are unit-tested without a terminal.
"""

from __future__ import annotations

import argparse
import posixpath
import shlex
import sys
from typing import TYPE_CHECKING, TextIO, override

if TYPE_CHECKING:
    from resoio.inventory import InventoryClient

_DEFAULT_CWD = "/Inventory"

_COMMANDS = (
    "ls",
    "cd",
    "pwd",
    "mkdir",
    "cp",
    "mv",
    "rm",
    "spawn",
    "help",
    "exit",
    "quit",
)

# Commands whose positional operands are inventory paths (used by completion).
_PATH_COMMANDS = frozenset({"ls", "cd", "mkdir", "cp", "mv", "rm", "spawn"})
# Commands that accept the recursive flag.
_RECURSIVE_COMMANDS = frozenset({"cp", "rm"})

_HELP = """\
commands:
  ls [path]            list a directory (default: cwd)
  cd [path]            change directory (validated server-side)
  pwd                  print the current directory
  mkdir <path>         create a folder
  cp [-r] <src> <dst>  copy (use -r for folders)
  mv <src> <dst>       move/rename (folders move recursively)
  rm [-r] <path>       remove (use -r for folders)
  spawn <path>         spawn an item into the current world
  help                 show this help
  exit | quit          leave the shell"""


def _resolve(cwd: str, arg: str) -> str:
    """Resolve a possibly-relative inventory path against ``cwd``.

    Handles absolute paths, ``.`` / ``..`` and multi-segment relatives via
    POSIX normalisation (no symlink semantics — LINK entries are entries,
    not filesystem symlinks).
    """
    base = arg if arg.startswith("/") else posixpath.join(cwd, arg)
    return posixpath.normpath(base) or "/"


def _split_flags(rest: list[str]) -> tuple[bool, list[str]]:
    """Split ``-r`` / ``-R`` flags from positional operands."""
    recursive = False
    positionals: list[str] = []
    for tok in rest:
        if tok in ("-r", "-R"):
            recursive = True
        else:
            positionals.append(tok)
    return recursive, positionals


class InventoryShell:
    """Stateful command dispatcher for the inventory REPL (terminal-agnostic).

    Holds the in-memory ``cwd`` and the connected :class:`InventoryClient`.
    Output goes to the injected ``out`` / ``err`` writers so tests can
    capture it without a real terminal.
    """

    def __init__(
        self,
        client: InventoryClient,
        *,
        cwd: str = _DEFAULT_CWD,
        out: TextIO | None = None,
        err: TextIO | None = None,
    ) -> None:
        self._client = client
        self.cwd = cwd
        self._out = out if out is not None else sys.stdout
        self._err = err if err is not None else sys.stderr

    @property
    def client(self) -> InventoryClient:
        return self._client

    def resolve(self, arg: str) -> str:
        """Resolve ``arg`` against the current cwd to an absolute path."""
        return _resolve(self.cwd, arg)

    async def execute(self, line: str) -> bool:
        """Run one command line.

        Returns ``False`` when the REPL should exit.
        """
        from grpclib.exceptions import GRPCError

        try:
            parts = shlex.split(line)
        except ValueError as exc:
            self._eprint(f"parse error: {exc}")
            return True
        if not parts:
            return True

        cmd, rest = parts[0], parts[1:]
        if cmd in ("exit", "quit"):
            return False
        if cmd not in _COMMANDS:
            self._eprint(f"unknown command: {cmd} (try 'help')")
            return True

        try:
            await self._dispatch(cmd, rest)
        except GRPCError as exc:
            self._eprint(f"{cmd}: {exc.status.name}: {exc.message}")
        except IndexError:
            self._eprint(f"{cmd}: missing operand")
        return True

    async def _dispatch(self, cmd: str, rest: list[str]) -> None:
        if cmd == "help":
            self._print(_HELP)
        elif cmd == "pwd":
            self._print(self.cwd)
        elif cmd == "ls":
            await self._ls(rest)
        elif cmd == "cd":
            await self._cd(rest)
        elif cmd == "mkdir":
            await self._client.mkdir(self.resolve(rest[0]))
        elif cmd == "cp":
            recursive, pos = _split_flags(rest)
            await self._client.copy(
                self.resolve(pos[0]), self.resolve(pos[1]), recursive=recursive
            )
        elif cmd == "mv":
            await self._client.move(self.resolve(rest[0]), self.resolve(rest[1]))
        elif cmd == "rm":
            recursive, pos = _split_flags(rest)
            await self._client.remove(self.resolve(pos[0]), recursive=recursive)
        elif cmd == "spawn":
            await self._spawn(rest)

    async def _ls(self, rest: list[str]) -> None:
        target = self.resolve(rest[0]) if rest else self.cwd
        listing = await self._client.list(target)
        from resoio.inventory import InventoryEntryKind

        for entry in sorted(listing.entries, key=lambda e: e.name):
            suffix = "/" if entry.kind is InventoryEntryKind.DIRECTORY else ""
            self._print(f"{entry.name}{suffix}")

    async def _cd(self, rest: list[str]) -> None:
        target = self.resolve(rest[0]) if rest else _DEFAULT_CWD
        # Validate the target exists (and is listable) before moving there.
        await self._client.list(target)
        self.cwd = target

    async def _spawn(self, rest: list[str]) -> None:
        result = await self._client.spawn(self.resolve(rest[0]))
        self._print(
            f"spawned {result.spawned_slot_name} "
            f"({result.spawned_slot_id}) from {result.source_path}"
        )

    async def complete(self, text_before_cursor: str) -> list[tuple[str, int]]:
        """Return ``(completion_text, start_position)`` pairs for tab
        completion.

        Completes command names at the first token, the ``-r`` flag for
        ``cp`` / ``rm``, and inventory entry names for any path operand
        (querying the server for the relevant directory). ``cd`` only offers
        directories. Server errors yield no completions (never crash the REPL).
        """
        last_space = text_before_cursor.rfind(" ")
        current = text_before_cursor[last_space + 1 :]
        head = text_before_cursor[:last_space] if last_space >= 0 else ""
        prior = head.split()

        # First token → command-name completion.
        if not prior:
            return [
                (name, -len(current)) for name in _COMMANDS if name.startswith(current)
            ]

        cmd = prior[0]
        if cmd in _RECURSIVE_COMMANDS and current.startswith("-"):
            return [
                (flag, -len(current)) for flag in ("-r",) if flag.startswith(current)
            ]
        if cmd not in _PATH_COMMANDS or current.startswith("-"):
            return []
        return await self._complete_path(cmd, current)

    async def _complete_path(self, cmd: str, current: str) -> list[tuple[str, int]]:
        from grpclib.exceptions import GRPCError

        from resoio.inventory import InventoryEntryKind

        if "/" in current:
            dir_part, frag = current.rsplit("/", 1)
            list_dir = self.resolve(dir_part if dir_part else "/")
        else:
            frag = current
            list_dir = self.cwd

        try:
            listing = await self._client.list(list_dir)
        except (GRPCError, OSError):
            return []

        dirs_only = cmd == "cd"
        out: list[tuple[str, int]] = []
        for entry in sorted(listing.entries, key=lambda e: e.name):
            is_dir = entry.kind is InventoryEntryKind.DIRECTORY
            if dirs_only and not is_dir:
                continue
            if not entry.name.startswith(frag):
                continue
            out.append((entry.name + ("/" if is_dir else ""), -len(frag)))
        return out

    def _print(self, text: str) -> None:
        print(text, file=self._out)

    def _eprint(self, text: str) -> None:
        print(text, file=self._err)


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``inventory`` subparser (no positional args — REPL
    only)."""
    parser = subparsers.add_parser(
        "inventory",
        parents=[common],
        help="Interactive inventory shell (ls/cd/mkdir/cp/mv/rm/spawn).",
        description=(
            "Open an interactive shell over the Resonite IO Inventory service. "
            "Navigate with cd/ls/pwd and operate with mkdir/cp/mv/rm/spawn; "
            "cp -r / rm -r act on folders. Tab completes commands and paths."
        ),
    )
    parser.set_defaults(func=_run)


async def _run(args: argparse.Namespace) -> int:
    # Deferred so `resoio --help` and shell completion stay fast.
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import InMemoryHistory

    from resoio.inventory import InventoryClient

    async with InventoryClient(args.socket) as client:
        shell = InventoryShell(client)

        class _InventoryCompleter(Completer):
            @override
            def get_completions(self, document, complete_event):  # pyright: ignore[reportMissingParameterType]
                # Sync path unused — prompt_async drives get_completions_async.
                return iter(())

            @override
            async def get_completions_async(self, document, complete_event):  # pyright: ignore[reportMissingParameterType]
                for text, start in await shell.complete(document.text_before_cursor):
                    yield Completion(text, start_position=start)

        session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
            completer=_InventoryCompleter(),
            complete_while_typing=False,
        )

        def prompt_message() -> FormattedText:
            return FormattedText(
                [
                    ("ansibrightblue", "resoio"),
                    ("", ":"),
                    ("ansicyan", shell.cwd),
                    ("", "$ "),
                ]
            )

        while True:
            try:
                line = await session.prompt_async(prompt_message)
            except EOFError:
                break
            except KeyboardInterrupt:
                # Ctrl-C cancels the current line, like a shell; keep going.
                continue
            if not await shell.execute(line):
                break

    return 0
