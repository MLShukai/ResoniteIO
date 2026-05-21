---
name: feedback-git-no-pager
description: git コマンド呼び出し時に --no-pager フラグを付けない。非インタラクティブ Bash では既定で pager を使わないため冗長。
metadata:
  type: feedback
---

git コマンド (`git log`, `git diff` 等) を Bash ツールから呼ぶときに `--no-pager` を付けない。

**Why:** 非インタラクティブな bash 環境 (TTY 無し) では git は自動的に pager を bypass する。`--no-pager` は明示しなくても output がフルに返ってくるので冗長。ユーザーは noise を嫌うため、不要なフラグは外す。

**How to apply:** `git --no-pager log ...` → `git log ...`。`git --no-pager diff ...` → `git diff ...`。エイリアスやスクリプトでも同様。
