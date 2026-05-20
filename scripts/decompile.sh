#!/usr/bin/env bash
# scripts/decompile.sh
#
# Resonite の主要 first-party DLL/EXE を ILSpy (`ilspycmd`) で decompile し、
# プロジェクトルートの `decompiled/` に **project 形式** で書き出す。
#
# 設計方針:
#   - decompile 対象は明示リスト管理 (グロブだと third-party `Resonite*` mod が
#     誤って混入する可能性があるため)。リストは EDIT THIS で囲んだ箇所を編集する。
#   - 既存の `decompiled/` は毎回 wipe してから生成 (冪等)。
#   - `ilspycmd` は `.config/dotnet-tools.json` の local tool として固定済み。
#     manifest 経由で `dotnet ilspycmd ...` として呼ぶ (PATH 操作不要)。
#   - 単独 DLL の失敗で全体を abort せず warn で続行し、最後にサマリを出して
#     失敗があれば非 0 終了する。
#   - mscorlib / System.* 解決のため、Resonite 同梱の .NET runtime
#     (`$RESONITE_DIR/dotnet-runtime/shared/Microsoft.NETCore.App/<ver>/`) も
#     reference path に追加する。
#
# Usage:
#   scripts/decompile.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="decompile"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

REPO_ROOT="$(repo_root)"
OUT_DIR="$REPO_ROOT/decompiled"
RESONITE_DIR="${ResonitePath:-$HOME/.steam/steam/steamapps/common/Resonite}"

# ===== EDIT THIS: decompile 対象 ============================================
# Resonite 関連 first-party assembly のみ。配布物の中身が変わったら追記する。
# パスは $RESONITE_DIR からの相対パス (フラット名 = 直下、サブディレクトリの場合は前置)。
ASSEMBLIES=(
  # Core engine (FrooxEngine プロセス側、Resonite.exe にロード)
  FrooxEngine.dll
  FrooxEngine.Commands.dll
  FrooxEngine.Store.dll
  FrooxEngine.Weaver.dll
  # Elements stack
  Elements.Core.dll
  Elements.Assets.dll
  Elements.Data.dll
  Elements.Quantity.dll
  # ProtoFlux
  ProtoFlux.Core.dll
  ProtoFlux.Nodes.Core.dll
  ProtoFlux.Nodes.FrooxEngine.dll
  ProtoFluxBindings.dll
  # Renderite host (Resonite.exe 側、shared memory IPC で renderer と話す)
  Renderite.Shared.dll
  Renderite.Host.dll
  # Renderite renderer (Renderite.Renderer.exe = Unity プロセス側の実装本体)
  # Camera / HeadOutput など「ユーザー画面の実描画」はこちらにある。
  # NOTE: Resonite 2026.5.20.222 update で Renderite.Unity.dll は消滅した
  # (engine と Renderer の DLL 構成が再編、Unity 側 binding は別 DLL に
  # 統合 / 削除された)。Assembly-CSharp が依然として Renderer 側
  # game logic の本体なので decompile 対象として残す。
  Renderer/Renderite.Renderer_Data/Managed/Assembly-CSharp.dll
  Renderer/Renderite.Renderer_Data/Managed/NativeGraphics.NET.dll
  # SkyFrost (cloud / data model)
  SkyFrost.Base.dll
  SkyFrost.Base.Models.dll
  # First-party misc
  PhotonDust.dll
  ResoniteLink.dll
  resonite-clipboard-cs.dll
  # NOTE: Resonite.exe / Renderite.Host.exe / Renderite.Renderer.exe は
  # **native PE 実行ファイル** (managed metadata を持たない bootstrapper) なので
  # ilspycmd では decompile できない。
  # NOTE: Mnemosyne.dll は ilspycmd 10.0.1.x 系の TargetFramework 検出バグに
  # 当たって失敗する (netstandard 1.x 由来? どのモードでも同じ箇所で例外)。
  # ilspycmd を上げて解消したら再度足す。
)
# ===== END EDIT THIS ========================================================

main() {
  have dotnet || die "dotnet が見つかりません。Docker 開発環境 (just container-up) を使うか、ホストに .NET SDK を入れてください。"

  if [[ ! -d "$RESONITE_DIR" ]]; then
    die "Resonite ディレクトリが見つかりません: $RESONITE_DIR
       .env の ResonitePath= に Resonite の実行ファイルディレクトリを設定してください。"
  fi
  if [[ ! -f "$RESONITE_DIR/FrooxEngine.dll" ]]; then
    die "FrooxEngine.dll が見つかりません: $RESONITE_DIR/FrooxEngine.dll
       ResonitePath が Resonite の実行ファイルディレクトリを指しているか確認してください。"
  fi
  log "Resonite directory: $RESONITE_DIR"

  # bundled .NET runtime の reference path 解決 (mscorlib / System.* 用)。
  # Renderite renderer 側 (Unity プロセス) の DLL 解決のため
  # Renderite.Renderer_Data/Managed も reference に含める。
  local -a ref_args=(-r "$RESONITE_DIR")
  local renderer_managed="$RESONITE_DIR/Renderer/Renderite.Renderer_Data/Managed"
  if [[ -d "$renderer_managed" ]]; then
    ref_args+=(-r "$renderer_managed")
    log "Reference path: $renderer_managed"
  fi
  local runtime_root="$RESONITE_DIR/dotnet-runtime/shared/Microsoft.NETCore.App"
  if [[ -d "$runtime_root" ]]; then
    while IFS= read -r -d '' d; do
      ref_args+=(-r "$d")
      log "Reference path: $d"
    done < <(find "$runtime_root" -mindepth 1 -maxdepth 1 -type d -print0)
  else
    warn "Bundled .NET runtime not found under $runtime_root"
    warn "  → mscorlib / System.* の解決ができず警告が増える可能性があります。"
  fi

  # 出力ディレクトリの初期化 (毎回 wipe して再生成)。
  if [[ -e "$OUT_DIR" ]]; then
    log "Removing existing $OUT_DIR"
    rm -rf "$OUT_DIR"
  fi
  mkdir -p "$OUT_DIR"

  # local tool restore (CI / 新規 clone でも安全)。
  log "Restoring .NET local tools..."
  (cd "$REPO_ROOT" && dotnet tool restore >/dev/null)

  log "Decompiling ${#ASSEMBLIES[@]} assemblies into $OUT_DIR (数分かかります)..."

  local -a succeeded=() failed=() skipped=()

  # `set -e` を一時的に外して各 DLL の失敗を許容する。
  set +e
  local asm src filename base out_subdir
  for asm in "${ASSEMBLIES[@]}"; do
    src="$RESONITE_DIR/$asm"
    if [[ ! -f "$src" ]]; then
      warn "Skip (file not found): $asm"
      skipped+=("$asm")
      continue
    fi
    # サブディレクトリ付きパスでも出力先は basename ベースの flat 名にする
    # (例: Renderer/.../Renderite.Unity.dll → decompiled/Renderite.Unity/)
    filename="$(basename "$asm")"
    base="${filename%.*}"
    out_subdir="$OUT_DIR/$base"
    mkdir -p "$out_subdir"
    log "→ $asm  (out: decompiled/$base/)"
    if dotnet ilspycmd "$src" \
      --project \
      --outputdir "$out_subdir" \
      --disable-updatecheck \
      "${ref_args[@]}" \
      >"$out_subdir/.ilspycmd.log" 2>&1; then
      succeeded+=("$asm")
    else
      warn "Failed: $asm  (詳細は $out_subdir/.ilspycmd.log)"
      failed+=("$asm")
    fi
  done
  set -e

  # サマリ。
  log "Done."
  log "  succeeded: ${#succeeded[@]}"
  if [[ ${#skipped[@]} -gt 0 ]]; then
    log "  skipped:   ${#skipped[@]} (${skipped[*]})"
  else
    log "  skipped:   0"
  fi
  if [[ ${#failed[@]} -gt 0 ]]; then
    log "  failed:    ${#failed[@]} (${failed[*]})"
    die "${#failed[@]} 件の assembly で decompile が失敗しました。"
  fi
  log "  failed:    0"
}

main "$@"
