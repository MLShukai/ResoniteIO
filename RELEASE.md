# リリース手順書 (RELEASE.md)

`ResoniteIO` の **tag-driven リリースパイプライン** の end-to-end runbook。mod zip (GitHub
Release に添付、Gale の `Import > Local mod...` で導入) と PyPI パッケージ (distribution
`resonite-io`、import は `resoio`) の **2 種類の成果物を 1 つの tag で同時に公開する**。

> **配布経路の変更 (重要)**: Thunderstore への upload は **現在停止中**。パッケージが承認されず、
> その layout が store の流儀に合わなかったため、配布は **GitHub Release のみ** に切り替えた。
> `publish.yml` の `publish-thunderstore` ジョブは将来の再開に備えて **コメントアウトで残置**して
> ある。mod zip は従来どおり `PackTS` (tcli) で **ビルド** し、GitHub Release に添付する
> (`thunderstore.toml` / `Directory.Build.targets` / tcli はこの zip 生成に引き続き使う)。

タスク発火型の要約とトラブルシュートは [`.claude/skills/release-resonite/SKILL.md`](.claude/skills/release-resonite/SKILL.md) に、
PR / push / `gh` 操作の基本は [`.claude/skills/github-ops/SKILL.md`](.claude/skills/github-ops/SKILL.md) に集約してある。
本ドキュメントは「実際に 1 リリースを切る」ための正規手順を述べる。

______________________________________________________________________

## 0. 全体像

- **正規バージョンソース = csproj `<Version>`** (`mod/src/ResoniteIO/ResoniteIO.csproj`)。
  `python/pyproject.toml` の `version` は **これと lockstep** で同じ値に保つ。
- リリースは **tag push で発火** する。`v*` パターンの tag を push すると `.github/workflows/publish.yml` が動く。
- リリースノートのソースは **`CHANGELOG.md`** (repo root、[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) 形式)。
  `## [X.Y.Z] - YYYY-MM-DD` セクションが GitHub Release の本文と Thunderstore 同梱 changelog に使われる。
- **Thunderstore namespace = `mlshukai`** (MLShukai チーム)。PyPI distribution name = `resonite-io` (import package は `resoio`)。
- リポジトリは現在 `Geson-anko/ResoniteIO` にあり、**`MLShukai/ResoniteIO` へ移管予定**。
  CI (非 publish) は移管前の `Geson-anko/ResoniteIO` でも回るが、**最初の publish tag は組織移管の完了後に push する**
  (Trusted Publisher / secret は移管後の `MLShukai/ResoniteIO` を前提に設定するため)。

______________________________________________________________________

## 1. CI ワークフロー一覧

`.github/workflows/` に 6 本。前 5 本は PR / push の品質ゲート、最後の 1 本が tag-driven のリリース。

| ワークフロー      | 名前 / 役割                                                                                          | trigger              |
| ----------------- | ---------------------------------------------------------------------------------------------------- | -------------------- |
| `pre-commit.yml`  | Format & Lint (`pre-commit` を GitHub Actions 内で実行)                                              | PR / push            |
| `test.yml`        | Python テスト matrix (3.12 / 3.13 / 3.14、`ubuntu-latest`)                                           | PR / push            |
| `type-check.yml`  | `pyright` strict 型チェック                                                                          | PR / push            |
| `dotnet.yml`      | C# `Core.Tests` のみ (Mod / net472 Renderer は CI から除外)。Renderer prebuilt の drift guard も実行 | PR / push            |
| `proto-check.yml` | `just gen-proto` を回して diff が出ないことを確認 (生成物のコミット漏れ検出)                         | PR / push            |
| `publish.yml`     | リリース (3 ジョブ。Thunderstore upload は停止中で残置)。下記 §3 参照                                | `push: tags: ["v*"]` |

補足:

- **pre-commit は pre-commit.ci ではなく GitHub Actions 内で実行する**。system hook
  (`dotnet csharpier` / `shellcheck` / `shfmt` / `uvx ruff`) に依存しており、pre-commit.ci の
  サンドボックスでは解決できないため。
- **C# CI は `ResoniteIO.Core.Tests` のみ** (Resonite 非依存の Core、`FrameHeader` IPC 契約を含む)。
  **Mod (`ResoniteIO` / `ResoniteIO.Tests`) は clean CI でビルド不可なので除外**する。proprietary DLL 依存のため:
  net472 Renderer は Unity/Renderite、engine bridge は `InterprocessLib.FrooxEngine.dll` (Nytra-InterprocessLib
  Gale mod、Camera v2 receiver が使う) を要求し、`Resonite.GameLibs` fallback はこれを供給しない。Mod とそのテストは
  local `just run` (Gale profile 前提) + manual/e2e で検証する。

______________________________________________________________________

## 2. バージョン lockstep ルール

3 箇所のバージョンが **完全一致** していなければ `publish.yml` の version guard で fail する。

1. tag 名 `vX.Y.Z` の `X.Y.Z`
2. `mod/src/ResoniteIO/ResoniteIO.csproj` の `<Version>` ← **正規ソース**
3. `python/pyproject.toml` の `version`

`<Version>` を上げたら必ず `pyproject.toml` も同じ値に上げ、`python/` で `uv lock` を回して
lockfile を追従させる。この 3 ファイルの bump は **`just bump-version X.Y.Z`**
(`scripts/bump-version.sh`、container 内で実行) が 1 コマンドで行う。
Thunderstore zip の `versionNumber` は `Directory.Build.targets` の `PackTS` が
`--package-version $(Version)` で csproj から渡すので、csproj が single source of truth になる。

______________________________________________________________________

## 3. `publish.yml` のジョブ

tag `vX.Y.Z` の push で発火する。依存グラフは `build` → `publish-pypi` → `github-release`。
(`publish-thunderstore` ジョブは upload 停止中のため **コメントアウトで残置**しており、現行の
依存グラフには含まれない。)

### 3-1. `build` (version guard + 成果物ビルド)

- **version guard**: tag の `X.Y.Z` が csproj `<Version>` および `python/pyproject.toml` の `version` と
  一致するか検証。1 つでも食い違えば即 fail (誤った tag を弾く安全弁)。
- **Renderer prebuilt drift guard**: committed prebuilt (`mod/prebuilt/renderer/`) が Renderer ソースと
  同期しているかを source hash で検証 (`mod/prebuilt/renderer.sha256` と `scripts/renderer-prebuilt-hash.sh` の
  出力を照合)。乖離していれば build より前に fast-fail する (`just renderer-prebuild` でローカル更新を案内)。
- **Thunderstore zip**: `dotnet build mod/src/ResoniteIO/ResoniteIO.csproj -c Release -t:PackTS`
  → `mod/build/mlshukai-ResoniteIO-X.Y.Z.zip` を生成。PackTS は Renderer を live build せず、committed
  prebuilt (`mod/prebuilt/renderer/`) をそのまま同梱する (Renderer は UnityEngine.CoreModule が非再配布なため CI で build 不能)。
- **Python dists**: `uv build` → `python/dist/` に sdist (`.tar.gz`) と wheel (`.whl`)。

### 3-2. `publish-thunderstore` (停止中・コメントアウト残置)

- **現在は無効**。`publish.yml` 内でジョブ全体がコメントアウトされており、tag push でも実行されない。
- 将来 store 配布を再開する場合の中身: `tcli publish` で Thunderstore (`resonite` community) に
  アップロード。認証は GitHub secret **`TCLI_AUTH_TOKEN`**、`-p:PublishTS=true -p:TcliToken=...` を
  `PackTS` に渡す。namespace は `mod/thunderstore.toml` の `mlshukai`。
- なお mod zip 自体は `build` ジョブの `PackTS` で生成され、§3-4 の GitHub Release に添付される
  (store upload とは独立)。

### 3-3. `publish-pypi`

- **PyPI Trusted Publishing (OIDC)** で公開。**長期 API token は使わない**。
- GitHub environment **`pypi`** 上で動き、PyPI 側に登録された Trusted Publisher 設定
  (owner `MLShukai` / repo `ResoniteIO` / workflow `publish.yml` / environment `pypi`) と OIDC で照合される。

### 3-4. `github-release`

- `CHANGELOG.md` (repo root) から **`## [X.Y.Z]` セクションを抽出** して Release ノートにする。
- tag が `(a|b|rc)[0-9]+$` にマッチする場合は **`--prerelease`** を付ける (§5 参照)。
- アセットとして **mod zip (`mlshukai-ResoniteIO-X.Y.Z.zip` + 固定名 `ResoniteIO.zip`) + python
  dists** (sdist/wheel) を添付する。固定名コピーにより
  `https://github.com/MLShukai/ResoniteIO/releases/latest/download/ResoniteIO.zip` で常に最新を
  取得できる (`build` ジョブの "Collect artifacts" で生成)。

______________________________________________________________________

## 4. 通常リリースの手順

ブランチ戦略は vrcpilot から継承し、dual artifact (mod + python) 向けに調整したもの。

### 4-1. 準備ブランチで bump

```bash
git switch -c chore/$(date +%Y%m%d)/release-vX.Y.Z main
```

このブランチで以下を **1 まとめ** に行う:

1. `just bump-version X.Y.Z` (container 内) — csproj `<Version>` / `pyproject.toml` の `version` /
   `uv.lock` の 3 ファイルを lockstep で bump する (§2)
2. `CHANGELOG.md` に `## [X.Y.Z] - YYYY-MM-DD` セクションを追加
   (`## [Unreleased]` の内容を確定版セクションに移し替える。Added / Changed / Fixed 等の見出しは Keep a Changelog に従う)
3. **Renderer ソース (`mod/src/ResoniteIO.Renderer/` / `mod/src/ResoniteIO.RendererShared/`) を変更した release のみ**:
   Resonite のあるローカル環境で `just renderer-prebuild` を実行し、`mod/prebuilt/renderer/` の差分を commit する
   (committed prebuilt が古いと `build` ジョブの drift guard で fail する)
4. `just run` (`format` → `gen-proto` → `build` → `test` → `type` → `check-renderer-prebuilt`) が green になるまで回す

```bash
gh pr create --base main \
  --title "chore(release): vX.Y.Z" \
  --body "..."   # github-ops skill の HEREDOC パターンを使う
```

PR レビュー → **merge は `main` 担当者 (ユーザー) が判断・実行する** (CLAUDE.md「Git 運用」)。

### 4-2. `release/X.Y` ブランチを作る (最初の minor のみ)

`main` に bump がマージされたら、その minor 系列の release ブランチを作る。

```bash
git switch -c release/X.Y main      # 例: release/0.2
git push -u origin release/X.Y
```

同一 minor の以降の patch (`X.Y.1`, `X.Y.2`, ...) はこの `release/X.Y` を再利用する。

### 4-3. tag を打って publish を発火

`release/X.Y` 上で tag を push する。**これが `publish.yml` を起動する唯一のトリガ**。

```bash
git switch release/X.Y
git tag vX.Y.Z                       # annotated にしたい場合は -a -m "..."
git push origin vX.Y.Z
```

> tag push は `main` への直接 push とは別物。CLAUDE.md の「`main` に直接 push しない」規約は守りつつ、
> tag は `release/X.Y` を指すものを push する。

push 後、`publish.yml` のジョブが走る (§3 の依存グラフ参照)。`gh run watch` / GitHub Actions の UI で進捗を追う。

______________________________________________________________________

## 5. プレリリース版 (alpha / beta / rc) — Thunderstore 停止中は可能

> **現状 (Thunderstore upload 停止中)**: 下記の「打てない」制約は **Thunderstore に publish する場合の話**。
> 現在は GitHub Release + PyPI のみで、両者とも prerelease を受け付けるため、`<Version>` を
> `0.1.0-rc1` (hyphen 付き、.NET 有効、3 箇所で完全一致) にすれば `v0.1.0-rc1` tag で prerelease を
> 切れる (`github-release` の `--prerelease` 判定が発火する)。以下の表は store 配布を再開したときの
> 制約として残す。

**Thunderstore が prerelease バージョンを受け付けないため、`v0.2.0rc1` のような prerelease tag で
dual publish をリハーサルすることはできない。** 次の 3 者を同時に満たす prerelease 文字列が存在しない:

| 対象                  | 要求する形式                        | 不可な例                                                                                    |
| --------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------- |
| Thunderstore (`tcli`) | `Major.Minor.Patch` の整数のみ      | `0.1.0-rc1` → `Invalid package version number ... must follow the Major.Minor.Patch format` |
| .NET (`<Version>`)    | hyphen 付き semver                  | `0.1.0rc1` → `not a valid version string` (受け付けるのは `0.1.0-rc1`)                      |
| version guard         | tag / csproj / pyproject の完全一致 | 上記 2 つが両立しない時点で詰む                                                             |

.NET が要求する `0.1.0-rc1` を Thunderstore が拒否し、Thunderstore が許す `0.1.0` は prerelease に
ならない。**Thunderstore に mod を出す限り prerelease チャネルは使えない**と理解する。

`publish.yml` の `github-release` に残る `(a|b|rc)[0-9]+$` → `--prerelease` 判定は上記により dual publish
経路では到達不能 (将来 python 単独 publish に分離した場合のための残置。消しても害は無い)。

### 代わりのリリース前検証

prerelease リハーサルが使えないので、以下で代替する:

1. **ローカル full check**: `just run` (`format` → `gen-proto` → `build` → `test` → `type`)。
2. **mod パッケージングのローカル確認**: `dotnet build mod/src/ResoniteIO/ResoniteIO.csproj -c Release -t:PackTS`
   (publish はしない)。Thunderstore zip が `mod/build/<namespace>-ResoniteIO-<version>.zip` に出るところまで
   確認する。CI と同様 InterprocessLib が必要 (§3-1 / `.github/scripts/fetch-interprocesslib.sh`)。
3. **`build` ジョブが唯一の publish 前ゲート**: `publish.yml` は
   `build` → `publish-pypi` → `github-release` (Thunderstore upload 停止中)。したがって:
   - `build` が落ちれば何も publish されない (version 番号は無傷)。
   - `build` が通れば PyPI publish → GitHub Release の順で進む。PyPI の version は不可逆なので、
     tag を打つ前に PyPI Trusted Publisher が有効か確認する。
4. PyPI 側だけ事前に確かめたいなら TestPyPI の Trusted Publisher を別途設定して `uv build` の成果物を
   手元から upload する。

______________________________________________________________________

## 6. ホットフィックス

公開済み minor 系列にパッチを当てる場合:

1. `release/X.Y` から分岐して修正
2. patch を bump (`X.Y.Z` → `X.Y.(Z+1)`、csproj + pyproject + CHANGELOG + `uv lock`)
3. `just run` green を確認し `release/X.Y` にマージ
4. `release/X.Y` 上で `vX.Y.(Z+1)` tag を push (= publish 発火)
5. **修正を `main` に forward-port** する (release ブランチと main の乖離を防ぐ)

______________________________________________________________________

## 7. 一回限りの手動セットアップ (Claude は行わない)

以下は **人間が GitHub / Thunderstore / PyPI の管理画面で行う** 前提作業。Claude は実施しない。

0. **リポジトリ移管**: `Geson-anko/ResoniteIO` → `MLShukai/ResoniteIO` に transfer する。
   **最初の publish tag はこの移管完了後に push する**。CI (非 publish) は移管前でも回せる。
1. **Thunderstore チーム + secret** (現在は不要 — upload 停止中):
   - store 配布を再開する場合のみ: Thunderstore で team `MLShukai` (namespace `mlshukai`) を作成し、
     team の service account token を GitHub repo secret **`TCLI_AUTH_TOKEN`** に登録して
     `publish.yml` の `publish-thunderstore` ジョブのコメントアウトを解除する。
2. **PyPI Trusted Publisher + environment**:
   - PyPI 側で Trusted Publisher を設定 (owner `MLShukai` / repo `ResoniteIO` / workflow `publish.yml` / environment `pypi`)。
   - GitHub repo に `pypi` environment を作成する (`publish-pypi` ジョブがこの environment で動く)。
   - test.pypi の Trusted Publisher は任意 (rc の事前確認に使うなら設定)。

> secret / token は **PR 説明や commit、ログに貼らない** (github-ops skill §6 と同様)。`gh secret` 操作も人間が行う。

______________________________________________________________________

## 8. リリース後の検証チェックリスト

publish 完了後、以下を確認する:

- [ ] **PyPI ページ** (<https://pypi.org/project/resonite-io/>) に新バージョンが出ている。`pip install resonite-io==X.Y.Z` / `uv add resonite-io==X.Y.Z` が通る
- [ ] **GitHub Release** が作成され、本文が `CHANGELOG.md` の `## [X.Y.Z]` と一致し、**mod zip
  (versioned + 固定名 `ResoniteIO.zip`) + python sdist/wheel** が添付されている
- [ ] **固定名 latest URL** が機能する: `curl -L -o /tmp/ResoniteIO.zip https://github.com/MLShukai/ResoniteIO/releases/latest/download/ResoniteIO.zip` で最新 zip が落ちる
- [ ] **Gale から導入できる**: 最新 zip を DL → Gale `Import > Local mod...` で import (supporting plugins は事前に導入) → Gale 経由で Resonite 起動 → `gale/BepInEx/LogOutput.log` (`just log`) に `Loading Plugin ResoniteIO` が出て load されることを確認
  (Gale プロファイル / 実機 load 検証の詳細は [`setup-resonite-env skill`](.claude/skills/setup-resonite-env/SKILL.md) §2 / §6)

______________________________________________________________________

## 9. 関連参照

- [`.claude/skills/release-resonite/SKILL.md`](.claude/skills/release-resonite/SKILL.md) — タスク発火型のリリース要約 + トラブルシュート
- [`.claude/skills/github-ops/SKILL.md`](.claude/skills/github-ops/SKILL.md) — push / PR / `gh` の基本と安全規約
- [`.claude/skills/merge-main/SKILL.md`](.claude/skills/merge-main/SKILL.md) — release ブランチへの main 取り込み
- [`mod/thunderstore.toml`](mod/thunderstore.toml) / [`mod/Directory.Build.targets`](mod/Directory.Build.targets) — Thunderstore packaging (`PackTS` / namespace / version 受け渡し)
- [`CHANGELOG.md`](CHANGELOG.md) — リリースノートのソース (Keep a Changelog)
