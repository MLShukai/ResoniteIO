---
name: pyright-unused-private-in-src
description: src/ で定義した `_` prefix private 関数/クラスは tests/ からの参照だけだと strict が unused 扱いするため `__all__` に列挙する
metadata:
  type: feedback
---

`tests/` は pyright strict の対象から外している (`tool.pyright.exclude` に
`tests/`) ため、`src/resoio/foo.py` で `_` prefix の関数 / クラスを定義し、
それを参照するのが test だけの場合 `reportUnusedFunction` /
`reportUnusedClass` で error になる。

**Why:** 段階的 commit (Phase 1A: 純粋ロジックだけ書く / Phase 2: async
runtime から参照する) のような分割を CLI モジュールでやると典型的に発生する。
本来は同一モジュール内の Phase 2 コードから呼ばれる予定だが、pyright は
未来の commit を知らない。

**How to apply:** 該当モジュールの先頭に `__all__ = ["_foo", "_Bar", ...]`
を置くと pyright は「export 対象」と見なして unused 判定をしない。
`_` prefix の意味 (= module private、外部公開しない) は変わらず、
`from .foo import *` で吸い上げる用途ではないことをコメントで明記する
(ResoniteIO では `python/src/resoio/cli/locomotion.py` でこの pattern を採用)。
