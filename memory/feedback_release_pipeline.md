---
name: release-pipeline
description: ResoniteIO のリリースパイプライン (tag-driven dual publish) の非自明な前提。正規 version = csproj、CHANGELOG = release notes、net472 除外、Thunderstore namespace mlshukai。
metadata:
  type: feedback
---

`ResoniteIO` は **`v*` tag の push で Thunderstore mod (`mlshukai-ResoniteIO`) と PyPI パッケージ
(`resoio`) を同時公開する** tag-driven リリースパイプラインを持つ (`.github/workflows/publish.yml`、
4 ジョブ直列: build → publish-thunderstore → publish-pypi → github-release)。手順の正規 runbook は
[`docs/RELEASE.md`](RELEASE.md)、タスク発火型 skill は `.claude/skills/release-resonite/`。

リリースを扱うときに前提とすべき非自明な事実:

- **正規バージョンソース = csproj `<Version>`** (`mod/src/ResoniteIO/ResoniteIO.csproj`)。
  `python/pyproject.toml` の `version` は **lockstep** で同値に保つ。`build` ジョブの version guard が
  **tag `X.Y.Z` == csproj `<Version>` == pyproject version** を強制し、1 つでもズレると fail する。
  Thunderstore zip の versionNumber は `Directory.Build.targets` の `PackTS` が `--package-version $(Version)` で渡す。
- **リリースノートのソースは `mod/CHANGELOG.md`** (Keep a Changelog 形式)。`github-release` ジョブが
  `## [X.Y.Z]` セクションを抽出して GitHub Release 本文にする。tag が `(a|b|rc)[0-9]+$` なら `--prerelease`。
- **net472 Renderer は CI から除外** (`dotnet.yml`)。proprietary な Unity/Renderite 依存で headless CI が復元不可。
  ただし **共有 IPC 契約 (proto / Core Service) と engine 側ロジックは CI でテストされる** (除外は Renderer のみ)。
- **pre-commit は pre-commit.ci ではなく GitHub Actions 内で実行する** (`pre-commit.yml`)。system hook
  (`dotnet csharpier` / `shellcheck` / `shfmt` / `uvx ruff`) に依存し、pre-commit.ci のサンドボックスでは解決できないため。
- **Thunderstore namespace = `mlshukai`** (MLShukai チーム)。`publish-thunderstore` は secret `TCLI_AUTH_TOKEN` で `tcli publish`。
- **PyPI は Trusted Publishing (OIDC)**。`publish-pypi` は GitHub environment `pypi` で動き **長期 token を使わない**。
- **リポジトリは `Geson-anko/ResoniteIO` → `MLShukai/ResoniteIO` へ移管予定**。CI の非 publish ワークフローは
  移管前でも回せるが、**最初の publish tag は移管完了後に push する** (secret / Trusted Publisher は移管後の repo 前提)。

**Why:** dual artifact (mod + python) を 1 tag で公開し、version 不整合・誤 tag を guard で機械的に弾く設計。
正規 version を csproj に固定したのは Thunderstore packaging (`PackTS`) が csproj から versionNumber を引くため。
組織移管後に publish を始めるのは Trusted Publisher / secret が `MLShukai/ResoniteIO` を owner/repo として照合するから。

**How to apply:** リリース関連タスクでは (1) version を上げるときは csproj `<Version>` + `pyproject.toml` + CHANGELOG を
**必ず 3 点セット** で更新し `uv lock` を回す、(2) リリースノートは `mod/CHANGELOG.md` を編集する (Release 本文を直書きしない)、
(3) Thunderstore namespace を変えない (`mlshukai`)、(4) secret / token を PR・commit・ログに貼らない、
(5) 最初の publish は組織移管完了を待つ。詳細手順は `docs/RELEASE.md` / `release-resonite` skill を参照する。
