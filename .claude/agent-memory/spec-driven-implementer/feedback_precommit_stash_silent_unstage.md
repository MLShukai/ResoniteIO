---
name: precommit-stash-silent-unstage
description: pre-commit の stash/restore 経路で staged 内容が失われて exit 1 のみ返る事象。再 stage で復旧する。
metadata:
  type: feedback
---

`git commit` から呼ばれる pre-commit が `[WARNING] Unstaged files detected` →
`[INFO] Stashing unstaged files to /home/dev/.cache/pre-commit/patch*` →
`[INFO] Restored changes from .../patch*` の cycle を回したあと、
**全 hook が "no files to check / Skipped" で終わり exit 1** だけ返るケースに遭遇する。
git log にはコミットが残らず、`git status` を見ると先ほど `git add` した差分が
unstaged に戻っている。

**Why:** unstaged な変更が他ファイルにも残っている状態で commit を走らせると、
pre-commit は安全のため repo を unstage 部分込みで stash し、hook 終了後に
restore する。restore のときに **stage の状態まで unstage に戻る** ことがある
(特に並列に別エージェントが同じ worktree で作業して別ファイルを変更している
worktree 共有環境で発生しやすい)。hook 自体は何も触っていないので "Passed" すら
出ず "Skipped" だけ並び、exit 1 だけが表面化する。

**How to apply:**

- 並列エージェントが同 worktree を編集している環境で `git commit` が exit 1
  かつ pre-commit ログが軒並み "no files to check / Skipped" だった場合、
  **panic せず `git status` を見る**。stage 済みだった file が unstaged に
  戻っている可能性が高い。
- 対応は単純で **`git add <file>` をやり直して再度 `git commit`** する。
  hook 側の修正は不要。
- できるだけ commit 前に他 file の unstaged 変更を `git stash` または別 commit
  で除外しておくと、この cycle に巻き込まれにくい (並列ブランチで他エージェントが
  触っている file は staged にしない、が原則)。
- 関連: \[\[check-head-before-implementing\]\] (並列実装中の worktree で起きる類似
  pitfall)。
