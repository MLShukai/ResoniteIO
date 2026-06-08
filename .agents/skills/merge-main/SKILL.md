---
name: merge-main
description: "Use right before creating a PR at the end of work — sync the latest main into the working branch and resolve conflicts so the PR diffs cleanly against an up-to-date base. Triggers: 'PR を出す前', 'main を最新化', 'main をマージ', 'main に追従', 'merge main', 'コンフリクト解決', 'sync main', 'rebase で揉めた'."
version: 0.1.0
---

# Merge latest main before PR

作業の最後に PR を出す **直前** で実行する手順。`main` をリモート最新に更新し、自分の作業ブランチに取り込んで (merge)、conflict を解消してから PR を立てる。これにより PR が最新の base に対して clean に diff する。

AGENTS.md「Git 運用」「自走開発フロー」と整合。**`main` への直接 commit / push はしない**。取り込みは作業ブランチ側で行う。PR 作成自体は [github-ops skill](../github-ops/SKILL.md) を参照。

このリポジトリの方針は **rebase ではなく merge** で main を取り込む (履歴上に merge commit が残ることを許容し、自ブランチの commit hash を書き換えない)。

______________________________________________________________________

## 前提チェック

取り込みの前に作業ブランチが clean であること。未コミットの変更があると merge が止まる。

```bash
git status --short            # 出力が空であること (clean)
git branch --show-current     # main でないこと (作業ブランチ上にいる)
```

- 未コミットの変更があるなら **先に commit する** (1 関心事 1 commit)。中途半端なら `git stash` で退避し、merge 後に `git stash pop`
- `main` ブランチ上にいたら誤り。作業ブランチに `git switch` する

______________________________________________________________________

## 手順

### 1. リモート最新を取得

```bash
git fetch origin main
```

`git pull` ではなく `fetch` を使う (ローカル `main` を介さず `origin/main` を直接 merge 対象にする)。ローカル `main` ブランチの更新は不要。

### 2. main が進んでいるか確認

```bash
git log HEAD..origin/main --oneline    # 自ブランチに無い main 側の新規 commit
```

- **出力が空** → main は進んでいない。取り込み不要。そのまま PR 作成へ
- **commit が並ぶ** → main が進んでいる。次の merge へ

### 3. origin/main を作業ブランチに merge

```bash
git merge origin/main
```

- conflict 無し → merge commit が作られる (または fast-forward)。手順 5 へ
- conflict 発生 → 手順 4 へ

merge commit message はデフォルト (`Merge remote-tracking branch 'origin/main' into <branch>`) でよい。編集が必要なら理由を一言添える。

### 4. conflict 解消

```bash
git status                     # Unmerged paths を確認
git diff --name-only --diff-filter=U   # conflict した file 一覧
```

各 conflict file を開き `<<<<<<<` / `=======` / `>>>>>>>` マーカーを解消する。

- **両者の意図を保持する**。main 側の変更を握り潰さない / 自分の変更も捨てない。どちらか一方を機械的に採用 (`--ours` / `--theirs`) する前に、本当にもう一方が不要か確認する
- 判断が割れる conflict (両方が同じ関数を別意図で書き換えた等) は **勝手に決めず、何が衝突しているか名指しでユーザーに確認** (AGENTS.md 開発原則 1)
- proto / 生成物の conflict は特に注意: `proto/**/*.proto` が両側で変わった場合、解消後に **`just gen-proto` を再実行** して生成物 (`python/src/resoio/_generated/`) を作り直し、生成物側の conflict はそれで上書きする (手で潰さない)
- 解消したら stage: `git add <file>`
- 全 file 解消後: `git merge --continue` (または `git commit`)
- 中断したくなったら `git merge --abort` で merge 前に戻せる

### 5. 取り込み後の検証

main を取り込んだ結果コードが壊れていないか確認する。**`just run` を回して全 green** であることが PR の前提 (AGENTS.md 自走開発フロー)。

```bash
just run                       # format → gen-proto → build → test → type
```

- gen-proto の差分が出たら commit に含める (proto を取り込んだ場合に起こりうる)
- test が落ちたら、main 側の変更と自分の変更の **意味的な衝突** (テキスト conflict は無かったが論理が壊れた) を疑う。修正して再度 green にする

### 6. push して PR 作成

```bash
git push                       # 既に upstream があれば引数不要
```

以降の PR 作成は [github-ops skill](../github-ops/SKILL.md) の `gh pr create` 手順に従う。

______________________________________________________________________

## やってはいけないこと

- **ローカル `main` を作業ブランチに直接 commit / push しない**。取り込みは作業ブランチ側のみ
- conflict を `git checkout --theirs .` 等で **一括上書きしない** (意図しない握り潰しの温床)
- conflict を残したまま `git add` / commit しない (`<<<<<<<` マーカーが混入する)
- 取り込み後に `just run` を省略しない。テキスト conflict が無くても論理は壊れうる
- `git push --force` しない。merge による取り込みは履歴を書き換えないので force は不要

______________________________________________________________________

## rebase を使いたくなったら

このリポジトリは **merge を既定** とする。`git pull --rebase` は自ブランチの commit hash を書き換え、push 済みブランチでは `--force-with-lease` が必要になる。共有/レビュー中のブランチでは履歴の安定性を優先して **merge** を使う。rebase が必要な特殊事情があるなら、その理由をユーザーに確認してから行う。

______________________________________________________________________

## 関連参照

- [github-ops skill](../github-ops/SKILL.md) — push / `gh pr create` / `Updates were rejected` 系トラブルシュート
- [AGENTS.md](../../../AGENTS.md) — 「Git 運用」「自走開発フロー」節
