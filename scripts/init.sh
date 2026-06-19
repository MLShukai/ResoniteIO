#!/usr/bin/env bash
# scripts/init.sh
#
# 初回 host setup を 1 コマンドで行う冪等スクリプト (`just init` から呼ぶ)。
# host 上で実行する想定 (container は不要)。
#
# 手順:
#   1. docker / docker compose v2 の存在確認
#   2. .env が無ければ .env.example をコピーし $EDITOR (既定 vi) で開かせる。
#      その場合は exit 0 で抜け、ユーザーに `just init` 再実行を促す
#      (`set dotenv-load` の解釈はパース時のため、同一実行内で再 source できない)
#   3. ResonitePath が指すディレクトリの実在を検証
#   4. ./gale/ を空ディレクトリとして用意 (Gale は profile path に空 dir を要求するが
#      存在自体は許容する。先回りで作っておくと Gale GUI でパス指定が楽になる)
#   5. ./gale/BepisLoader.dll を見て Gale プロファイル設置を判定:
#      - 既設なら `just check-gale` を呼び全部品を厳密チェック
#      - 未設なら手順を stderr に出して非 0 exit (GaleProfile.r2z の import を推奨)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="init"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

REPO_ROOT="$(repo_root)"

# Gale プロファイルが未設置のときに出す手順 (stderr)。
# GaleProfile.r2z は repo 同梱の profile snapshot で、必須 mod を版指定込みで
# 一括投入できる (個別 install のフォールバックも併記する)。
print_gale_setup_steps() {
  cat >&2 <<'EOF'

ERROR: ./gale に Gale profile が未設置です (ディレクトリは空のまま用意済み)。

  以下を host 上で実施してください:
    1. Gale v1.5.4+ をインストール (https://github.com/Kesomannen/gale)
    2. Gale GUI で 'Create profile' を選び、パスに <repo>/gale を指定
       (このディレクトリは空である必要があり、just init が用意した状態が
        まさにそれにあたる)
    3. profile に必須 mod 一式を入れる。以下のどちらかを選ぶ:
         [推奨] 作成した profile を選択した状態で
                'Import > ... profile from file' から <repo>/GaleProfile.r2z を
                選び、overwrite する (必須 mod が版指定込みで一括投入される)
         [手動] 以下 6 つの mod を個別に install:
                  - ResoniteModding-BepisLoader (>=1.5.1)
                  - ResoniteModding-BepInExResoniteShim (>=0.9.3)
                  - ResoniteModding-BepisResoniteWrapper (>=1.0.2)
                  - ResoniteModding-BepInExRenderer (>=5.4)   — Camera v2 用 Renderer 側 BepInEx 5
                  - ResoniteModding-RenderiteHook (>=1.1.1)   — Renderer プロセスへの doorstop inject
                  - Nytra-InterprocessLib (>=3.0.0)           — engine ↔ Renderer 共有メモリ queue
    4. Steam で Resonite の Launch Options に以下を設定:
         WINEDLLOVERRIDES="winhttp=n,b" %command%
       (これが無いと Renderer 側 BepInEx が永遠に起動しない)
    5. 完了後 'just init' を再実行
EOF
}

main() {
  cd "$REPO_ROOT"

  log "Checking host tooling ..."
  have docker || die "docker が見つかりません。"
  docker compose version >/dev/null 2>&1 || die "docker compose v2 が必要です。"

  if [[ ! -f .env ]]; then
    cp .env.example .env
    log ".env を .env.example から作成しました。"
    if [[ -t 0 && -t 1 ]]; then
      log "'${EDITOR:-vi}' で開きます。保存後、もう一度 'just init' を実行してください。"
      "${EDITOR:-vi}" .env || true
    else
      warn "非対話 shell のため editor は起動しません。.env を編集してから 'just init' を再実行してください。"
    fi
    # dotenv-load はパース時解釈のため、同一実行内では .env を再 source できない。
    # ここで一旦抜け、ユーザーに再実行してもらう。
    exit 0
  fi
  log ".env exists."

  : "${ResonitePath:?ResonitePath が .env に設定されていません。.env を編集してから 'just init' を再実行してください。}"
  [[ -d "$ResonitePath" ]] || die "ResonitePath=$ResonitePath はディレクトリではありません。"
  log "ResonitePath OK: $ResonitePath"

  mkdir -p gale
  if [[ ! -f gale/BepisLoader.dll ]]; then
    print_gale_setup_steps
    exit 1
  fi

  just check-gale

  log "All preconditions satisfied. Next, open the dev container:"
  cat <<'EOF'
    VS Code: コマンドパレットから 'Dev Containers: Reopen in Container'
    Zed:     dev container として開く
    CLI:     devcontainer up --workspace-folder .   # 任意
EOF
}

main "$@"
