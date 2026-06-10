---
name: write-docs
description: "Use when writing or extending the ResoniteIO documentation site (MkDocs Material + mkdocstrings). Covers where docs live, how to preview/build, the per-modality API-page convention, and what to update when a modality is added. Triggers: 'ドキュメントサイト', 'docs site', 'docs を更新', 'mkdocs', 'mkdocstrings', 'API reference を追加', 'docs-serve', 'docs-build', 'docs page', 'ドキュメント追加'."
version: 0.1.0
---

# Write / Extend the Docs Site

ResoniteIO の公開ドキュメントは **MkDocs Material + `mkdocstrings[python]`** で構成する
(pamiq-core の docs を手本にした)。記述言語は **英語**。

## 1. 配置 (どこに何があるか)

| もの                | パス                                                            |
| ------------------- | --------------------------------------------------------------- |
| MkDocs 設定         | リポジトリルート `mkdocs.yml`                                   |
| ドキュメント本体    | リポジトリルート `docs/`                                        |
| Python API の生成元 | `python/src/resoio/*.py` の docstring (mkdocstrings が静的解析) |
| docs 依存           | `python/pyproject.toml` の uv `[dependency-groups].docs`        |
| アイコン / favicon  | `docs/assets/icon.png` (`theme.logo` / `theme.favicon`)         |

`mkdocs.yml` をルートに置く理由: docs は Python クライアントと C# mod (アーキテクチャ) の両方を
扱うため。uv プロジェクトは `python/` のままなので、mkdocs は `-f ../mkdocs.yml` 経由で動かす
(justfile レシピが面倒を見る)。

**ユーザー docs と project docs を分ける**: `docs/` は **公開サイト (ユーザー向け) 専用**。
RELEASE.md などの maintainer / プロジェクト向けドキュメントは **repo root** に置く
(`resonite_io_plan.md` / `AGENTS.md` / `README.md` と同列、GitHub 上で読む)。`docs/` に
maintainer doc を混ぜない (混ぜると mkdocs が拾い、`exclude_docs` での除外管理が増える)。

アイコンは **master 1 つ + 派生 + symlink** で重複と手作業を避ける:

- **master** = repo root の `icon.png` (full-size、commit する。現状 1254x1254)。これが唯一の真。
- **派生** = `mod/icon.png` (256x256)。Thunderstore は **256x256 必須** で `mod/thunderstore.toml`
  の `[build].icon` が参照する。master から `scripts/resize_icon.py` で生成する。手で作らない:
  `just icon` を叩くか、`icon.png` を変更して commit すれば pre-commit の `resize-icon` hook が
  自動再生成する (stale なら fail して再 stage を促す)。Pillow は justfile / pre-commit で
  **版を pin** し (現 `pillow==12.2.0`)、比較は **pixel ベース** なので PNG 再エンコード差では
  rewrite されない (環境差での誤検知を防ぐ)。
- **docs** = `docs/assets/icon.png` は `mod/icon.png` への相対 symlink (`../../mod/icon.png`)。
  mkdocs は symlink を辿って site/ に実体をコピーするので公開サイトには実ファイルが載る。

master を full-size で持つので `check-added-large-files` の上限を `--maxkb=2048` に緩めてある。
Material の `theme.logo` キーは header 画像用の名前だが、中身はブランドアイコン (ロゴ文字ではない)。

## 2. preview / build

```bash
just docs-serve   # http://localhost:8000 で live-reload preview
just docs-build   # --strict で build (nav 欠落 / 参照破綻 / mkdocstrings 未解決を失敗扱い)
```

`docs-build` は `--strict` なので **これが docs のローカル CI ゲート**。CI でのデプロイは
§2.1 の mike workflow が担う。`just run` には docs-build を含めない (コミットゲートを軽く保つため)。

ビルド出力 `site/` は `.gitignore` 済み。

**`docs/` は mdformat の対象外**: pre-commit の `mdformat` hook から `docs/` を
除外している (`.pre-commit-config.yaml` の `exclude: ^docs/`)。plain GFM 前提の
mdformat が MkDocs Material 記法 (admonition `!!!` やネストしたコードフェンス) の
本文を de-indent して描画を壊すため。よって admonition 本文の **4 スペース
インデントは手で維持** すること。docs の markdown 検証は mdformat ではなく
`just docs-build` (`--strict`) が担う。なお `.agents/skills/` 配下のこの SKILL.md
自体は mdformat の対象なので、ここでは `!!!` admonition を使わない。

## 2.1 バージョン管理とデプロイ (mike + CI)

docs は **mike** で複数バージョンを `gh-pages` に配置し、Material の version selector で
切り替える (Sphinx/ReadTheDocs 相当)。デプロイは `.github/workflows/docs.yml` が担う:

- **main へ push** → `dev` バージョンを更新 (開発版 docs)。
- **stable な `v*` tag** → `<X.Y.Z>` を発行し `latest` alias を最新へ移動、default に設定
  (サイトルートは `latest` にリダイレクト)。
- **prerelease tag** (`vX.Y.Za1` 等) → `<X.Y.Z>` のみ発行し `latest` は動かさない。

`mkdocs.yml` の `extra.version.provider: mike` + `default: latest` が selector を有効化する。
ローカルの `just docs-serve` / `just docs-build` は mike を介さない素の mkdocs なので、
selector は出ない (versions.json が無いだけで build は通る)。GitHub Pages のソースは
`gh-pages` ブランチ (初回 deploy で自動作成、Pages の有効化は repo admin の 1 回設定)。

docs deps (`mkdocs` / `mkdocs-material` / `mkdocstrings` / `mike`) は `python/pyproject.toml`
の uv `docs` グループにある。

## 3. API ページ規約

モダリティごとに `docs/api/<modality>.md` を **1 枚** 作り、mkdocstrings の `:::`
ディレクティブで公開シンボルを束ねる。最小ページの形:

```markdown
# Camera

::: resoio.camera.CameraClient

::: resoio.camera.Frame
```

- 列挙するシンボルは `python/src/resoio/__init__.py` の `__all__` (= 公開 API) に合わせる。
  各モダリティの client class + dataclass / enum / 定数を明示的に書く。
- 描画内容は **ソースの docstring がそのまま** 出る。docstring は英語 + Google スタイル
  (`docstring_style: google` を `mkdocs.yml` で指定)。**ドキュメント品質はソースの docstring に
  宿る** ので、API ページ自体に説明を書き足すより、ソースの docstring を直す方が筋が良い
  (docstring の新規/polish は `docstring-author` agent に任せられる →
  [`.codex/agents/docstring-author.toml`](../../../.codex/agents/docstring-author.toml))。
- グローバルな mkdocstrings オプション (`show_source` / `members_order` 等) は `mkdocs.yml` の
  handler 設定で一括管理する。ページ側で個別 override は原則しない。

## 4. 散文ページ

- `docs/index.md` — 概要・設計思想・主要リンク。
- `docs/getting-started/` — `installation.md` (Thunderstore / PyPI は placeholder + ソース
  ビルド), `quickstart.md`。
- `docs/architecture/` — `overview.md` (Core/Mod 二層 + gRPC/UDS), `modalities.md` (全
  モダリティ表), `csharp-mod.md` (C# の手書きリファレンス)。
- `docs/cli.md` — `resoio` flat command 一覧。

これらは手書き。コード例や表は実装に追従させる (CLI コマンドやモダリティの方向/RPC 種別は
`resonite_io_plan.md` と各 `*.proto` が正)。

## 4.1 図は mermaid で書く

図は ASCII アートではなく **mermaid** で書く。mermaid という言語指定のコードフェンスを使い、
`mkdocs.yml` の `pymdownx.superfences` custom_fence で有効化済み (Material が mermaid.js を
自動ロード)。例は `docs/architecture/overview.md` のアーキテクチャ図。山括弧 `<` `>` を含む
ラベルは `&lt;` `&gt;` でエスケープする (mermaid は山括弧を HTML と解釈するため)。

## 5. C# は自動 API 無し

**mkdocstrings は C# を扱えない** (C# handler は存在せず、要望 issue は "not planned")。
Python と C# を両対応する「Material 品質」の単一ツールは無いと確認済み (Doxygen / Breathe は
見た目と片側の描画品質を犠牲にする)。よって C# は `docs/architecture/csharp-mod.md` の
**手書き概念ページ** でカバーし、深掘りは `resonite_io_plan.md` と `add-new-modality` skill に
リンクする。クラス単位の C# API ref は今回スコープ外。

## 6. モダリティを追加したときの docs 手順

新規モダリティ (`add-new-modality` skill 参照) を足したら、docs も更新する:

1. `docs/api/<modality>.md` を新規作成 (§3 の形)。
2. `mkdocs.yml` の `nav:` → `API Reference:` に 1 行追加。
3. `docs/architecture/modalities.md` のモダリティ表に 1 行追加 (方向・RPC 種別・client へのリンク)。
4. `just docs-build` が `--strict` で通ることを確認。

クロスリンク: [`add-new-modality`](../add-new-modality/SKILL.md) skill。

## 7. Codex 設定ファイルを触るとき

Codex 向けの永続指示は root `AGENTS.md`、repo skills は `.agents/skills/`、
custom subagents は `.codex/agents/*.toml` に置く。これらを編集するときは通常の
repo ファイルとして扱い、独立した複数ファイルの読み取り・編集は
[`maximize-parallels`](../maximize-parallels/SKILL.md) に従って並列化する。
