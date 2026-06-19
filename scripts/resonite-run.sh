#!/usr/bin/env bash
# scripts/resonite-run.sh
#
# devcontainer 内 dev ユーザーで実行する Resonite 起動スクリプト。
# ホストの Resonite install (/resonite:ro bind) を書込可能な /opt/resonite に
# rsync したうえで umu-run 経由で Resonite.exe を起動する。
#
# Usage:
#   scripts/resonite-run.sh [ARGS...]
#
# ARGS は Resonite.exe にそのまま渡される追加引数 (省略可)。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="resonite-run"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

RESONITE_SRC="/resonite"
APP_DIR="/opt/resonite"

# ===== 事前チェック =============================================================
check_resonite_src() {
  if [[ ! -f "$RESONITE_SRC/Resonite.exe" ]]; then
    die "$RESONITE_SRC/Resonite.exe が見つかりません。" \
      "ホスト側の ResonitePath が正しく設定されているか、" \
      "devcontainer が \${ResonitePath}:/resonite:ro を bind しているか確認してください。"
  fi
}

check_umu_run() {
  have umu-run || die "umu-run が PATH に見つかりません。" \
    "devcontainer を rebuild して umu-launcher が正しくインストールされているか確認してください。"
}

# ===== Resonite install を書込可能コピーに同期 ===================================
# Resonite は install ディレクトリにログ等を書き込むため、ro bind の /resonite からは
# 直接起動できない。/opt/resonite (HOME 外) に同期してから起動する。
#
# APP_DIR を HOME 外 (/opt) に置く理由:
#   HOME 配下に置くと umu が HOME マウントを S: として扱い、
#   CWD のドライブが S: になって絶対 Unix パス (/dev/shm など) が誤解釈される。
#   /opt 配下なら親がマウントポイントでないため CWD は Z: (→ /) となり、
#   Resonite/Renderer が渡す絶対パスが正しく解決される。
sync_resonite() {
  mkdir -p "$APP_DIR"
  log "Syncing $RESONITE_SRC -> $APP_DIR (初回は ~2GB のコピー、以降は差分のみ)..."
  local changed
  changed="$(rsync -a --delete --itemize-changes "$RESONITE_SRC/" "$APP_DIR/")"
  if [[ -z "$changed" ]]; then
    log "$APP_DIR は最新です (変更なし)。"
  else
    local n
    n="$(printf '%s\n' "$changed" | wc -l)"
    if [[ "$n" -le 20 ]]; then
      printf '%s\n' "$changed" | sed 's/^/  /'
    fi
    log "$n 件を同期しました -> $APP_DIR"
  fi
}

# ===== エントリポイント =========================================================
main() {
  # 引数チェックは行わない: $@ はそのまま Resonite.exe に forward する (下の exec)。
  check_resonite_src
  check_umu_run
  sync_resonite

  # APP_DIR に cd することで CWD ドライブが Z: (→ /) になり、
  # ResoBoot やレンダラが渡す絶対 Unix パスが正しく解決される (entrypoint.sh と同じ理由)。
  cd "$APP_DIR"

  log "Starting Resonite via umu-run..."
  exec umu-run /opt/resonite/Resonite.exe -SkipIntroTutorial "$@"
}

main "$@"
