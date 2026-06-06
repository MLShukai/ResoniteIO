---
name: examples-no-private-prefix
description: python/examples/ 配下のサンプルコードでは module-level の定数や helper 関数に `_` private prefix を付けない (library ではないため)
metadata:
  type: feedback
---

`python/examples/` 配下のサンプルファイルでは、module-level の定数も helper
関数も plain な名前 (`DURATION_S`, `wait_for_ready`) で書く。`_` private
prefix は付けない。

**Why:** examples は library モジュールではなく "API 呼び出しの最小サンプル"
として読まれる教材。`_` prefix は library 内部での「外から呼ぶな」のシグナル
だが、example はそもそも単独実行ファイルで「外」が存在しない。private prefix
は「ライブラリの API なのか実装詳細なのか」を読者に余計に考えさせるノイズに
なる。一方で library 本体 (`python/src/resoio/`) では `_` prefix を維持する
(pyright strict / `__all__` 制御の文脈)。

**How to apply:**

- 新規 `python/examples/X.py` ファイルを書くとき、constants は `WIDTH = 640`、
  helper は `async def wait_for_ready()` のように plain naming
- `python/src/resoio/` 配下のライブラリコードでは従来通り `_private` を使う
  (\[\[feedback-pyright-unused-private-in-src\]\] 参照)
- CLI (`python/src/resoio/cli/`) は library 本体扱いで `_run` 等 `_` prefix を維持
