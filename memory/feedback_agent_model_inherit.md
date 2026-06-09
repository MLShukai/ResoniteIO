---
name: agent-model-inherit
description: .claude/agents の model frontmatter は inherit 固定。session model は settings.container.json で一元 pin する
metadata:
  type: feedback
---

`.claude/agents/*.md` の frontmatter `model:` は **`inherit`** にする。特定モデル名
(`opus` / `sonnet` / `fable` 等) を agent 側に焼き込まない。

**Why:**

- 2026-06-09 の Fable 5 移行時、全 5 agent が `model: opus` 固定のままになっており、
  session model (settings.container.json の `"model": "claude-fable-5[1m]"`) と乖離した。
- agent 側に flagship 名を pin すると、モデル世代が変わるたびに 5 ファイルを追従更新する
  羽目になる。`inherit` なら session model が single source of truth になり、
  settings.container.json の 1 箇所だけ更新すればよい。

**How to apply:** 新規 agent を `.claude/agents/` に追加するときも `model: inherit` を
使う。意図的に軽いモデルへ落としたい agent (まだ存在しない) だけ例外として明示 pin し、
理由をコメントで残す。session model の変更は settings.container.json で行う。
