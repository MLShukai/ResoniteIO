#!/usr/bin/env bash
# scripts/resonite-run.sh
#
# devcontainer 内 dev ユーザーで実行する Resonite 起動スクリプト。
# ホストの Resonite install (/resonite:ro bind) を書込可能な /opt/resonite に
# rsync したうえで umu-run 経由で Resonite.exe を起動する。
#
# 既定は **Gale プロファイル (./gale = /workspace/gale) を読み込んで mod 込みで起動**
# する。engine 側は hookfxr (--hookfxr-enable --bepinex-target)、Renderer 側は
# doorstop (--doorstop-target-assembly + WINEDLLOVERRIDES="winhttp=n,b" で hook 版
# winhttp プロキシを Wine に読ませる) で mod をロードする。加えて pressure-vessel に
# Gale プロファイルを bind 共有する (main() 参照)。
#
# --vanilla を付けると mod を読まない素の Resonite を起動する (起動確認用)。
#
# Usage:
#   scripts/resonite-run.sh [--vanilla] [ARGS...]
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
# Gale プロファイル (mod 一式の在処)。compose が GalePath=/workspace/gale を渡す。
GALE_DIR="${GalePath:-/workspace/gale}"

# mode (mod / vanilla) は先頭引数 --vanilla で切替える。剥がした残りは Resonite に forward。
VANILLA=0
if [[ "${1:-}" == "--vanilla" ]]; then
  VANILLA=1
  shift
fi

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

# mod mode は Gale プロファイルの BepInEx を必須とする (vanilla fallback はしない)。
check_gale_profile() {
  if [[ ! -d "$GALE_DIR/BepInEx" ]]; then
    die "$GALE_DIR/BepInEx が見つかりません (mod 起動には Gale プロファイルが必要)。" \
      "'just deploy-mod' で mod を配置し、'just check-gale' で必須部品を確認してください。" \
      "素の Resonite を起動するだけなら 'just resonite-vanilla' を使ってください。"
  fi
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

# ===== mod 起動引数 =============================================================
# engine 側 = hookfxr (LinuxBootstrap.sh が "$@" 経由で BepisLoader に渡す)。
# Renderer 側 = doorstop (winhttp proxy)。--doorstop-target-assembly の CLI 指定が
# install 内 Renderer/doorstop_config.ini を上書きするので、Unix 絶対パスを渡せる
# (cd /opt/resonite で CWD ドライブが Z:→/ になり Wine が正しく解決する)。
build_mod_args() {
  MOD_ARGS=(--hookfxr-enable --bepinex-target "$GALE_DIR/BepInEx")
  local core pre f
  core="$GALE_DIR/Renderer/BepInEx/core"
  # Renderer 側 preloader を先頭マッチで 1 つ拾う (BepInEx.Preloader.dll 等)。
  # nullglob 非依存にするため [[ -f ]] で literal pattern 残りを弾く。
  pre=""
  for f in "$core"/BepInEx.*Preloader*.dll "$core"/BepInEx.*IL2CPP*.dll; do
    if [[ -f "$f" ]]; then
      pre="$f"
      break
    fi
  done
  if [[ -n "$pre" ]]; then
    MOD_ARGS+=(--doorstop-enabled true --doorstop-target-assembly "$pre")
    log "mod 起動: bepinex-target=$GALE_DIR/BepInEx doorstop=$pre"
  else
    warn "Renderer preloader 未検出 ($core)。Camera v2 (Renderer 側 plugin) は無効で起動します。"
    log "mod 起動: bepinex-target=$GALE_DIR/BepInEx doorstop=<none>"
  fi
}

# ===== エントリポイント =========================================================
main() {
  # 引数チェックは行わない: --vanilla を剥がした残りはそのまま Resonite.exe に forward。
  check_resonite_src
  check_umu_run

  MOD_ARGS=()
  if [[ "$VANILLA" -eq 1 ]]; then
    log "vanilla mode: mod を読み込まずに起動します。"
  else
    check_gale_profile
    build_mod_args
    # engine / Renderer は pressure-vessel (Steam Linux Runtime) の sandbox 内で動く。
    # pressure-vessel は既定で $HOME と game dir (/opt/resonite) しか bind しないため、
    # /workspace 配下の Gale プロファイルは sandbox から見えず BepisLoader が core DLL を
    # load できずに死ぬ。PRESSURE_VESSEL_FILESYSTEMS_RW で profile を sandbox に bind する。
    # (host の Gale 起動では ./gale が $HOME 配下なので bind 不要だった。詳細:
    #  memory/reference_pressure_vessel_paths.md)
    export PRESSURE_VESSEL_FILESYSTEMS_RW="${PRESSURE_VESSEL_FILESYSTEMS_RW:+$PRESSURE_VESSEL_FILESYSTEMS_RW:}$GALE_DIR"
    log "pressure-vessel に $GALE_DIR を bind 共有 (sandbox から mod を可視化)"
    # Renderer 側 (Wine プロセス) の doorstop は winhttp.dll プロキシ。Wine は system
    # 同梱の winhttp を優先するため、hook 版 winhttp を読ませるには WINEDLLOVERRIDES が
    # 要る。これが無いと Renderer 側 BepInEx が起動せず Camera v2 plugin が load されない
    # (--doorstop-* CLI は doorstop の挙動を設定するだけで、winhttp の読み込み自体は
    #  この override が必須)。host Steam 経由では Launch Options で渡していたもの。
    export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:+$WINEDLLOVERRIDES;}winhttp=n,b"
    log "WINEDLLOVERRIDES=$WINEDLLOVERRIDES (Renderer doorstop の winhttp プロキシ用)"
  fi

  sync_resonite

  # APP_DIR に cd することで CWD ドライブが Z: (→ /) になり、
  # ResoBoot やレンダラが渡す絶対 Unix パスが正しく解決される (entrypoint.sh と同じ理由)。
  cd "$APP_DIR"

  log "Starting Resonite via umu-run..."
  exec umu-run /opt/resonite/Resonite.exe -SkipIntroTutorial "${MOD_ARGS[@]}" "$@"
}

main "$@"
