---
name: migrate-codex
description: "Use when Claude project assets are the source of truth and Codex-facing mirrors need updating. Migrates .claude/skills to .agents/skills, .claude/agents/*.md to .codex/agents/*.toml, and .claude/settings*.json to .codex/rules/default.rules. Triggers: just migrate-codex, Claude から Codex へ移行, Codex skill に同期, .claude を .agents/.codex に反映."
---

# Migrate Claude Assets To Codex

このリポジトリでは `.claude/` 側を編集元にして、Codex が読む mirror を `.agents/` と `.codex/` に生成する。Claude 側の skill / agent / settings を変更した後、Codex 側にも反映したいときに使う。

## 何を同期するか

- `.claude/skills/<name>/` -> `.agents/skills/<name>/`
- `.claude/agents/<name>.md` -> `.codex/agents/<name>.toml`
- `.claude/settings.json` と `.claude/settings.container.json` -> `.codex/rules/default.rules`

`edit-dot-claude` のような Claude harness 専用 skill は既定では同期しない。必要なら `--include-claude-only` を付ける。

## 手順

1. 差分確認だけなら `just migrate-codex --check` を実行する。stale な mirror があると非 0 で、更新対象のファイルが表示される。
2. 実際に更新するなら `just migrate-codex` を実行する。
3. `git diff` で変換結果を確認する。変換が粗い場合は生成物を手で直すのではなく、`scripts/migrate_codex.py` の rewrite 規則を直して再実行する。
4. `just migrate-codex --check` が green になることを確認する。

## 判断基準

- Claude 側の文脈を Codex 用に変える必要がある表現 (`CLAUDE.md`、`.claude/skills`、`.claude/agents/*.md` など) は converter で置換する。
- Codex mirror にしか存在しない skill は消さない。`migrate-codex` skill 自体は Codex 専用なので `.claude/skills` には戻さない。
- `.codex/config.toml` と個人の auth/session state は自動生成しない。
- 新しい Claude agent の TOML 変換が不自然なら、まず frontmatter / body の構造が既存 agent と同形か確認する。

## 検証

最低限の検証は以下。

```bash
just migrate-codex
just migrate-codex --check
```

Docker/devcontainer 変更と同時に扱う場合は、追加で `docker compose -f compose.yml config` か devcontainer rebuild で構文を確認する。
