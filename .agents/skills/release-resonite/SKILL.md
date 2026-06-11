---
name: release-resonite
description: "Use when cutting a ResoniteIO release — bump version, tag, and publish the Thunderstore mod + PyPI package, or doing the one-time release setup. Triggers: 'リリース', 'release', 'publish', 'tcli', 'thunderstore publish', 'バージョンを上げる', 'tag を打つ', 'PyPI 公開', 'just mod-pack', 'TCLI_AUTH_TOKEN', 'Trusted Publisher'."
version: 0.1.0
---

# Release ResoniteIO (tag-driven dual publish)

`ResoniteIO` を **1 つの tag で mod zip (GitHub Release に添付) と PyPI パッケージ (`resoio`) を同時公開** する
ための手順 skill。正規の runbook は [`RELEASE.md`](../../../RELEASE.md)。本 skill はそれを行動可能な要約にしたもの。

> **配布経路 (重要)**: Thunderstore upload は **停止中** (パッケージ非承認 + layout 不一致のため)。配布は
> **GitHub Release のみ**。mod は `Import > Local mod...` で Gale に入れる。`publish.yml` の
> `publish-thunderstore` ジョブは将来再開用に **コメントアウト残置**。mod zip は `PackTS` (tcli) で
> **ビルド** し続け GitHub Release に添付する (tcli / thunderstore.toml はこの zip 生成に必要)。

- **正規バージョン = csproj `<Version>`** (`mod/src/ResoniteIO/ResoniteIO.csproj`)。`python/pyproject.toml` は lockstep。
- リリースは **`v*` tag の push** で `.github/workflows/publish.yml` を発火させる。
- リリースノートのソースは **`CHANGELOG.md`** ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 形式)。
- mod zip namespace (zip 名 `mlshukai-ResoniteIO-X.Y.Z.zip`) = **`mlshukai`** (`thunderstore.toml`)。

______________________________________________________________________

## 1. リリースを切る (cut a release)

### 1-1. 準備ブランチで bump (version は 3 箇所 lockstep)

```bash
git switch -c chore/$(date +%Y%m%d)/release-vX.Y.Z main
```

1. `mod/src/ResoniteIO/ResoniteIO.csproj` の `<Version>` を `X.Y.Z` に
2. `python/pyproject.toml` の `version` を **同じ** `X.Y.Z` に
3. `CHANGELOG.md` に `## [X.Y.Z] - YYYY-MM-DD` セクションを追加 (`## [Unreleased]` を確定版に移す)。
   **末尾の link reference definitions も忘れず追加する** (`[X.Y.Z]: https://github.com/MLShukai/ResoniteIO/releases/tag/vX.Y.Z` と `[unreleased]: ...compare/vX.Y.Z...HEAD`)。
   これが無いと `mdformat` が見出しを `## \[X.Y.Z\]` にエスケープし、§2-4 の changelog 抽出 (`## \[X.Y.Z\]` regex) が失敗して Release ノートが generic な "Release X.Y.Z" にフォールバックする。Keep a Changelog 慣習どおり全 version 分の `[version]: url` を揃える
4. `python/` で `uv lock` を回す
5. `just run` (`format`→`gen-proto`→`build`→`test`→`type`→`check-renderer-prebuilt`) が green になるまで回す。
   末尾の `check-renderer-prebuilt` が落ちたら Camera v2 Renderer prebuilt が stale。**Resonite のあるローカルで**
   `just renderer-prebuild` → `mod/prebuilt/` の差分を commit する (§7 の prebuilt note 参照)。CI では rebuild できないので
   ここで揃えておかないと publish.yml の build job が drift guard で fail する
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

## 2. `publish.yml` のジョブ

依存グラフ: `build` → `publish-pypi` → `github-release` (Thunderstore upload 停止中)。
`build` が唯一の publish 前ゲート。`publish-thunderstore` ジョブはコメントアウト残置で実行されない。

1. **build** — version guard (tag `X.Y.Z` == csproj `<Version>` == `pyproject.toml` version を検証)
   → **Renderer prebuilt drift guard** (`mod/prebuilt/renderer.sha256` == `scripts/renderer-prebuilt-hash.sh` の再計算値を検証。
   Camera v2 Renderer plugin は UnityEngine.CoreModule 非再配布で CI build 不可のため、committed prebuilt
   `mod/prebuilt/renderer/` をそのまま zip 同梱する。乖離していたら stale として fail)
   → `.github/scripts/fetch-interprocesslib.sh` で InterprocessLib を Thunderstore から取得 (CI には
   Gale プロファイルが無く NuGet fallback も無いため、PackTS の mod compile に必須)
   → `dotnet build mod/src/ResoniteIO/ResoniteIO.csproj -c Release -t:PackTS` で mod zip、`uv build` で python sdist/wheel。
   Collect artifacts で zip を固定名 `ResoniteIO.zip` にもコピー (latest URL 用)
2. **publish-thunderstore** (停止中・コメントアウト残置) — 再開時は fetch-interprocesslib.sh + `tcli publish`
   (secret `TCLI_AUTH_TOKEN`、`-p:PublishTS=true -p:TcliToken=...`)
3. **publish-pypi** — PyPI Trusted Publishing (OIDC)、GitHub environment `pypi`、**token なし**
4. **github-release** — `CHANGELOG.md` の `## [X.Y.Z]` を抽出して Release ノート化、mod zip (versioned + 固定名 `ResoniteIO.zip`) + python dists を添付

______________________________________________________________________

## 3. プレリリース版 (alpha / beta / rc)

**Thunderstore upload 停止中の現状では prerelease を切れる**。GitHub Release / PyPI は prerelease を
受け付けるため、`<Version>` を `0.1.0-rc1` (hyphen 付き、.NET 有効、tag/csproj/pyproject の 3 箇所で完全一致)
にして `v0.1.0-rc1` tag を push すれば、`github-release` の `(a|b|rc)[0-9]+$` → `--prerelease` 判定が発火する。

> store 配布を再開すると、Thunderstore (`tcli`) が `Major.Minor.Patch` 整数のみ (`0.1.0-rc1` 拒否) で
> .NET は hyphen 付き semver を要求するため、両立する prerelease 文字列が無くなり prerelease は再び不可になる。
> 詳細は [`RELEASE.md`](../../../RELEASE.md) §5。

**リリース前検証**: ① `just run` ② `dotnet build ... -t:PackTS` のローカル zip 生成確認 (publish しない)
③ `build` が通れば PyPI → GitHub Release が走るので、tag を打つ前に PyPI Trusted Publisher が有効か確認
(PyPI の version は不可逆)。

______________________________________________________________________

## 4. 一回限りの手動セットアップ (Codex は行わない)

人間が GitHub / Thunderstore / PyPI の管理画面で行う:

0. リポジトリを `Geson-anko/ResoniteIO` → `MLShukai/ResoniteIO` に移管。**最初の publish tag は移管後に push**
   (CI の非 publish ワークフローは移管前でも回せる)
1. (現在不要 — Thunderstore upload 停止中) store 再開時のみ: Thunderstore team `MLShukai` (namespace `mlshukai`)
   を作成 → service account token を GitHub secret **`TCLI_AUTH_TOKEN`** に登録 → `publish-thunderstore` の
   コメントアウトを解除
2. PyPI Trusted Publisher を設定 (owner `MLShukai` / repo `ResoniteIO` / workflow `publish.yml` / environment `pypi`) +
   GitHub `pypi` environment を作成。test.pypi は任意

> secret / token は PR・commit・ログに貼らない。`gh secret` 操作も人間が行う。

______________________________________________________________________

## 5. トラブルシュート

- **version-guard mismatch で build job が fail**: tag の `X.Y.Z` と csproj `<Version>` と `pyproject.toml` version の
  どれかがズレている。3 箇所を一致させ、`uv lock` の追従も確認してから tag を打ち直す
  (誤 tag は `git push origin :refs/tags/vX.Y.Z` で remote から消してから再 push)。
- **Renderer prebuilt drift guard で build job が fail** (`Renderer prebuilt is stale`): Renderer ソース
  (`mod/src/ResoniteIO.Renderer/` ∥ `mod/src/ResoniteIO.RendererShared/` の `.cs` / `.csproj`) を変更したのに
  committed prebuilt `mod/prebuilt/renderer/` を更新していない。**Resonite のあるローカルで** `just renderer-prebuild`
  を実行し `mod/prebuilt/` (DLL/PDB + `renderer.sha256`) の差分を commit してから tag を打ち直す。CI 側では
  UnityEngine.CoreModule が無く rebuild できないため、この修正はローカルでしか行えない (§7 prebuilt note)。
- **`publish-pypi` が OIDC で弾かれる**: PyPI Trusted Publisher の owner/repo/workflow/environment が移管後の値と一致しているか、GitHub `pypi` environment が存在するかを確認 (§4-2)。
- **mod zip が GitHub Release に出ない**: `build` ジョブの PackTS が `mod/build/*.zip` を生成し Collect artifacts が `ResoniteIO.zip` を作るかを確認。InterprocessLib fetch (§2-1) が失敗していると PackTS が compile できない。
- **Gale の local import から入らない / load されない**: supporting plugins (BepisLoader 等) を事前に profile へ入れたか確認 (local import は依存を自動解決しない)。§6 の検証で `Loading Plugin ResoniteIO` が出るか確認。Gale プロファイル / Steam Launch Options は [`setup-resonite-env`](../setup-resonite-env/SKILL.md) §2 / §3。
- **Release ノートが "Release X.Y.Z" のまま (CHANGELOG が反映されない)**: `mdformat` が見出しを `## \[X.Y.Z\]` にエスケープし、`github-release` の抽出 regex (`## \[X.Y.Z\]`) にマッチしていない。CHANGELOG 末尾に該当 version の link reference definition (`[X.Y.Z]: url`) を追加すると見出しが reference link として扱われ mdformat がエスケープしなくなる (§1-1 step 3)。`publish.yml` の regex は変更しない。

______________________________________________________________________

## 6. リリース後検証

- PyPI ページ (distribution `resonite-io`) に新版が出て `uv add resonite-io==X.Y.Z` が通る
- GitHub Release に mod zip (versioned + 固定名 `ResoniteIO.zip`) + python sdist/wheel が添付され、本文が CHANGELOG と一致 (rc は Pre-release バッジ)
- **固定名 latest URL** が機能: `curl -L https://github.com/MLShukai/ResoniteIO/releases/latest/download/ResoniteIO.zip -o /tmp/ResoniteIO.zip` で最新が落ちる
- **Gale install 検証**: 最新 zip を DL → Gale `Import > Local mod...` で import (supporting plugins は事前導入) → Resonite 起動 → `just log` で `Loading Plugin ResoniteIO` を確認

______________________________________________________________________

## 7. Camera v2 Renderer prebuilt note

Camera v2 の Renderer 側 plugin (`ResoniteIO.Renderer`、net472 Unity Mono) は **UnityEngine.CoreModule が
非再配布** なため CI でも Remora SDK でも build できない。そのため Resonite のあるローカルで build した成果物を
**committed prebuilt** として repo に commit し、pack/CI はそれを build せずそのまま mod zip に同梱する。

- 成果物: `mod/prebuilt/renderer/{ResoniteIO.Renderer.dll, ResoniteIO.RendererShared.dll, ResoniteIO.Renderer.pdb}`
  (`.gitignore` の `*.dll`/`*.pdb` ignore を negate して追跡)。source hash は兄弟パス `mod/prebuilt/renderer.sha256`
  (hash file は zip に入れない方針で dir 外に分離)
- 更新: `just renderer-prebuild` (Resonite 必須) が Release build → file-set を `mod/prebuilt/renderer/` に copy →
  `scripts/renderer-prebuilt-hash.sh` で source hash を `renderer.sha256` に書く。実行後 `mod/prebuilt/` を commit
- drift guard: `just check-renderer-prebuilt` (`just run` 末尾に含む) と CI (`publish.yml` build / `dotnet.yml`) が
  committed hash と再計算 hash を照合。Renderer ソースを触って prebuilt 更新を忘れると fail する (§5 troubleshoot)
- thunderstore.toml の `[[build.copy]]` (`./prebuilt/renderer` → `Renderer/ResoniteIO.Renderer/`) で zip 同梱。
  Gale BepisLoader installer が package top-level `Renderer/` を `Renderer/BepInEx/plugins/<FullName>/` へ routing する

______________________________________________________________________

## 8. 関連参照

- [`RELEASE.md`](../../../RELEASE.md) — 正規の end-to-end リリース runbook
- [`github-ops`](../github-ops/SKILL.md) — push / PR / `gh` の基本と安全規約
- [`merge-main`](../merge-main/SKILL.md) — release ブランチへの main 取り込み・コンフリクト解消
- [`setup-resonite-env`](../setup-resonite-env/SKILL.md) — Gale プロファイル / 実機 load 検証 (§2 / §6)
