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

`mkdocs.yml` をルートに置く理由: docs は Python クライアントと C# mod (アーキテクチャ) の両方を
扱うため。uv プロジェクトは `python/` のままなので、mkdocs は `-f ../mkdocs.yml` 経由で動かす
(justfile レシピが面倒を見る)。

## 2. preview / build

```bash
just docs-serve   # http://localhost:8000 で live-reload preview
just docs-build   # --strict で build (nav 欠落 / 参照破綻 / mkdocstrings 未解決を失敗扱い)
```

`docs-build` は `--strict` なので **これが docs のローカル CI ゲート**。GitHub Actions /
自動デプロイは今のところ無い (`gh-deploy` は後から追加可能)。`just run` には docs-build を
含めない (コミットゲートを軽く保つため)。

ビルド出力 `site/` は `.gitignore` 済み。

**`docs/` は mdformat の対象外**: pre-commit の `mdformat` hook から `docs/` を
除外している (`.pre-commit-config.yaml` の `exclude: ^docs/`)。plain GFM 前提の
mdformat が MkDocs Material 記法 (admonition `!!!` やネストしたコードフェンス) の
本文を de-indent して描画を壊すため。よって admonition 本文の **4 スペース
インデントは手で維持** すること。docs の markdown 検証は mdformat ではなく
`just docs-build` (`--strict`) が担う。なお `.claude/skills/` 配下のこの SKILL.md
自体は mdformat の対象なので、ここでは `!!!` admonition を使わない。

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
  [`.claude/agents/docstring-author.md`](../../agents/docstring-author.md))。
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

## 7. `.claude/` ファイルを触るとき

この SKILL.md を含め `.claude/` 配下を編集するときは
[`edit-dot-claude`](../edit-dot-claude/SKILL.md) の /tmp 経由手順で permission prompt を抑える。
独立した複数ファイルの Write/Edit は [`maximize-parallels`](../maximize-parallels/SKILL.md) に
従い 1 メッセージで並列発火する。
