set dotenv-load := true
set shell := ["bash", "-c"]

# 既定で help を出す。
default:
    @just --list

# ===== 環境構築 =========================================================

# 初回 setup: host tooling 検証 / .env セットアップ / Gale プロファイル確認を
# 1 コマンドで行う。host 上で実行する想定 (container は要らない)。冪等。
#
#   1. docker / docker compose v2 の存在確認
#   2. .env が無ければ .env.example をコピーし $EDITOR (既定 vi) で開かせる。
#      その場合は exit 0 で抜け、ユーザーに `just init` 再実行を促す
#      (set dotenv-load の解釈はパース時のため、同一実行内で再 source できないため)
#   3. ResonitePath が指すディレクトリの実在を検証
#   4. ./gale/ を空ディレクトリとして用意 (Gale は profile path に空 dir を要求するが
#      存在自体は許容する。先回りで作っておくと Gale GUI でパス指定が楽になる)
#   5. ./gale/BepisLoader.dll を見て Gale プロファイル設置を判定:
#      - 既設なら `check-gale` を呼び全部品を厳密チェック
#      - 未設なら手順を stderr に出して非 0 exit
init:
    @echo "[init] Checking host tooling ..."
    @command -v docker >/dev/null 2>&1 || { echo "ERROR: docker が見つかりません。" >&2; exit 1; }
    @docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose v2 が必要です。" >&2; exit 1; }
    @if [ ! -f .env ]; then \
        cp .env.example .env; \
        echo "[init] .env を .env.example から作成しました。"; \
        if [ -t 0 ] && [ -t 1 ]; then \
            echo "[init] '${EDITOR:-vi}' で開きます。保存後、もう一度 'just init' を実行してください。"; \
            "${EDITOR:-vi}" .env; \
        else \
            echo "[init] 非対話 shell のため editor は起動しません。.env を編集してから 'just init' を再実行してください。" >&2; \
        fi; \
        exit 0; \
    fi
    @echo "[init] .env exists."
    @: "${ResonitePath:?ResonitePath が .env に設定されていません。.env を編集してから 'just init' を再実行してください。}"
    @[ -d "$ResonitePath" ] || { echo "ERROR: ResonitePath=$ResonitePath はディレクトリではありません。" >&2; exit 1; }
    @echo "[init] ResonitePath OK: $ResonitePath"
    @mkdir -p gale
    @if [ ! -f gale/BepisLoader.dll ]; then \
        echo "" >&2; \
        echo "ERROR: ./gale に Gale profile が未設置です (ディレクトリは空のまま用意済み)。" >&2; \
        echo "" >&2; \
        echo "  以下を host 上で実施してください:" >&2; \
        echo "    1. Gale v1.5.4+ をインストール (https://github.com/Kesomannen/gale)" >&2; \
        echo "    2. Gale GUI で 'Create profile' を選び、パスに <repo>/gale を指定" >&2; \
        echo "       (このディレクトリは空である必要があり、just init が用意した状態が" >&2; \
        echo "        まさにそれにあたる)" >&2; \
        echo "    3. プロファイルに以下 6 つの mod を install:" >&2; \
        echo "         - ResoniteModding-BepisLoader (>=1.5.1)" >&2; \
        echo "         - ResoniteModding-BepInExResoniteShim (>=0.9.3)" >&2; \
        echo "         - ResoniteModding-BepisResoniteWrapper (>=1.0.2)" >&2; \
        echo "         - ResoniteModding-BepInExRenderer (>=5.4)   — Camera v2 用 Renderer 側 BepInEx 5" >&2; \
        echo "         - ResoniteModding-RenderiteHook (>=1.1.1)   — Renderer プロセスへの doorstop inject" >&2; \
        echo "         - Nytra-InterprocessLib (>=3.0.0)           — engine ↔ Renderer 共有メモリ queue" >&2; \
        echo "    4. Steam で Resonite の Launch Options に以下を設定:" >&2; \
        echo "         WINEDLLOVERRIDES=\"winhttp=n,b\" %command%" >&2; \
        echo "       (これが無いと Renderer 側 BepInEx が永遠に起動しない)" >&2; \
        echo "    5. 完了後 'just init' を再実行" >&2; \
        exit 1; \
    fi
    @just check-gale
    @echo ""
    @echo "[init] All preconditions satisfied. Next, open the dev container:"
    @echo "    VS Code: コマンドパレットから 'Dev Containers: Reopen in Container'"
    @echo "    Zed:     dev container として開く"
    @echo "    CLI:     devcontainer up --workspace-folder .   # 任意"

# proto から Python 側の生成コードを再生成する。C# 側は dotnet build で自動生成。
gen-proto:
    bash scripts/gen_proto.sh

# ルートの full-size icon.png (master) から mod/icon.png (256x256) を再生成する。
# Thunderstore は 256x256 必須、docs/assets/icon.png は mod/icon.png への symlink。
# pre-commit の resize-icon hook が icon.png 変更時に自動で同じ script を走らせる。
# Pillow は pre-commit と版を揃えるため pin する (描画の決定性を保つ)。
icon:
    uv run --no-project --with 'pillow==12.2.0' python scripts/resize_icon.py

# Resonite の主要 first-party DLL を ILSpy で decompile し、
# プロジェクトルートの decompiled/ に project 形式で書き出す。
# 既存の decompiled/ は wipe される (idempotent)。要 .env の ResonitePath。
decompile:
    bash scripts/decompile.sh

# ===== Python (python/) =================================================

py-format:
    cd python && uv run ruff format . && uv run ruff check --fix .

py-test:
    cd python && uv run pytest -v --cov

py-type:
    cd python && uv run pyright

# e2e テストを実行する (実機 Resonite + host-agent が前提)。
# - 引数なし (name="all"): tests/e2e/ ディレクトリ配下を全て走らせる
# - 引数あり (例: `just e2e-test connection`): tests/e2e/<name>.py のみ走らせる
# tests/e2e/ 配下のファイルは `test_` prefix を持たず `<scenario>.py` 命名としている。
# pytest の python_files パターンを `*.py` に override することで collect 対象に含める。
e2e-test name="all":
    @if [ "{{ name }}" = "all" ]; then \
        cd python && uv run pytest tests/e2e/ -m e2e -v --override-ini='python_files=*.py'; \
    else \
        cd python && uv run pytest tests/e2e/{{ name }}.py -m e2e -v --override-ini='python_files=*.py'; \
    fi

# ===== C# (mod/) ========================================================

mod-format:
    cd mod && dotnet csharpier format .

mod-build:
    cd mod && dotnet build -c Release

mod-test:
    cd mod && dotnet test

# Thunderstore 配布用 zip を build/ に生成 (mod/Directory.Build.targets の PackTS)。
# 公開時は `just mod-pack PublishTS=true` で `dotnet tcli publish` に切替わる。
mod-pack:
    cd mod && dotnet build ResoniteIO.sln -c Release -t:PackTS -v d

# ローカル開発成果物と Gale プロファイルに配置された plugin を撤去する。
# Engine 側 (`gale/BepInEx/plugins/ResoniteIO`) と Renderer 側
# (`gale/Renderer/BepInEx/plugins/ResoniteIO.Renderer`、Camera v2 用) の
# 両 deploy 先を片付ける。
mod-clean:
    find mod -type d -name 'bin' -prune -exec rm -rf {} +
    find mod -type d -name 'obj' -prune -exec rm -rf {} +
    rm -rf mod/build
    @GALE_ROOT="${GalePath:-./gale}"; \
    for PLUGIN_DIR in \
        "$GALE_ROOT/BepInEx/plugins/ResoniteIO" \
        "$GALE_ROOT/Renderer/BepInEx/plugins/ResoniteIO.Renderer"; do \
        if [ -d "$PLUGIN_DIR" ]; then \
            rm -rf "$PLUGIN_DIR" && \
            echo "Removed $PLUGIN_DIR"; \
        fi; \
    done

# ===== 横断 ==============================================================

format: py-format mod-format

test: py-test mod-test

type: py-type

build: mod-build

# `just mod-build` で csproj の PostBuild Target が
# $(GalePath)/BepInEx/plugins/ResoniteIO/ に DLL+PDB を Copy する。
# 名前で意図を表すために専用レシピを残す。
# 配置先は GalePath (container) / repo root の ./gale/ (host) を優先順で解決。
# gale/ が無効なら build は成功するが Copy がスキップされるためエラー扱い。
deploy-mod: mod-build
    @GALE_ROOT="${GalePath:-./gale}"; \
    DLL="$GALE_ROOT/BepInEx/plugins/ResoniteIO/ResoniteIO.dll"; \
    if [ -f "$DLL" ]; then \
        echo "Deployed to $GALE_ROOT/BepInEx/plugins/ResoniteIO/"; \
    else \
        echo "ERROR: 配置先に DLL が見当たりません ($DLL)。" >&2; \
        echo "       Gale (https://github.com/Kesomannen/gale) v1.5.4+ で" >&2; \
        echo "       '<repo>/gale' に profile を作り、BepisLoader を追加してください。" >&2; \
        exit 1; \
    fi

# Gale プロファイル (./gale/) に BepisLoader と必須プラグインが揃っているか検証する。
# ホスト上で実行する想定 (container でも GalePath があれば動く)。
# 検査対象 (実プロファイルの配置に追従):
#   engine 側 (Linux .NET 10, BepInEx 6):
#     - $GALE_ROOT/BepisLoader.dll              (Gale が profile root に置く)
#     - $GALE_ROOT/BepInEx/core/BepInEx.Core.dll
#     - $GALE_ROOT/BepInEx/core/BepInEx.NET.Common.dll
#     - $GALE_ROOT/BepInEx/core/0Harmony.dll
#     - $GALE_ROOT/BepInEx/plugins/ResoniteModding-BepInExResoniteShim*/**/BepInExResoniteShim.dll
#     - $GALE_ROOT/BepInEx/plugins/ResoniteModding-BepisResoniteWrapper*/**/BepisResoniteWrapper.dll
#   Camera v2 用 (engine 側 plugins):
#     - $GALE_ROOT/BepInEx/plugins/ResoniteModding-RenderiteHook*/RenderiteHook/RenderiteHook.dll
#     - $GALE_ROOT/BepInEx/plugins/Nytra-InterprocessLib/InterprocessLib.BepisLoader/InterprocessLib.FrooxEngine.dll
#   Renderer 側 (Wine + Unity Mono, BepInEx 5; 詳細 plugin 検証は Wave 4/5):
#     - $GALE_ROOT/Renderer/BepInEx/core/BepInEx.Preloader.dll
#       (ResoniteModding-BepInExRenderer package が deploy する Renderer 側 core。
#        この package 自体は profile 内に独立 plugin dir を作らず、
#        Renderer/BepInEx/core/ 配下に framework を展開する)
# 不足あれば非 0 exit。version 表示は best-effort。
check-gale:
    @GALE_ROOT="${GalePath:-./gale}"; \
    echo "[check-gale] Checking Gale profile at $GALE_ROOT ..."; \
    fail=0; \
    check_file() { \
        local label="$1" path="$2"; \
        if [ -f "$path" ]; then \
            printf "  %-44s ✓\n" "$label"; \
        else \
            printf "  %-44s ✗  (expected at %s)\n" "$label" "$path" >&2; \
            fail=1; \
        fi; \
    }; \
    check_glob() { \
        local label="$1" pattern="$2"; \
        local match; \
        match=$(find $pattern 2>/dev/null | head -n 1); \
        if [ -n "$match" ]; then \
            printf "  %-44s ✓  (%s)\n" "$label" "$match"; \
        else \
            printf "  %-44s ✗  (no match for %s)\n" "$label" "$pattern" >&2; \
            fail=1; \
        fi; \
    }; \
    check_file "BepisLoader.dll"              "$GALE_ROOT/BepisLoader.dll"; \
    check_file "BepInEx.Core.dll"             "$GALE_ROOT/BepInEx/core/BepInEx.Core.dll"; \
    check_file "BepInEx.NET.Common.dll"       "$GALE_ROOT/BepInEx/core/BepInEx.NET.Common.dll"; \
    check_file "0Harmony.dll"                 "$GALE_ROOT/BepInEx/core/0Harmony.dll"; \
    check_glob "BepInExResoniteShim.dll"      "$GALE_ROOT/BepInEx/plugins/ResoniteModding-BepInExResoniteShim*/BepInExResoniteShim/BepInExResoniteShim.dll"; \
    check_glob "BepisResoniteWrapper.dll"     "$GALE_ROOT/BepInEx/plugins/ResoniteModding-BepisResoniteWrapper*/BepisResoniteWrapper/BepisResoniteWrapper.dll"; \
    check_glob "RenderiteHook.dll"            "$GALE_ROOT/BepInEx/plugins/ResoniteModding-RenderiteHook*/RenderiteHook/RenderiteHook.dll"; \
    check_file "InterprocessLib.FrooxEngine.dll" "$GALE_ROOT/BepInEx/plugins/Nytra-InterprocessLib/InterprocessLib.BepisLoader/InterprocessLib.FrooxEngine.dll"; \
    check_file "Renderer/BepInEx.Preloader.dll" "$GALE_ROOT/Renderer/BepInEx/core/BepInEx.Preloader.dll"; \
    if [ "$fail" -ne 0 ]; then \
        echo "[check-gale] ERROR: 必要な Gale 部品が見つかりません。" >&2; \
        echo "  Gale (https://github.com/Kesomannen/gale) で profile を更新し、" >&2; \
        echo "  以下を install してください:"                    >&2; \
        echo "    - ResoniteModding-BepisLoader"                 >&2; \
        echo "    - ResoniteModding-BepInExResoniteShim"         >&2; \
        echo "    - ResoniteModding-BepisResoniteWrapper"        >&2; \
        echo "    - ResoniteModding-BepInExRenderer  (Camera v2)" >&2; \
        echo "    - ResoniteModding-RenderiteHook    (Camera v2)" >&2; \
        echo "    - Nytra-InterprocessLib            (Camera v2)" >&2; \
        echo "  Renderer 側 core が無い場合は、Gale から Resonite を 1 度起動し" >&2; \
        echo "  RenderiteHook が doorstop files を deploy するのを待ってください。" >&2; \
        exit 1; \
    fi; \
    echo "[check-gale] All required Gale components present."

# Resonite (host 側プロセス) の BepInEx ログを追従する。print-debug の主経路。
# `tail -F` は inode 切り替え (ローテーション / Resonite 再起動) を跨いで再追従する。
# host 側で起動する想定 (Resonite が動いているのは container ではなく host)。
# Gale 経由起動時のログは profile 側 (gale/BepInEx/LogOutput.log) に出る。
# Gale が将来仕様変更する場合は要再確認。
log:
    @GALE_ROOT="${GalePath:-./gale}"; \
    LOG="$GALE_ROOT/BepInEx/LogOutput.log"; \
    if [ ! -f "$LOG" ]; then \
        echo "NOTE: $LOG はまだ存在しません。Gale から Resonite を起動すると tail が自動的に追従します。" >&2; \
    fi; \
    tail -F "$LOG"

# format → gen-proto → build → test → type を直列実行。コミット前のゲート。
run: format gen-proto build test type

# ===== Docs (mkdocs) ====================================================
#
# ドキュメントサイトは repo root の mkdocs.yml + docs/ で構成し、Python API は
# mkdocstrings で python/src/resoio/ から自動生成する。docs deps は uv の
# `docs` dependency-group に分離しており、`just run` のゲートには含めない。

# ドキュメントサイトをローカルで preview する (live-reload)。
# http://localhost:8000 で開く。
docs-serve:
    cd python && uv run --group docs mkdocs serve -f ../mkdocs.yml -a 0.0.0.0:8000

# ドキュメントサイトを build する。--strict で nav 欠落 / 参照破綻 /
# mkdocstrings 未解決をビルド失敗にする (GH Action 無しのローカル CI 代替)。
docs-build:
    cd python && uv run --group docs mkdocs build -f ../mkdocs.yml --strict

# ===== Clean =============================================================

clean: clean-py mod-clean

clean-py:
    rm -rf python/.venv
    rm -rf python/.pytest_cache
    rm -rf python/.ruff_cache
    rm -rf python/.pyright
    rm -rf python/.coverage
    find python -type d -name '__pycache__' -prune -exec rm -rf {} +
    find python -type d -name '*.egg-info' -prune -exec rm -rf {} +

# ===== Host bridge (Resonite debug) =========================================
#
# host 常駐 daemon (`scripts/host_agent.py`) と container 側 client
# (`scripts/resonite_cli.py`) を組み合わせて、container 内 shell から host
# 上の Resonite を Gale 経由で start/stop/status する debug 経路。
# UDS は本番 gRPC IPC とは分離した $XDG_RUNTIME_DIR/resonite-io-debug/ を使う。

# container 側 `just resonite-*` のための debug bridge daemon を host で
# foreground 起動する。Ctrl+C で停止、socket は自動 unlink。環境変数の検査は
# host_agent.py 内で行う (DISPLAY / WAYLAND_DISPLAY / GaleBin が必要)。
# **GUI session の端末から実行** (gale は --no-gui でもディスプレイを要求)。
#
# screenshot action のために host 側専用 `pyscreenshot` を `scripts/.venv/` (uv venv
# 管理) に入れる。venv は冪等に確保 + 同期し、最新 deps で agent を起動する。
# scripts/.venv は host 専用 (container 側からは使わない、gitignore 済み)。
host-agent:
    @test -x scripts/.venv/bin/python || uv venv scripts/.venv --python 3.12
    @uv pip install --python scripts/.venv/bin/python -r scripts/requirements.txt --quiet
    scripts/.venv/bin/python scripts/host_agent.py

# container 内 shell (または host) から host の Resonite を起動する。
# profile 名は .env の GaleProfile を既定値とし、`--profile <name>` で override。
# 例: `just resonite-start` / `just resonite-start --profile my-profile`
resonite-start *ARGS:
    python3 scripts/resonite_cli.py start {{ARGS}}

# container 内 shell (または host) から Resonite / Renderite を停止する。
# SIGTERM → 3 秒待ち → SIGKILL の二段構え。Proton 系プロセスは触らない。
resonite-stop:
    python3 scripts/resonite_cli.py stop

# Resonite / Renderite の実行状態を JSON で表示する。
resonite-status:
    python3 scripts/resonite_cli.py status

# host_agent に screenshot RPC を投げて PNG を repo-relative path に書き出す。
# 例: `just resonite-screenshot output=tmp/e2e/desktop.png`
resonite-screenshot output:
    python3 scripts/resonite_cli.py screenshot --output {{ output }}
