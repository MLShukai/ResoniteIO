#!/usr/bin/env bash
# .devcontainer/initialize.sh
#
# devcontainer の initializeCommand から host 側で実行される冪等スクリプト。
# cwd は workspace root (repo ルート)。compose 方式の devcontainer では
# updateRemoteUserUID が効かないため、ここで host の準備を肩代わりする:
#   1. .env の存在を確認 (無ければ `just init` を促して fail-fast)
#   1b. compose 変数補間用に .devcontainer/.env -> ../.env symlink を張る
#   2. AppArmor による非特権 user namespace 制限の hard fail チェック
#   3. 本番 / debug 用 UDS dir を 0700 で作成
#   4. host の uid/gid / X11 / audio / GPU 情報を .env に冪等 upsert
#   5. GPU ベンダ検出 → .devcontainer/compose.gpu.yml symlink 作成

set -euo pipefail

# ---------------------------------------------------------------------------
# 1. .env 存在チェック
# ---------------------------------------------------------------------------
if [[ ! -f .env ]]; then
  echo "ERROR: .env が見つかりません。先に 'just init' を実行してください。" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 1b. compose 変数補間用の .env symlink (.devcontainer/.env -> ../.env)
# ---------------------------------------------------------------------------
# compose.yml が .devcontainer/ にあるため、compose のプロジェクトディレクトリは
# .devcontainer/ になり、${ResonitePath} / ${HOST_UID} 等の変数補間に使う .env も
# .devcontainer/ を探す (env_file: ../.env はコンテナ環境用で別経路)。repo root の
# .env を symlink で .devcontainer/ から見えるようにする。symlink は gitignore 済み。
ln -sfn ../.env .devcontainer/.env

# ---------------------------------------------------------------------------
# 2. AppArmor hard fail (ホスト側チェック)
# ---------------------------------------------------------------------------
# pressure-vessel (Steam Linux Runtime) は unprivileged user namespace を必要とする。
# ホスト (非 root) で unshare を試し、失敗したら明確な案内を出して exit 1。
# 参考実装 (resonite-docker/init.sh) は warning 止まりだが、本 repo では hard fail。
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
# 3. UDS socket 用 host ディレクトリを 0700 で先に作る
# ---------------------------------------------------------------------------
#   ~/.resonite-io/      : gRPC IPC (mod ↔ Python)
#   ~/.resonite-io-debug/: debug bridge (container ↔ host-agent)
mkdir -p "$HOME/.resonite-io" "$HOME/.resonite-io-debug"
chmod 0700 "$HOME/.resonite-io" "$HOME/.resonite-io-debug"

# ---------------------------------------------------------------------------
# ヘルパ関数群
# ---------------------------------------------------------------------------

# X ディスプレイを検出する。SSH 越しでも動作し、Wayland 上の Xwayland も考慮する。
detect_display() {
  # 1) ローカル実行: 既存 $DISPLAY を信頼する (Wayland 上では Xwayland のソケット値)。
  if [ -n "${DISPLAY:-}" ]; then
    printf '%s' "$DISPLAY"
    return
  fi
  # 2) `who` から X ディスプレイ (:N) を取得 (SSH 越しでも有効)。
  local d
  d="$(who 2>/dev/null | awk '
    $2 ~ /^:[0-9]+(\.[0-9]+)?$/      { print $2; exit }
    $NF ~ /^\(:[0-9]+(\.[0-9]+)?\)$/ { s=$NF; gsub(/[()]/,"",s); print s; exit }')"
  if [ -n "$d" ]; then
    printf '%s' "$d"
    return
  fi
  # 3) /tmp/.X11-unix の socket から推定 (Wayland は複数あり得る; 現 user 所有を優先)。
  local me s n owner
  me="$(id -u)"
  for s in /tmp/.X11-unix/X[0-9]*; do
    [ -S "$s" ] || continue
    owner="$(stat -c '%u' "$s" 2>/dev/null)" || continue
    [ "$owner" = "$me" ] || continue
    n="${s##*/X}"
    printf ':%s' "$n"
    return
  done
  # 4) 最小番号の socket にフォールバック。
  # shellcheck disable=SC2012  # /tmp/.X11-unix は X ソケット (Xn) のみで非英数字名は無く ls で十分。
  d="$(ls /tmp/.X11-unix/ 2>/dev/null | sed -n 's/^X\([0-9]\+\)$/\1/p' | sort -n | head -n1)"
  if [ -n "$d" ]; then
    printf ':%s' "$d"
    return
  fi
  # 5) 最終フォールバック。
  printf ':0'
}

# X authority ファイルの場所を検出する。
detect_xauthority_src() {
  local f
  if [ -n "${XAUTHORITY:-}" ] && [ -r "${XAUTHORITY}" ]; then
    printf '%s' "$XAUTHORITY"
    return
  fi
  for f in \
    "$HOME/.Xauthority" \
    "/run/user/$(id -u)/gdm/Xauthority" \
    /run/user/"$(id -u)"/xauth_* \
    /run/user/"$(id -u)"/.mutter-Xwaylandauth.*; do
    [ -r "$f" ] && {
      printf '%s' "$f"
      return
    }
  done
  return 0 # 未検出 = 空。set -e を誤動作させないため return 0。
}

# モニタが接続されている GPU の NVIDIA UUID を取得する。
detect_display_gpu() {
  command -v nvidia-smi >/dev/null 2>&1 || return 0
  local s card pci short uuid
  for s in /sys/class/drm/card*-*/status; do
    [ "$(cat "$s" 2>/dev/null)" = connected ] || continue
    card="$(basename "$(dirname "$s")" | sed 's/-.*//')"
    pci="$(basename "$(readlink -f "/sys/class/drm/$card/device")" 2>/dev/null)"
    short="${pci#0000:}"
    uuid="$(nvidia-smi --query-gpu=gpu_bus_id,uuid --format=csv,noheader 2>/dev/null \
      | awk -F', *' -v b="$short" 'BEGIN{b=toupper(b)} toupper($1) ~ b {print $2; exit}')"
    [ -n "$uuid" ] && {
      printf '%s' "$uuid"
      return 0
    }
  done
  return 0
}

# AMD: モニタ接続 GPU の render node / Mesa デバイス選択値を取得する。
# 出力: "<vendor>:<device> <pci-tag> <render-node>" (未検出時は空)
detect_amd_render_gpu() {
  local s con card drv vendor device pci tag rnode
  for s in /sys/class/drm/card*-*/status; do
    [ "$(cat "$s" 2>/dev/null)" = connected ] || continue
    con="$(basename "$(dirname "$s")")"
    case "$con" in *-Virtual-* | *-Writeback-*) continue ;; esac
    card="${con%%-*}"
    drv="$(basename "$(readlink -f "/sys/class/drm/$card/device/driver" 2>/dev/null)" 2>/dev/null)"
    [ "$drv" = amdgpu ] || continue
    vendor="$(cat "/sys/class/drm/$card/device/vendor" 2>/dev/null)"
    vendor="${vendor#0x}"
    device="$(cat "/sys/class/drm/$card/device/device" 2>/dev/null)"
    device="${device#0x}"
    pci="$(basename "$(readlink -f "/sys/class/drm/$card/device" 2>/dev/null)")"
    tag="pci-$(printf '%s' "$pci" | tr ':.' '_')"
    rnode="$(readlink -f "/dev/dri/by-path/pci-${pci}-render" 2>/dev/null)"
    [ -n "$vendor" ] && [ -n "$device" ] && [ -n "$rnode" ] \
      && {
        printf '%s:%s %s %s' "$vendor" "$device" "$tag" "$rnode"
        return 0
      }
  done
  return 0
}

# GPU ベンダを 1 つ特定する (nvidia | amd | intel)。
# 参考: resonite-docker/run.sh の detect_gpu ロジック。
detect_gpu_vendor() {
  # NVIDIA: nvidia-smi コマンドまたは /dev/nvidia0 デバイスで判定。
  if command -v nvidia-smi >/dev/null 2>&1 || [ -e /dev/nvidia0 ]; then
    printf 'nvidia'
    return
  fi
  # DRM vendor ID で判定。
  local vendor
  for vendor in /sys/class/drm/card[0-9]*/device/vendor; do
    [ -r "$vendor" ] || continue
    local id
    id="$(cat "$vendor" 2>/dev/null)"
    case "$id" in
      0x10de)
        printf 'nvidia'
        return
        ;;
      0x1002)
        printf 'amd'
        return
        ;;
      0x8086)
        printf 'intel'
        return
        ;;
    esac
  done
  # 検出不能の場合は nvidia をデフォルトとする。
  printf 'nvidia'
}

# ---------------------------------------------------------------------------
# 4. 各種プローブ & .env への冪等 upsert
# ---------------------------------------------------------------------------

DISPLAY_DETECTED="$(detect_display)"

# X auth cookie を FamilyWild (ffff) に書換えて .xauth に出力。
# コンテナのホスト名はランダムな ID なため、そのままでは MIT-MAGIC-COOKIE-1 の
# hostname マッチに失敗し X 接続が拒否される (ウィンドウが出ず無音で終了)。
# FamilyWild 書換えは「X11 GUI in Docker」の標準的な手法。
XAUTH_SRC="$(detect_xauthority_src)"
XAUTH_FILE="$PWD/.xauth"
rm -f "$XAUTH_FILE"
if [ -n "$XAUTH_SRC" ] && command -v xauth >/dev/null 2>&1; then
  if xauth -f "$XAUTH_SRC" nlist "$DISPLAY_DETECTED" 2>/dev/null \
    | sed -e 's/^..../ffff/' \
    | xauth -f "$XAUTH_FILE" nmerge - >/dev/null 2>&1 && [ -s "$XAUTH_FILE" ]; then
    :
  else
    rm -f "$XAUTH_FILE"
  fi
fi
# mount target として必ず存在させる (空でも可。空なら X auth は通らず warn のみ)。
[ -e "$XAUTH_FILE" ] || : >"$XAUTH_FILE"

GPU_UUID="$(detect_display_gpu)"

AMD_VK_DEVICE_SELECT=""
AMD_DRI_PRIME=""
AMD_RENDER_NODE=""
AMD_RENDER="$(detect_amd_render_gpu)"
if [ -n "$AMD_RENDER" ]; then
  # shellcheck disable=SC2086
  set -- $AMD_RENDER
  AMD_VK_DEVICE_SELECT="${1}!"
  AMD_DRI_PRIME="$2"
  AMD_RENDER_NODE="$3"
fi

# render / video グループの GID を取得する。
RENDER_GID="$(getent group render 2>/dev/null | cut -d: -f3 || true)"
VIDEO_GID="$(getent group video 2>/dev/null | cut -d: -f3 || true)"
[ -n "$RENDER_GID" ] || RENDER_GID="$(stat -c '%g' /dev/dri/renderD128 2>/dev/null || echo 110)"
[ -n "$VIDEO_GID" ] || VIDEO_GID="$(stat -c '%g' /dev/dri/card0 2>/dev/null || echo 44)"

# host の uid/gid を .env に冪等 upsert (既存行は削除して追記し直す)。
sed -i \
  '/^HOST_UID=/d; /^HOST_GID=/d; /^DISPLAY=/d; /^XAUTHORITY_HOST=/d; /^RENDER_GID=/d; /^VIDEO_GID=/d; /^NVIDIA_GPU_UUID=/d; /^AMD_RENDER_NODE=/d; /^AMD_VK_DEVICE_SELECT=/d; /^AMD_DRI_PRIME=/d' \
  .env
{
  echo "HOST_UID=$(id -u)"
  echo "HOST_GID=$(id -g)"
  echo "DISPLAY=${DISPLAY_DETECTED}"
  echo "XAUTHORITY_HOST=${XAUTH_FILE}"
  echo "RENDER_GID=${RENDER_GID}"
  echo "VIDEO_GID=${VIDEO_GID}"
  echo "NVIDIA_GPU_UUID=${GPU_UUID}"
  echo "AMD_RENDER_NODE=${AMD_RENDER_NODE}"
  echo "AMD_VK_DEVICE_SELECT=${AMD_VK_DEVICE_SELECT}"
  echo "AMD_DRI_PRIME=${AMD_DRI_PRIME}"
} >>.env

# ---------------------------------------------------------------------------
# 警告チェック (hard fail にしない)
# ---------------------------------------------------------------------------

if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
  echo "info: Wayland セッション検出。X11 アプリ (Wine レンダラ) は Xwayland 経由で描画します (DISPLAY=${DISPLAY_DETECTED})。"
fi

if [ ! -s "$XAUTH_FILE" ]; then
  echo "warning: X auth cookie を準備できませんでした (.xauth が空: ${XAUTH_FILE})。" >&2
  echo "  X ディスプレイ (${DISPLAY_DETECTED}) に接続できず、無音で終了する可能性があります。" >&2
  echo "  グラフィカルセッション内で実行し、Xorg または Xwayland が動いているか確認してください。" >&2
fi

# Resonite.exe 存在確認 (ResonitePath は .env から読む)。
RESONITE_PATH_VAL="$(grep '^ResonitePath=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
if [ -n "${RESONITE_PATH_VAL:-}" ] && [ ! -e "${RESONITE_PATH_VAL}/Resonite.exe" ]; then
  echo "warning: ${RESONITE_PATH_VAL}/Resonite.exe が見つかりません。" >&2
  echo "  .env の ResonitePath を確認してください。" >&2
fi

# PulseAudio/PipeWire ソケット確認。
PULSE_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/pulse/native"
if [ ! -S "$PULSE_SOCK" ]; then
  echo "warning: PulseAudio/PipeWire socket が見つかりません: ${PULSE_SOCK}" >&2
  echo "  音声なし / 初回オンボーディングで固まる可能性があります。" >&2
  echo "  ホストで PipeWire (または PulseAudio) が動いているか確認してください。" >&2
fi

# ---------------------------------------------------------------------------
# 5. GPU ベンダ検出 → .devcontainer/compose.gpu.yml symlink 作成
# ---------------------------------------------------------------------------
GPU_VENDOR="$(detect_gpu_vendor)"
echo "info: GPU ベンダ検出: ${GPU_VENDOR}"
ln -sfn "compose.${GPU_VENDOR}.yml" .devcontainer/compose.gpu.yml
echo "info: .devcontainer/compose.gpu.yml -> compose.${GPU_VENDOR}.yml"
