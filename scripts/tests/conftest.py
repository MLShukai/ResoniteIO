"""Pytest config for ``scripts/tests/``.

``scripts/`` 配下のスクリプトは package ではなく単独ファイルなので、
``host_agent`` / ``resonite_cli`` を ``import`` できるように親ディレクトリを
``sys.path`` に追加する。
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
