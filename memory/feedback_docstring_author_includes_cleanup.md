---
name: docstring-author-includes-cleanup
description: docstring-author を呼ぶときは新規 docstring 追加だけでなく既存の冗長コメント cleanup も依頼するのが既定。
metadata:
  type: feedback
---

`docstring-author` エージェントを呼ぶときは、毎回「新規/変更箇所の polish」だけでなく「ファイル全体の冗長コメント cleanup」もスコープに含めるよう明示的に指示する。

**Why:** ユーザーが直接 IDE で開いて確認した時に「冗長なコメントが残っているのが気になる」というフィードバックを出している。docstring を厚く追加した直後ほど発生しやすいので、追加 pass を別途回すより同じ pass で trim まで一気にやってしまうのが摩擦が少ない。

**How to apply:**

- agent prompt の「観点」または「やってほしいこと」セクションに「冗長 / WHAT 再説明 / 識別子から自明な記述を trim する」を明示
- 「新規追加」だけでなく「ファイル全体の既存コメント」を対象に含める
- WHY コメント (Unity Object null overload、proto3 default、pressure-vessel 制約、等の load-bearing な背景) は触らない、という保護線も同時に明示
- これは \[\[docstring-author/MEMORY.md\]\] の trim 規律と同根。docstring-author 側にも同様のメモは既にあるが、呼び出し側のプロンプトでも毎回明示しないと「追加」モードで終わりがち
