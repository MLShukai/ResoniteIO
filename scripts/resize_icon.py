#!/usr/bin/env python3
"""Regenerate ``mod/icon.png`` (256x256) from the full-size root ``icon.png``.

The root ``icon.png`` is the source of truth (full resolution, committed). The
mod ships a 256x256 icon because Thunderstore requires exactly 256x256
(``mod/thunderstore.toml`` ``[build].icon``), and the docs site reuses the same
file through the ``docs/assets/icon.png`` symlink. This script derives the
256x256 copy from the master so the two never drift.

Run it via ``just icon``, or let the ``resize-icon`` pre-commit hook fire it
automatically whenever ``icon.png`` changes. The comparison is pixel-based (not
byte-based) so PNG re-encoding differences across environments never cause a
spurious rewrite; only an actual change to the master regenerates the file.
Exits non-zero (after rewriting) when the derived icon was stale, so pre-commit
flags it for re-staging.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops

_ICON_SIZE = (256, 256)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SOURCE = _REPO_ROOT / "icon.png"
_TARGET = _REPO_ROOT / "mod" / "icon.png"


def _derive() -> Image.Image:
    with Image.open(_SOURCE) as src:
        return src.convert("RGBA").resize(_ICON_SIZE, Image.Resampling.LANCZOS)


def _is_up_to_date(derived: Image.Image) -> bool:
    if not _TARGET.exists():
        return False
    with Image.open(_TARGET) as current:
        if current.size != _ICON_SIZE:
            return False
        diff = ImageChops.difference(current.convert("RGBA"), derived)
        return diff.getbbox() is None


def main() -> int:
    if not _SOURCE.exists():
        print(f"ERROR: source icon not found: {_SOURCE}", file=sys.stderr)
        return 1
    derived = _derive()
    if _is_up_to_date(derived):
        return 0
    derived.save(_TARGET)
    print(
        f"Regenerated {_TARGET.relative_to(_REPO_ROOT)} (256x256) from "
        f"{_SOURCE.relative_to(_REPO_ROOT)} — stage it.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
