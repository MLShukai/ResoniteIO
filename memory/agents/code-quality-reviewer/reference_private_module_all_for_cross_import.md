---
name: private-module-all-for-cross-import
description: private モジュール (_foo.py) から cross-import されるシンボルは _ prefix を付けない (ユーザー規約)。__all__ で表面を明示し、テストが pin する旧名は import alias で互換維持。
metadata:
  type: feedback
---

resoio の Python 側で private モジュール (`_foo.py`) を分割するとき、**そこから
sibling モジュールへ import されるシンボルには `_` prefix を付けない**
(2026-06-10 ユーザーフィードバック)。privacy はモジュール名の `_` prefix が
担っており、シンボル側の `_` は二重で規約違反。

- 抽出先モジュール: cross-import される名前は unprefixed (`MuxedState`,
  `suppress_teardown_errors` など)。モジュール内部でしか使わない helper /
  定数だけ `_` prefix を残す
- `__all__` は引き続き置く: 「このモジュールの export 表面」のドキュメントとして
  機能する。unprefixed 名なら pyright strict の `reportPrivateUsage` /
  `reportUnusedFunction` はそもそも発生しない (旧回避策だった
  「`_` シンボルを `__all__` に列挙して通す」は不要になる)
- テストが旧 `_` 名を `resoio.xxx.<module>.<sym>` 経路で pin している場合は、
  抽出元モジュール側で `from ..._foo import sym as _sym` と alias して互換を
  保つ (テストは編集しない)。実例: `record.py` の
  `suppress_teardown_errors as _suppress_teardown_errors`
- 既存の `resoio._client` → `_BaseClient` cross-import はこの規約確立より前の
  legacy。指示なしにリネームしない (12+ ファイルに波及するため別判断)

ruff/pyupgrade が `typing.Callable` → `collections.abc.Callable` を rewrite する
ので、抽出時の import は最初から collections.abc に寄せておくと pre-commit の
二度手間を避けられる。
