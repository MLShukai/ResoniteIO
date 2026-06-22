---
name: changelog_emoji_convention
description: CHANGELOG.md は絵文字付きカテゴリ見出し + 💥 Breaking marker 規約。version 見出しと末尾 link 定義は触らない。polish は docstring-author に委譲。
metadata:
  type: feedback
---

`CHANGELOG.md` (Keep a Changelog 形式) のエントリは、変更の種類が一目で分かるよう絵文字付きで書く。

- カテゴリ見出し (`###`) に絵文字を付ける: `### ✨ Added` / `### 🔧 Changed` / `### 🗑️ Removed` / `### 🐛 Fixed` / `### 🔒 Security` / `### ⚠️ Deprecated`。これ以外の絵文字は使わない。
- breaking change はエントリ本文の先頭に `💥 Breaking:` マーカーを付けて統一する (`(breaking)` / `Breaking — ...` の表記揺れを避ける)。
- **load-bearing なので触らない**: `## [X.Y.Z] - YYYY-MM-DD` / `## [Unreleased]` の version 見出し (絵文字も付けない) と、末尾の `[version]: url` link reference definitions。`publish.yml` の github-release job が `## \[X.Y.Z\]` regex で section を抽出して Release ノートにするため、ここを壊すとノートが generic な "Release X.Y.Z" にフォールバックする (\[\[feedback_release_pipeline\]\] / release-resonite skill §1-1)。
- リリースノートなので事実情報は落とさない。読みやすさは表現で出す。特に breaking change の移行手順 (旧→新の名前・削除引数・lockstep 指示) は必ず残す。
- polish/整形作業は `docstring-author` agent に委譲する (\[\[feedback_docstring_author_includes_cleanup\]\])。agent 定義にも CHANGELOG polishing の節を入れてある。

**Why:** ユーザー (project owner) が「CHANGELOG が読みにくい、絵文字で変更種別を分かりやすく整理したい」と依頼 (2026-06-22)。絵文字スキームと load-bearing 制約を将来の編集でも一貫させるための規約。

**How to apply:** CHANGELOG にエントリを足す / 整形するとき、リリースを切るとき (release-resonite skill §1-1 step 2) に従う。
