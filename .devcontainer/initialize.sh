#!/usr/bin/env bash
# .devcontainer/initialize.sh
#
# devcontainer の initializeCommand から host 側で実行される冪等スクリプト。
# cwd は workspace root (repo ルート)。compose 方式の devcontainer では
# updateRemoteUserUID が効かないため、ここで host の準備を肩代わりする:
#   1. .env の存在を確認 (無ければ `just init` を促して fail-fast)
#   2. 本番 / debug 用 UDS dir を 0700 で作成 (Docker 任せだと root 所有になる)
#   3. host の uid/gid を .env に HOST_UID / HOST_GID として冪等 upsert
#      (compose の build-arg が読み、container の dev ユーザーと一致させる)

set -euo pipefail

if [[ ! -f .env ]]; then
  echo "ERROR: .env が見つかりません。先に 'just init' を実行してください。" >&2
  exit 1
fi

# UDS socket 用 host ディレクトリを 0700 で先に作る。
#   ~/.resonite-io/      : gRPC IPC (mod ↔ Python)
#   ~/.resonite-io-debug/: debug bridge (container ↔ host-agent)
mkdir -p "$HOME/.resonite-io" "$HOME/.resonite-io-debug"
chmod 0700 "$HOME/.resonite-io" "$HOME/.resonite-io-debug"

# host の uid/gid を .env に冪等 upsert (既存行は削除して追記し直す)。
sed -i '/^HOST_UID=/d; /^HOST_GID=/d' .env
{
  echo "HOST_UID=$(id -u)"
  echo "HOST_GID=$(id -g)"
} >>.env
