---
name: migrate-codex
description: "Use from the Claude side to sync Codex's settings-derived rules. `.claude/` is the source of truth; this skill regenerates `.codex/rules/default.rules` from `.claude/settings*.json` via `just migrate-codex`. Content-level sync of skills/agents/prose is NOT done here — that is the Codex side's `migrate-claude` skill. Triggers: 'Codex 設定を同期', 'migrate-codex', 'just migrate-codex', '.codex/rules を更新', 'Codex rules を再生成', 'Codex に permission を反映', 'settings を Codex へ'."
---

# Migrate Claude Settings To Codex

このリポジトリは Claude (`.claude/` + `CLAUDE.md`) を source of truth とし、Codex 用資産 (`.agents/` + `.codex/` + `AGENTS.md`) はそのミラーとして repo 内に持つ。**この skill は Claude 側から「形式的に処理できる settings 由来の Codex rules」だけを同期する**。skill / agent / prose guidance の内容移植は **Codex 側の `migrate-claude` skill** (`.agents/skills/migrate-claude/`) が担当するので、ここでは扱わない。

## 何を同期するか

- `just migrate-codex` (= `python3 scripts/migrate_codex.py`) が `.claude/settings.json` + `.claude/settings.container.json` の `permissions` を読み、`Bash(...)` の allow / deny を Codex の `prefix_rule` に変換して `.codex/rules/default.rules` を再生成する。
- 変換は **deterministic な Bash permission のみ**。非 Bash の permission (Edit / Read / Write 等) は Codex の tools/sandbox 側で扱う前提で、生成 rules のヘッダにコメントとして残る。
- `.codex/config.toml`、auth/session state、個人環境設定は生成しない。

## 手順

1. `.claude/settings*.json` の permission を変更したら、まず drift を確認する:

   ```bash
   just migrate-codex --check   # stale なら非ゼロ終了
   ```

2. stale なら再生成して diff を確認する:

   ```bash
   just migrate-codex
   git diff .codex/rules/default.rules
   ```

3. 生成物 `.codex/rules/default.rules` を同じ commit に含める。手書きしない (常に script 生成物)。

## スコープ外 (Codex 側の責務)

- `.claude/skills/`、`.claude/agents/*.md`、`CLAUDE.md` の知見を `.agents/skills/`、`.codex/agents/*.toml`、`AGENTS.md` へ反映するのは **Codex 側で `migrate-claude` skill を明示的に呼んで行う** (内容判断が必要なため script 化しない)。Claude 側からは手を出さない。
- 単純なパス・名称置換だけでは意味が変わるものは script に入れない。置換ルールを増やしたくなったら、それは `migrate-claude` skill 側の手順。

## 検証

```bash
just migrate-codex --check
pre-commit run --files scripts/migrate_codex.py .codex/rules/default.rules
```
