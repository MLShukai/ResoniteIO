---
name: private-module-all-for-cross-import
description: resoio で _ prefix private モジュールから sibling モジュールへ _ prefix シンボルを import すると pyright strict が落ちる。対象 module に __all__ を置いて解決する定石。
metadata:
  type: reference
---

resoio の Python 側で private モジュール (`_foo.py`) を分割し、別モジュールが
`from resoio.xxx._foo import _Helper` のように `_` prefix シンボルを cross-module
import すると、pyright strict が **2 種類** のエラーを出す:

- `reportPrivateUsage`: "\_X is private and used outside of the module in which it is declared"
- `reportUnusedFunction` / `reportUnusedClass`: import される側のモジュールでは
  その private 関数/クラスが「未使用」と判定される (cross-module import は accessed と
  みなされない)

**解決策**: import される側のモジュール (`_foo.py`) に `__all__` を置き、
cross-module で参照する `_` prefix シンボルを列挙する。`__all__` に載せると
pyright はそれを「export された表面」と扱い、両エラーとも消える。`_` prefix は
プロジェクトの private-module 規約として保持したまま OK。

**Why:** project の既存定石。`resoio._client` が `__all__` に `_BaseClient` /
`_reset_version_check` を列挙し、12+ のモダリティ client が
`from resoio._client import _BaseClient` で取り込んでいる。`reportPrivateUsage`
は pyproject で `"warning"` 設定だが `just py-type` の gate では通らない (unused 系は
error)。

**How to apply:** private モジュール分割 (例: `record.py` → `_recording_io.py`) を
する code-quality refactor で、抽出先の `_` prefix シンボルを sibling から import
する設計にしたら、抽出先 module に `__all__` を足す。テストが
`resoio.xxx.<module>.<sym>` 経路で参照するシンボルは、抽出元 module 側でも
re-import して互換を保つ (import するだけで __all__ 経由なら usage 扱いになり OK)。
ruff/pyupgrade が `typing.Callable` → `collections.abc.Callable` を rewrite する
ので、抽出時の `from typing import ... Callable` は最初から collections.abc に
寄せておくと pre-commit の二度手間を避けられる。
