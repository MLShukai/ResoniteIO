#!/usr/bin/env bash
# scripts/bump-version.sh
#
# リリース準備の version bump を 1 コマンドで行う (RELEASE.md §2 / §4-1)。
# 正規バージョンソースは csproj <Version> で、python/pyproject.toml と
# python/uv.lock を lockstep で同じ値に揃える。
#
# 更新対象 (3 箇所):
#   1. mod/src/ResoniteIO/ResoniteIO.csproj の <Version>   ← 正規ソース
#   2. python/pyproject.toml の [project] version
#   3. python/uv.lock (uv lock の再実行で追従)
#
# CHANGELOG.md の確定 (Unreleased → [X.Y.Z] + link reference definitions) は
# リリース内容の判断を伴うため対象外。実行後にリマインダーを表示する。
#
# version 形式は publish.yml の version guard / prerelease 判定と揃える:
#   X.Y.Z または X.Y.Z-(a|b|rc)N (例: 0.4.0 / 0.4.0-rc1)
#
# Usage:
#   bash scripts/bump-version.sh <version>   # just bump-version <version> から呼ぶ

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="bump-version"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

REPO_ROOT="$(repo_root)"
CSPROJ="mod/src/ResoniteIO/ResoniteIO.csproj"
PYPROJECT="python/pyproject.toml"

main() {
  [[ $# -eq 1 ]] || die "Usage: bash scripts/bump-version.sh <X.Y.Z | X.Y.Z-(a|b|rc)N>"
  local version="$1"
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(a|b|rc)[0-9]+)?$ ]] \
    || die "Invalid version '$version' (expected X.Y.Z or X.Y.Z-(a|b|rc)N, e.g. 0.4.0 / 0.4.0-rc1)"
  have uv || die "uv is required but not installed (run inside the dev container)."

  cd "$REPO_ROOT"

  # --- csproj <Version> (正規ソース) ---
  # 置換対象が一意であることを保証する (csproj には PackageReference の
  # Version 属性が多数あるため、<Version> element のみを対象にする)。
  local count
  count="$(grep -c '<Version>.*</Version>' "$CSPROJ" || true)"
  [[ "$count" == "1" ]] || die "Expected exactly 1 <Version> element in $CSPROJ (found $count)."
  local current
  current="$(sed -n 's|.*<Version>\(.*\)</Version>.*|\1|p' "$CSPROJ")"
  if [[ "$current" == "$version" ]]; then
    warn "Version is already $version; nothing to do."
    exit 0
  fi
  log "Bumping version: $current -> $version"
  sed -i "s|<Version>$current</Version>|<Version>$version</Version>|" "$CSPROJ"

  # --- pyproject.toml [project] version (lockstep) ---
  count="$(grep -c '^version = "' "$PYPROJECT" || true)"
  [[ "$count" == "1" ]] || die "Expected exactly 1 top-level version line in $PYPROJECT (found $count)."
  sed -i "s|^version = \".*\"$|version = \"$version\"|" "$PYPROJECT"

  # --- uv.lock 追従 ---
  (cd python && uv lock)

  log "Updated to $version:"
  grep -n '<Version>' "$CSPROJ"
  grep -n '^version = ' "$PYPROJECT"
  warn "CHANGELOG.md は手動で確定すること: '## [Unreleased]' を '## [$version] - $(date +%F)' に移し、"
  warn "末尾の link reference definitions ([$version]: ... と [unreleased]: ...) も追加する (RELEASE.md §4-1)。"
}

main "$@"
