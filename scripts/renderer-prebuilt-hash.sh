#!/usr/bin/env bash
# scripts/renderer-prebuilt-hash.sh
#
# Camera v2 Renderer plugin の committed prebuilt 成果物 (mod/prebuilt/renderer/)
# が Renderer ソースと同期しているかを検証するための **source hash** を計算する。
#
# 設計方針 (決定論):
#   - 入力集合は Renderer の build 入力のうち「ソース」のみ:
#       * mod/src/ResoniteIO.Renderer/        配下の全 .cs (再帰、bin/obj 除外)
#       * mod/src/ResoniteIO.RendererShared/  配下の全 .cs (再帰、bin/obj 除外)
#       * mod/src/ResoniteIO.Renderer/ResoniteIO.Renderer.csproj
#       * mod/src/ResoniteIO.RendererShared/ResoniteIO.RendererShared.csproj
#     HintPath が指す Unity/Renderite DLL は CI に存在せず「ソース」でもないため
#     hash に含めない (version skew は thunderstore.toml の dependency lockstep が担保)。
#   - パスは repo-root 相対に正規化し、LC_ALL=C sort で昇順ソートする
#     (絶対パス差・ロケール差を消す)。
#   - ソート順の各ファイルに per-file sha256sum を取り、その標準出力行
#     ("<sha256>  <repo-relative-path>") をソート順のまま連結し、再度 sha256 にかける。
#   - 最終 hash (64 hex) のみを **stdout** に 1 行 (改行付き) で出力する。
#     人間向けログ (log/warn) は **stderr** に出して stdout を hash 専用に保つ。
#
# 責務境界 (本スクリプトは hash 計算のみ):
#   - mod/prebuilt/renderer.sha256 への **書き込み** は `just renderer-prebuild` が行う。
#   - committed hash との **照合** は `just check-renderer-prebuilt` (および CI) が行う。
#   これにより同一 hash ロジックを単一スクリプトに集約し、refresh と check が
#   byte 単位で一致することを保証する。
#
# Usage:
#   bash scripts/renderer-prebuilt-hash.sh      # -> 64-hex digest on stdout

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="renderer-prebuilt-hash"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

REPO_ROOT="$(repo_root)"
RENDERER_DIR="mod/src/ResoniteIO.Renderer"
SHARED_DIR="mod/src/ResoniteIO.RendererShared"

main() {
  have sha256sum || die "sha256sum is required but not installed (coreutils)."
  have find || die "find is required but not installed."
  have sort || die "sort is required but not installed."

  # hash は repo-root 相対パスで再現性を確保するため、repo root を CWD にする。
  cd "$REPO_ROOT"

  for dir in "$RENDERER_DIR" "$SHARED_DIR"; do
    [[ -d "$dir" ]] || die "Renderer source directory not found: $dir"
  done

  warn "Computing Renderer source hash (inputs under $RENDERER_DIR + $SHARED_DIR)"

  # 入力ファイル収集 (repo-root 相対パス)。bin/obj を prune して生成物を除外する。
  # .cs は再帰収集、.csproj は当該 2 プロジェクトファイルのみ対象。
  local -a input_files=()
  while IFS= read -r -d '' f; do
    input_files+=("${f#./}")
  done < <(
    find "$RENDERER_DIR" "$SHARED_DIR" \
      \( -type d \( -name bin -o -name obj \) -prune \) -o \
      -type f \( -name '*.cs' -o -name '*.csproj' \) -print0
  )

  [[ ${#input_files[@]} -gt 0 ]] || die "No Renderer source files found; cannot compute hash."

  # repo-root 相対パス文字列で昇順ソート (LC_ALL=C でロケール非依存)。
  local -a sorted_files=()
  while IFS= read -r -d '' f; do
    sorted_files+=("$f")
  done < <(printf '%s\0' "${input_files[@]}" | LC_ALL=C sort -z)

  warn "Hashing ${#sorted_files[@]} source file(s)"

  # 各ファイルの sha256sum 行 ("<sha256>  <path>") をソート順のまま連結し、
  # その byte 列を再度 sha256 にかけて 64-hex を得る。
  local digest
  digest="$(
    for f in "${sorted_files[@]}"; do
      sha256sum -- "$f"
    done | sha256sum | cut -d' ' -f1
  )"

  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "Computed hash is not a 64-hex digest: $digest"

  printf '%s\n' "$digest"
}

main "$@"
