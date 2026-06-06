---
name: release-resonite
description: "Use when cutting a ResoniteIO release — bump version, tag, and publish the Thunderstore mod + PyPI package, or doing the one-time release setup. Triggers: 'リリース', 'release', 'publish', 'tcli', 'thunderstore publish', 'バージョンを上げる', 'tag を打つ', 'PyPI 公開', 'just mod-pack', 'TCLI_AUTH_TOKEN', 'Trusted Publisher'."
version: 0.1.0
---

# Release ResoniteIO (tag-driven dual publish)

`ResoniteIO` を **1 つの tag で Thunderstore mod (`mlshukai-ResoniteIO`) と PyPI パッケージ (`resoio`) を同時公開** する
ための手順 skill。正規の runbook は [`docs/RELEASE.md`](../../../docs/RELEASE.md)。本 skill はそれを行動可能な要約にしたもの。

- **正規バージョン = csproj `<Version>`** (`mod/src/ResoniteIO/ResoniteIO.csproj`)。`python/pyproject.toml` は lockstep。
- リリースは **`v*` tag の push** で `.github/workflows/publish.yml` を発火させる。
- リリースノートのソースは **`mod/CHANGELOG.md`** ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 形式)。
- Thunderstore namespace = **`mlshukai`** (MLShukai チーム)。

______________________________________________________________________

## 1. リリースを切る (cut a release)

### 1-1. 準備ブランチで bump (version は 3 箇所 lockstep)

```bash
git switch -c chore/$(date +%Y%m%d)/release-vX.Y.Z main
```

1. `mod/src/ResoniteIO/ResoniteIO.csproj` の `<Version>` を `X.Y.Z` に
2. `python/pyproject.toml` の `version` を **同じ** `X.Y.Z` に
3. `mod/CHANGELOG.md` に `## [X.Y.Z] - YYYY-MM-DD` セクションを追加 (`## [Unreleased]` を確定版に移す)
4. `python/` で `uv lock` を回す
5. `just run` (`format`→`gen-proto`→`build`→`test`→`type`) が green になるまで回す
6. PR を出す (`github-ops` skill の `gh pr create` HEREDOC)。**main へのマージはユーザーが実行**

### 1-2. release ブランチ + tag

```bash
git switch -c release/X.Y main      # 最初の minor のみ。以降の patch は再利用
git push -u origin release/X.Y
git switch release/X.Y
git tag vX.Y.Z                       # tag push が publish.yml の唯一のトリガ
git push origin vX.Y.Z
```

`main` への直接 push 禁止規約は守る (tag は `release/X.Y` を指すものを push する)。進捗は `gh run watch` で追う。

______________________________________________________________________

## 2. `publish.yml` の 4 ジョブ (直列)

1. **build** — version guard (tag `X.Y.Z` == csproj `<Version>` == `pyproject.toml` version を検証)
   → `dotnet build mod/src/ResoniteIO/ResoniteIO.csproj -c Release -t:PackTS` で Thunderstore zip、`uv build` で python sdist/wheel
2. **publish-thunderstore** — `tcli publish` (secret `TCLI_AUTH_TOKEN`、`-p:PublishTS=true -p:TcliToken=...`)
3. **publish-pypi** — PyPI Trusted Publishing (OIDC)、GitHub environment `pypi`、**token なし**
4. **github-release** — `mod/CHANGELOG.md` の `## [X.Y.Z]` を抽出して Release ノート化、tag が `(a|b|rc)[0-9]+$` なら `--prerelease`、mod zip + python dists を添付

______________________________________________________________________

## 3. プレリリース (rc)

```bash
git tag vX.Y.ZrcN && git push origin vX.Y.ZrcN   # 例: v0.2.0rc1
```

csproj `<Version>` と `pyproject.toml` も `X.Y.ZrcN` に揃える (version guard が効く)。`github-release` が `--prerelease` を付ける。
本番 tag (`vX.Y.Z`) は rc 検証後に別途打つ。

______________________________________________________________________

## 4. 一回限りの手動セットアップ (Claude は行わない)

人間が GitHub / Thunderstore / PyPI の管理画面で行う:

0. リポジトリを `Geson-anko/ResoniteIO` → `MLShukai/ResoniteIO` に移管。**最初の publish tag は移管後に push**
   (CI の非 publish ワークフローは移管前でも回せる)
1. Thunderstore team `MLShukai` (namespace `mlshukai`) を作成 → service account token を GitHub secret **`TCLI_AUTH_TOKEN`** に登録
2. PyPI Trusted Publisher を設定 (owner `MLShukai` / repo `ResoniteIO` / workflow `publish.yml` / environment `pypi`) +
   GitHub `pypi` environment を作成。test.pypi は任意

> secret / token は PR・commit・ログに貼らない。`gh secret` 操作も人間が行う。

______________________________________________________________________

## 5. トラブルシュート

- **version-guard mismatch で build job が fail**: tag の `X.Y.Z` と csproj `<Version>` と `pyproject.toml` version の
  どれかがズレている。3 箇所を一致させ、`uv lock` の追従も確認してから tag を打ち直す
  (誤 tag は `git push origin :refs/tags/vX.Y.Z` で remote から消してから再 push)。
- **`publish-thunderstore` が認証エラー**: secret `TCLI_AUTH_TOKEN` 未登録 / 期限切れ / 移管後の repo に未設定。§4-1 を確認。
- **Thunderstore namespace 不一致**: `mod/thunderstore.toml` の `namespace` が `mlshukai` (MLShukai team) であること。team 未作成だと publish できない。
- **`publish-pypi` が OIDC で弾かれる**: PyPI Trusted Publisher の owner/repo/workflow/environment が移管後の値と一致しているか、GitHub `pypi` environment が存在するかを確認 (§4-2)。
- **Gale から入らない / load されない**: §6 の検証で `Loading Plugin ResoniteIO` が出るか確認。Gale プロファイル / Steam Launch Options は [`setup-resonite-env`](../setup-resonite-env/SKILL.md) §2 / §3。

______________________________________________________________________

## 6. リリース後検証

- PyPI ページに新版が出て `uv add resoio==X.Y.Z` が通る
- GitHub Release に mod zip + python sdist/wheel が添付され、本文が CHANGELOG と一致 (rc は Pre-release バッジ)
- Thunderstore (`mlshukai/ResoniteIO`) に反映
- **Gale install 検証**: Gale で Thunderstore を検索 → `ResoniteIO` を install → Resonite 起動 → `just log` で `Loading Plugin ResoniteIO` を確認

______________________________________________________________________

## 7. 関連参照

- [`docs/RELEASE.md`](../../../docs/RELEASE.md) — 正規の end-to-end リリース runbook
- [`github-ops`](../github-ops/SKILL.md) — push / PR / `gh` の基本と安全規約
- [`merge-main`](../merge-main/SKILL.md) — release ブランチへの main 取り込み・コンフリクト解消
- [`setup-resonite-env`](../setup-resonite-env/SKILL.md) — Gale プロファイル / 実機 load 検証 (§2 / §6)
