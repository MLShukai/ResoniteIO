---
name: migrate-claude
description: "Use when migrating Claude project assets into Codex-facing repo assets. The script only regenerates formal settings-derived Codex rules; use this skill for non-mechanical migration of .claude/skills, .claude/agents, CLAUDE.md guidance, and related docs. Triggers: Claude から Codex へ移行, migrate-claude, migrate-codex, Codex skill に同期, .claude を .agents/.codex に反映."
---

# Migrate Claude Assets To Codex

このリポジトリでは Claude 側の資産を参考にしつつ、Codex が読む資産を repo 内に持つ。設定の形式変換だけは script で行い、skill / agent / prose guidance の移植は Codex が内容を読んで判断する。

## 分担

- `just migrate-codex`: `.claude/settings.json` と `.claude/settings.container.json` から `.codex/rules/default.rules` を再生成する。形式的に処理できる settings migration だけを扱う。
- この skill: `.claude/skills/`、`.claude/agents/*.md`、`CLAUDE.md` の知見を `.agents/skills/`、`.codex/agents/*.toml`、`AGENTS.md` などへ移すか判断する。

## 手順

1. まず `just migrate-codex --check` を実行し、Codex rules が settings と同期しているか確認する。
2. stale なら `just migrate-codex` を実行し、生成された `.codex/rules/default.rules` の diff を確認する。
3. Claude skill / agent を移す場合は、元ファイルと既存の Codex 側ファイルを両方読み、Codex に必要な手順だけを手で反映する。
4. 既存 Codex skill / agent にしかない情報は消さない。Claude 側を source of truth と決め打ちせず、repo の現行運用に合うほうを採用する。
5. `.claude` 固有の表現 (`CLAUDE.md`、Claude Code、Claude-only permission、`edit-dot-claude` など) は、Codex で意味がある表現に置き換えるか、移植しない。

## 判断基準

- 単純なパス・名称置換だけでは意味が変わるものは script に入れない。
- 大量の置換ルールを追加したくなったら、この skill の手順として扱う。
- Codex 専用 skill は `.agents/skills/` に置き、`.claude/skills/` へ逆同期しない。
- `.codex/config.toml`、auth/session state、個人環境の設定は生成しない。

## 検証

最低限の検証:

```bash
just migrate-codex --check
pre-commit run --files scripts/migrate_codex.py .codex/rules/default.rules .agents/skills/migrate-claude/SKILL.md
```
