#!/usr/bin/env bash
# .devcontainer/entrypoint.sh
#
# dev コンテナ起動時に USER dev として実行されるエントリポイント。
# 主な役割:
#   1. AppArmor による非特権 user namespace 制限のチェック (hard fail)
#      pressure-vessel (Steam Linux Runtime) が unprivileged userns を必要とするため。
#   2. コンテナ毎にユニークな machine-id を生成。
#   3. compose の command (sleep infinity) を exec で引き継ぐ。
#
# Resonite 実際の起動は scripts/resonite-run.sh が行う (justfile の resonite-up レシピ)。

set -euo pipefail

# ---------------------------------------------------------------------------
# 1. AppArmor: 非特権 user namespace チェック (hard fail)
# ---------------------------------------------------------------------------
# pressure-vessel (Steam Linux Runtime) は unprivileged user namespace を必要とする。
# Ubuntu 24.04 以降はデフォルトで AppArmor による制限が有効で、
# コンテナ内から sysctl で変更できない (ホスト設定)。
# security_opt: apparmor=unconfined を compose に設定しているが、
# ホスト側の kernel.apparmor_restrict_unprivileged_userns が 1 の場合は
# apparmor=unconfined でも制限が残るケースがある。
# unshare で実際に試して失敗した場合のみ hard fail にする。
if ! unshare --user --map-root-user --mount true 2>/dev/null; then
  echo "ERROR: 非特権 user namespace が作成できません。" >&2
  echo "  pressure-vessel (Steam Linux Runtime) は unprivileged user namespace を必要とします。" >&2
  echo "  これはコンテナ内から変更できないホスト設定です。" >&2
  echo "" >&2
  echo "  対処方法:" >&2
  echo "  Temporary:  sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0" >&2
  echo "  Persistent: echo 'kernel.apparmor_restrict_unprivileged_userns=0' | sudo tee /etc/sysctl.d/99-resonite-userns.conf && sudo sysctl --system" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. machine-id 生成 (コンテナ毎にユニーク化)
# ---------------------------------------------------------------------------
# /etc/machine-id は Dockerfile で dev 所有の空ファイルとして作成済み。
tr -d - </proc/sys/kernel/random/uuid >/etc/machine-id

# ---------------------------------------------------------------------------
# 3. compose の command を exec で起動
# ---------------------------------------------------------------------------
exec "$@"
