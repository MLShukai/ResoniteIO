#!/usr/bin/env bash
# scripts/resonite-ctl.sh
#
# devcontainer 内で mod 込み Resonite の起動・停止・状態確認を行う制御スクリプト。
# 起動は scripts/resonite-run.sh (umu-run + hookfxr/doorstop) を background で叩く。
# 停止・状態確認は Resonite.exe / Renderite.Renderer.exe を名前 (pgrep/pkill) で扱う。
#
# Usage:
#   scripts/resonite-ctl.sh start [ARGS...]   # mod 込みで background 起動 (即 return)
#   scripts/resonite-ctl.sh stop              # SIGTERM→3s→SIGKILL の二段構え
#   scripts/resonite-ctl.sh status            # 実行状態を表示

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="resonite-ctl"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Gale プロファイル (mod 一式の在処)。compose が GalePath=/workspace/gale を渡す。
GALE_DIR="${GalePath:-/workspace/gale}"

# pgrep -f は cmdline 全体に対してマッチする。Resonite.exe / Renderite.Renderer.exe は
# 互いに部分文字列ではないので 2 パターンで分離できる。umu-run ラッパも cmdline に
# "Resonite.exe" を含むため stop で一緒に落ちるが、container には守るべき Steam
# セッションが無いので問題ない (むしろ launch chain ごとクリーンに片付く)。
RESONITE_PATTERN="Resonite.exe"
RENDERITE_PATTERN="Renderite.Renderer.exe"
TERMINATION_TIMEOUT_ITERS=10 # 0.3s * 10 = 3s
POLL_INTERVAL_SEC=0.3

# 一致プロセスを "pid cmdline" 形式で列挙 (無ければ空文字列)。
_pids() { pgrep -af "$1" || true; }

# 一致プロセスが居れば 0、居なければ非 0。
_running() { pgrep -f "$1" >/dev/null 2>&1; }

cmd_start() {
  if _running "$RESONITE_PATTERN"; then
    die "Resonite は既に起動しています。先に 'just resonite-stop' で停止してください。" \
      "$(_pids "$RESONITE_PATTERN")"
  fi
  if [[ ! -d "$GALE_DIR/BepInEx" ]]; then
    die "$GALE_DIR/BepInEx が見つかりません (mod 起動には Gale プロファイルが必要)。" \
      "'just deploy-mod' で配置し 'just check-gale' で確認、" \
      "または素の Resonite を起動するなら 'just resonite-vanilla' を使ってください。"
  fi
  local logdir="$GALE_DIR/BepInEx"
  mkdir -p "$logdir"
  local logfile="$logdir/umu-launch.log"
  # setsid + & + </dev/null で完全 detach し即 return する。
  # ログ (umu/Proton の起動ノイズ) は umu-launch.log へ。mod 本体のログは
  # BepInEx が同 dir の LogOutput.log に書く (`just log` の対象)。
  setsid bash "$SCRIPT_DIR/resonite-run.sh" "$@" >"$logfile" 2>&1 </dev/null &
  log "Resonite を background 起動しました (launcher pid=$!)。"
  log "umu/Proton ログ: $logfile  /  mod ログ: just log"
}

cmd_stop() {
  local before
  before="$(
    _pids "$RESONITE_PATTERN"
    _pids "$RENDERITE_PATTERN"
  )"
  if [[ -z "$before" ]]; then
    log "Resonite は起動していません (no-op)。"
    return 0
  fi

  log "Resonite / Renderite に SIGTERM を送信します..."
  pkill -TERM -f "$RESONITE_PATTERN" || true
  pkill -TERM -f "$RENDERITE_PATTERN" || true

  local i
  for ((i = 0; i < TERMINATION_TIMEOUT_ITERS; i++)); do
    sleep "$POLL_INTERVAL_SEC"
    if ! _running "$RESONITE_PATTERN" && ! _running "$RENDERITE_PATTERN"; then
      log "停止しました。"
      return 0
    fi
  done

  warn "SIGTERM で停止しなかったため SIGKILL します。"
  pkill -KILL -f "$RESONITE_PATTERN" || true
  pkill -KILL -f "$RENDERITE_PATTERN" || true
  log "SIGKILL を送信しました。"
}

cmd_status() {
  local resonite renderite
  resonite="$(_pids "$RESONITE_PATTERN")"
  renderite="$(_pids "$RENDERITE_PATTERN")"

  if [[ -n "$resonite" ]]; then
    log "Resonite: 起動中"
    printf '%s\n' "$resonite" | sed 's/^/  /'
  else
    log "Resonite: 停止"
  fi
  if [[ -n "$renderite" ]]; then
    log "Renderite: 起動中"
    printf '%s\n' "$renderite" | sed 's/^/  /'
  else
    log "Renderite: 停止"
  fi
}

main() {
  case "${1:-}" in
    start)
      shift
      cmd_start "$@"
      ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    *) die "usage: resonite-ctl.sh {start|stop|status} [args...]" ;;
  esac
}

main "$@"
