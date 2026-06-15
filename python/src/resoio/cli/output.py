"""Shared output serializer for the ``resoio`` CLI ``--format`` flag.

Every structured command opts into machine-readable output through this
module rather than reinventing serialization. ``human`` mode keeps using
each command's existing ``print`` path (byte-for-byte unchanged); the
``json`` branch routes its payload through :func:`emit`, which normalizes
it with :func:`to_jsonable` and writes a single JSON document to stdout.

``--format`` is **not** added to the common parent parser — only commands
that actually return structured data add it (top-level commands call
:func:`add_format_argument` in ``register``; nested commands attach the
parent built by :func:`build_format_parent` to their result-producing
leaves). That keeps ``args.format`` absent on carve-out commands
(``shutdown`` / ``screenshot`` / ``record`` / ``drive`` / interactive).

stdlib only — no yaml, no third-party dependency.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import sys
from typing import Literal, cast

__all__ = [
    "FORMAT_CHOICES",
    "Format",
    "add_format_argument",
    "build_format_parent",
    "emit",
    "is_structured",
    "render",
    "to_jsonable",
]

Format = Literal["human", "json"]
FORMAT_CHOICES = ("human", "json")


def add_format_argument(parser: argparse.ArgumentParser) -> None:
    """Add the ``--format {human,json}`` option to ``parser``.

    Defaults to ``human`` so omitting the flag preserves the existing
    text output. Called once per structured command — never on the
    common parent parser, which would leak ``--format`` onto carve-out
    commands that have no structured payload to emit.
    """
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        default="human",
        help=("Output format: human-readable text (default) or machine-readable json."),
    )


def build_format_parent() -> argparse.ArgumentParser:
    """Build a parent parser carrying only ``--format``.

    Nested commands (``cursor`` / ``display`` / ``context-menu`` /
    ``dash`` / ``world``) attach this to result-producing leaves via
    ``add_parser(..., parents=[common, fmt])`` so ``--format`` lands on
    individual leaves rather than the whole subcommand group.
    """
    parser = argparse.ArgumentParser(add_help=False)
    add_format_argument(parser)
    return parser


def is_structured(fmt: str) -> bool:
    """Return whether ``fmt`` requests structured (machine) output."""
    return fmt == "json"


def to_jsonable(obj: object) -> object:
    """Recursively normalize ``obj`` into a ``json.dumps``-safe value.

    Dispatch order is load-bearing — it is checked top to bottom and the
    first match wins:

    1. ``None`` passes through.
    2. ``bool`` passes through **before** the int branch (``bool`` is a
       subclass of ``int``; checking int first would render ``True`` as
       ``1``).
    3. :class:`enum.Enum` becomes ``obj.name`` (the string label), **not**
       ``obj.value``. betterproto2 enums are ``IntEnum``, so ``.value`` is
       a meaningless integer that ``json.dumps`` would emit as a bare int.
       The name is the stable, readable contract — and this branch must
       precede the int branch for the same subclass reason as ``bool``.
    4. ``int`` / ``float`` / ``str`` pass through (large ints such as a
       ``unix_nanos`` ~1.7e18 round-trip exactly; JSON has no int limit).
    5. ``bytes`` / ``bytearray`` raise ``TypeError`` — binary data must
       never enter a JSON payload. This is a backstop: any command that
       hands binary to ``emit`` is a bug, and we fail loudly rather than
       silently producing garbage.
    6. ``dict`` recurses with stringified keys.
    7. ``tuple`` / ``list`` recurse into a list (tuples become lists).
    8. dataclass **instances** map field name -> normalized value, in
       declaration order. betterproto2 ``Message`` is a ``@dataclass`` and
       is handled by **this** branch — we deliberately do not call
       ``Message.to_dict()``, which camelCases names and drops default
       values; ``dataclasses.fields`` gives us snake_case proto field
       names in declaration order, which is the wire/contract shape we
       want.
    9. anything else (including numpy scalars/arrays) raises ``TypeError``
       — there is no numpy branch by design, so embedding array data fails
       loudly instead of leaking ``repr()`` noise.
    """
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, enum.Enum):
        return obj.name
    if isinstance(obj, (int, float, str)):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        raise TypeError(
            f"binary data is not serializable to json: {type(obj).__name__}"
        )
    if isinstance(obj, dict):
        mapping = cast("dict[object, object]", obj)
        return {str(k): to_jsonable(v) for k, v in mapping.items()}
    if isinstance(obj, (tuple, list)):
        items = cast("tuple[object, ...] | list[object]", obj)
        return [to_jsonable(x) for x in items]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            field.name: to_jsonable(getattr(obj, field.name))
            for field in dataclasses.fields(obj)
        }
    raise TypeError(f"{type(obj).__name__} is not serializable to json")


def render(payload: object, fmt: str) -> str:
    """Render ``payload`` as a string for the given format.

    json: ``json.dumps`` with ``indent=2``, ``ensure_ascii=False`` (so
    e.g. Japanese world names stay literal), ``sort_keys=False`` (preserve
    field/declaration order), plus a trailing newline.

    human: raises ``ValueError`` — this serializer is json-only; human
    output goes through each command's existing ``print`` path and never
    reaches ``render``.
    """
    if fmt == "json":
        return (
            json.dumps(
                to_jsonable(payload),
                indent=2,
                ensure_ascii=False,
                sort_keys=False,
            )
            + "\n"
        )
    raise ValueError("render() is json-only; human uses the existing print path")


def emit(payload: object, fmt: str) -> None:
    """Write the rendered ``payload`` as one document to stdout.

    ``BrokenPipeError`` is swallowed so ``... | head`` style pipelines that
    close stdout early exit cleanly instead of raising a traceback,
    matching the existing screenshot/record binary-output handling.
    """
    try:
        sys.stdout.write(render(payload, fmt))
    except BrokenPipeError:
        pass
