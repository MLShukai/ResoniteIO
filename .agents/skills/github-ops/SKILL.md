---
name: github-ops
description: "Use when performing GitHub operations from container — creating/reviewing PRs (`gh pr create`, `gh pr view`, `gh pr checks`), managing issues, pushing branches, or authenticating gh CLI. Triggers: 'gh pr create', 'gh pr', 'gh issue', 'gh auth', 'PR を作成', 'PR を送る', 'pull request を作る', 'git push', 'PR レビュー', 'issue を立てる'."
version: 0.1.0
---

# GitHub Operations (gh CLI)

resonite-io リポジトリでの GitHub 連携 (PR / issue / push) のための skill。**`gh` CLI と `git` はコンテナ内で実行する前提**で、Dockerfile に `gh` apt パッケージを同梱済み (`.codex/rules/default.rules` で `Bash(git push:*)` / `Bash(gh:*)` を allow 済み)。

このリポジトリの git 運用規約 ([AGENTS.md](../../../AGENTS.md) の「Git 運用」「自走開発フロー」節) を `gh` 操作に落とし込む手順書。

______________________________________________________________________

## 1. 認証 (gh auth)

`gh` の認証情報はコンテナ image には焼かれない。コンテナ起動ごとに以下のいずれかで認証する。

### 経路 A: `GH_TOKEN` 環境変数 (推奨)

- host の `.env` または shell に `GH_TOKEN=ghp_xxx` (または fine-grained PAT) を入れ、`compose.yml` の `environment:` で container に流す
- `gh` は `GH_TOKEN` を最優先で参照するため `gh auth login` 不要
- PAT に必要な scope: `repo` (private repo を扱うなら) / `workflow` (CI 設定を触るなら) / `read:org`
- token の漏洩を避けるため `.env` は gitignore 済みであることを確認 (`git check-ignore -v .env`)

### 経路 B: `gh auth login` を都度実行

- `gh auth login --hostname github.com --git-protocol https --web` を container 内で実行
- ブラウザ device flow が開く (host 側 browser で承認)。container ↔ host 間で URL を手でコピペ
- 認証情報は `~/.config/gh/hosts.yml` に書かれるが、これは container の一時 FS なので **再ビルド後に消える**。`~/.config/gh` を named volume / bind mount にしておくと永続化できる

### 確認

```bash
gh auth status                # 認証状態と scope を表示
gh api user --jq .login       # 自分の username を返せれば OK
```

______________________________________________________________________

## 2. ブランチを push する

AGENTS.md の規約:

- **`main` に直接 commit しない**。作業ブランチは `main` から `<種別>/<日付>/<内容>` で分岐 (`種別` = `feature` / `fix` / `refactor` / `docs` / `chore`)
- 例: `feature/20260521/manipulation-skeleton` / `fix/20260521/uds-permission`

```bash
git switch -c feature/$(date +%Y%m%d)/<short-slug> main
# ... 作業・コミット ...
git push -u origin HEAD        # 初回 push。-u で upstream を貼る
git push                       # 2 回目以降
```

`-u origin HEAD` は branch 名を引数に書かなくて済むので推奨。`git push --force-with-lease` は rebase 直後など必要時のみ。`--force` は使わない (履歴破壊を防ぐ)。

______________________________________________________________________

## 3. PR を作成する (`gh pr create`)

### 基本フロー

```bash
gh pr create \
  --base main \
  --title "<種別>(<スコープ>): <内容>" \
  --body "$(cat <<'EOF'
## Summary
- <変更点 1 つ目>
- <変更点 2 つ目>

## Test plan
- [ ] `just run` が green
- [ ] (関連する手動検証)
EOF
)"
```

タイトルは **コミットメッセージと同じ形式** で書く (`<種別>(<スコープ>): <内容>`、種別 = `feat` / `fix` / `docs` / `style` / `refactor` / `test` / `chore`、スコープ = `mod` / `python` / `proto` / `scripts` / `ci` / `docs` または `mod/camera` / `python/locomotion` のようなモダリティ単位)。

- `--draft` で WIP として作る
- `--base main` は本リポでは省略可だが、ベース branch を明示する習慣を推奨
- 複数 commit を含むブランチでは PR description で commit を要約する (PR タイトルは最も支配的な変更を反映)
- **`main` へのマージはユーザーが判断・実行する** ため、PR を立てたらレビュー待ち。Codex から `gh pr merge` は基本叩かない

### HEREDOC でフォーマット崩れを防ぐ

`--body "$(cat <<'EOF' ... EOF)"` の **シングルクォート** が重要。これが無いと `$` や backtick が shell に展開される。

______________________________________________________________________

## 4. PR をレビュー・確認する

```bash
gh pr list                          # 開いている PR 一覧
gh pr view <番号>                   # メタ情報 + body
gh pr view <番号> --comments        # コメント込み
gh pr diff <番号>                   # diff を pager 無しで表示
gh pr checks <番号>                 # CI status
gh pr checks <番号> --watch         # CI 完了まで follow

# コメント取得 (review comment は API 経由)
gh api repos/Geson-anko/resonite-io/pulls/<番号>/comments

# Review コメント (inline) の作成
gh pr review <番号> --comment --body "..."
gh pr review <番号> --approve
gh pr review <番号> --request-changes --body "..."
```

URL からの参照も可: `gh pr view https://github.com/.../pull/123`。

CI が長い場合は `gh pr checks <番号> --watch` を別ターミナルで走らせる (background 実行に向く)。

______________________________________________________________________

## 5. Issue 操作

```bash
gh issue create --title "..." --body "..." --label bug
gh issue list --state open --label "step-6"
gh issue view <番号> --comments
gh issue close <番号> --comment "..."
gh issue comment <番号> --body "..."
```

resonite-io では bug tracker は GitHub Issues に集約。Linear や Jira 等の外部 tracker は使っていない。

______________________________________________________________________

## 6. 安全規約 (AGENTS.md と整合)

- **`main` への直接 push / force-push を絶対にしない**。仮にユーザーが指示しても、`feature/...` ブランチを切ってから PR にする
- `git push --force` / `git push --force-with-lease` は **同名 branch を自分が rebase した直後** のみ。upstream を書き換える可能性のあるブランチ (他人が触っているもの、`main`) には絶対に使わない
- `gh pr merge` / `gh pr close` は **ユーザー判断**。Codex から自発的にマージ・close しない
- `gh release create` / repo 設定変更 (`gh repo edit`) も同様にユーザー確認
- PR description / commit body に **secret や `.env` の中身を貼らない**。`gh secret` 操作も基本ユーザーが行う

______________________________________________________________________

## 7. ローカル PR ドラフト

ネット越し API を叩く前に local で固めたい場合:

```bash
git log main..HEAD --oneline       # PR に含まれる commits
git diff main...HEAD               # PR 全体の diff (... に注意; .. ではない)
git log main..HEAD --format="%s"   # commit subject 一覧
```

これを材料に PR title / body を組み立て、最後に `gh pr create` で投げる。

______________________________________________________________________

## 8. トラブルシュート

### `gh: command not found`

Dockerfile に gh インストール step は入っているはず ([Dockerfile](../../../.devcontainer/Dockerfile))。image が古い場合は devcontainer を再ビルドする (VS Code「Dev Containers: Rebuild Container」、または `docker compose -f compose.yml build`)。

### `HTTP 401: Bad credentials`

`GH_TOKEN` が空 or 期限切れ / scope 不足。`gh auth status` で確認し、host で PAT を更新する。

### `Updates were rejected because the remote contains work that you do not have locally`

`main` が進んでいる。**`git pull --rebase origin main`** を作業ブランチ上で当て、conflict を解消してから `git push --force-with-lease` (force-with-lease は **upstream が自分の最後の push と一致する場合のみ通す** 安全側の force)。

### `pre-commit hook が PR push を遮る`

`git push --no-verify` は使わない (AGENTS.md と CI のガード趣旨に反する)。hook が落ちた根本原因 (`just run` の中で何が fail したか) を fix する。

______________________________________________________________________

## 9. 関連設定・参照

- [`Dockerfile`](../../../.devcontainer/Dockerfile) — `gh` apt パッケージのインストール block
- [`.codex/rules/default.rules`](../../../.codex/rules/default.rules) — `Bash(git push:*)` / `Bash(gh:*)` の allow 設定
- [`AGENTS.md`](../../../AGENTS.md) — Git 運用節 (branch / commit 命名規約)
- [`memory/feedback_git_no_pager.md`](../../../memory/feedback_git_no_pager.md) — `git --no-pager` は不要 (`gh` 側も同様に pager 自動 bypass)
