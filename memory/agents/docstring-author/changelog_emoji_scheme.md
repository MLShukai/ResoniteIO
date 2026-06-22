---
name: changelog-emoji-scheme
description: CHANGELOG.md polish convention — emoji on Keep-a-Changelog category headings + 💥 Breaking marker, plus load-bearing parts not to touch
metadata:
  type: feedback
---

CHANGELOG.md (repo root) uses a fixed emoji scheme on `###` category headings and
a normalized breaking-change marker. Apply consistently across **all** version
sections when polishing.

**Why:** the user wants release notes that are scannable at a glance; the emoji
let a reader spot the change type without reading prose. Introduced 2026-06-22.

**How to apply:**

- Category headings (`###`) only — never the `## [X.Y.Z]` version headings:
  - `### ✨ Added` / `### 🔧 Changed` / `### 🗑️ Removed` / `### 🐛 Fixed`
  - `### 🔒 Security` / `### ⚠️ Deprecated`
- Use **no other emoji** anywhere.
- Breaking entries: prefix body with `💥 Breaking:` right after the bold lead-in
  (e.g. `**X is renamed**: 💥 Breaking: ...`). Normalize old `(breaking)` /
  `Breaking — ` forms to this. Leave incidental prose "breaking" (e.g. "a
  **breaking** release", "breaking on the first frame") untouched — only entry
  markers get normalized.
- Long Unreleased entries: split into intro sentence + sub-bullets for scan-ability;
  never drop migration facts (old→new names, removed args, lockstep instructions).

**Load-bearing — DO NOT touch:**

- `## [X.Y.Z] - YYYY-MM-DD` / `## [Unreleased]` version headings: `publish.yml`
  github-release job extracts via `## \[X.Y.Z\]` regex. No emoji on these.
- Trailing `[0.1.0]: https://...` link reference definitions (order + content).
- The 6-line intro paragraph (Keep a Changelog link).

**Lint note:** MD024 (duplicate-heading) warnings fire because every version reuses
`Added`/`Changed`/`Fixed` — these are pre-existing and expected for a changelog;
ignore them. mdformat does not escape emoji-prefixed `###` headings.
