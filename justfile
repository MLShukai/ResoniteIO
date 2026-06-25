set dotenv-load := true
set shell := ["bash", "-c"]

# 既定で help を出す。
default:
    @just --list

# ===== 環境構築 =========================================================

# 初回 host setup を 1 コマンドで実行する (host 上で実行、container 不要、冪等)。
# 詳細ロジックは scripts/init.sh に集約している:
#   docker / docker compose v2 検出 → .env 作成・検証 → ResonitePath 検証 →
#   Gale プロファイル確認 (未設置なら GaleProfile.r2z の import 手順を案内)。
init:
    bash scripts/init.sh

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

# Claude settings から Codex rules を形式変換する。
# skill / agent / prose guidance の移植は .agents/skills/migrate-claude に任せる。
migrate-codex *ARGS:
    python3 scripts/migrate_codex.py {{ARGS}}

# ===== Python (python/) =================================================

py-format:
    cd python && uv run ruff format . && uv run ruff check --fix .

py-test:
    cd python && uv run pytest -v --cov

py-type:
    cd python && uv run pyright

# e2e テストを実行する (container 内 `just resonite-launch` で起動する実機 Resonite が前提)。
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

# ===== Renderer prebuilt (Camera v2) ====================================
#
# Camera v2 の Renderer 側 plugin (net472 / Unity Mono / BepInEx 5) は
# UnityEngine.CoreModule が非再配布なため CI で build できない。そのため
# Resonite のあるローカルで build した成果物を mod/prebuilt/renderer/ に commit し、
# pack/CI はそれを build せずそのまま同梱する (thunderstore.toml の [[build.copy]])。
# 成果物が Renderer ソースに対して古くならないよう source-hash drift guard を設ける
# (scripts/renderer-prebuilt-hash.sh + mod/prebuilt/renderer.sha256 + check-renderer-prebuilt)。

# Renderer をローカル Release build し、committed prebuilt 成果物と source hash を更新する。
# **Resonite (ResonitePath) が必須** (Unity/Renderite DLL の解決に要る)。
# 成果物の DLL/PDB は mod/prebuilt/renderer/ に、source hash は兄弟パス
# mod/prebuilt/renderer.sha256 に書く (hash file は zip に入れない方針で dir 外に分離)。
# 実行後 mod/prebuilt/ の差分を commit すること。
renderer-prebuild:
    @if [ -z "${ResonitePath:-}" ] || [ ! -d "${ResonitePath:-}" ]; then \
        echo "ERROR: Renderer の prebuild には Resonite (ResonitePath) が必要です。" >&2; \
        echo "       devcontainer + bind-mount された Resonite 環境で実行してください。" >&2; \
        echo "       (ResonitePath='${ResonitePath:-<unset>}')" >&2; \
        exit 1; \
    fi
    cd mod && dotnet build src/ResoniteIO.Renderer/ResoniteIO.Renderer.csproj -c Release
    @SRC="mod/src/ResoniteIO.Renderer/bin/Release/net472"; \
    DEST="mod/prebuilt/renderer"; \
    if [ ! -f "$SRC/ResoniteIO.Renderer.dll" ]; then \
        echo "ERROR: build 出力に ResoniteIO.Renderer.dll が見当たりません ($SRC)。" >&2; \
        exit 1; \
    fi; \
    rm -rf "$DEST"; \
    mkdir -p "$DEST"; \
    cp "$SRC/ResoniteIO.Renderer.dll" "$DEST/"; \
    for f in ResoniteIO.Renderer.pdb ResoniteIO.RendererShared.dll System.Memory.dll; do \
        if [ -f "$SRC/$f" ]; then cp "$SRC/$f" "$DEST/"; fi; \
    done; \
    echo "[renderer-prebuild] Copied prebuilt file-set to $DEST/:"; \
    ls -1 "$DEST"
    bash scripts/renderer-prebuilt-hash.sh > mod/prebuilt/renderer.sha256
    @echo "[renderer-prebuild] Wrote source hash to mod/prebuilt/renderer.sha256:"
    @cat mod/prebuilt/renderer.sha256
    @echo "[renderer-prebuild] 完了。mod/prebuilt/ の差分を commit してください。"

# committed prebuilt が Renderer ソースと同期しているか検証する。
# Resonite 不要・build 不要 (CI でそのまま走らせるための軽量 drift guard)。
# 不一致なら非 0 で fail し、refresh 手順を案内する。
check-renderer-prebuilt:
    @HASH_FILE="mod/prebuilt/renderer.sha256"; \
    DLL="mod/prebuilt/renderer/ResoniteIO.Renderer.dll"; \
    if [ ! -f "$HASH_FILE" ]; then \
        echo "ERROR: $HASH_FILE が存在しません (Renderer prebuilt が未 commit)。" >&2; \
        echo "       Resonite のあるローカルで 'just renderer-prebuild' を実行し commit してください。" >&2; \
        exit 1; \
    fi; \
    if [ ! -f "$DLL" ]; then \
        echo "ERROR: $DLL が存在しません (prebuilt 本体欠落)。" >&2; \
        echo "       Resonite のあるローカルで 'just renderer-prebuild' を実行し commit してください。" >&2; \
        exit 1; \
    fi; \
    EXPECTED="$(cat "$HASH_FILE")"; \
    ACTUAL="$(bash scripts/renderer-prebuilt-hash.sh)"; \
    if [ "$EXPECTED" != "$ACTUAL" ]; then \
        echo "ERROR: Renderer のソースが committed prebuilt と乖離しています。" >&2; \
        echo "       Resonite のあるローカル環境で 'just renderer-prebuild' を実行し、" >&2; \
        echo "       mod/prebuilt/ の差分を commit してください。" >&2; \
        echo "       expected=$EXPECTED" >&2; \
        echo "       actual  =$ACTUAL" >&2; \
        exit 1; \
    fi; \
    echo "[check-renderer-prebuilt] OK: Renderer prebuilt は最新です ($ACTUAL)。"

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
        "$GALE_ROOT/Renderer/BepInEx/plugins/ResoniteIO" \
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

# mod を Thunderstore zip に pack し (`just mod-pack`)、それを Gale プロファイルへ
# 「実際のインストールと同じレイアウト」で展開する。Gale (BepisLoader installer) の
# routing を再現するので dev 配置 == 配布物 (resoio launch が探す nested レイアウト):
#   <root files> + plugins/<X> → BepInEx/plugins/ResoniteIO/( /<X>)
#   Renderer/<Y>               → Renderer/BepInEx/plugins/ResoniteIO/<Y>
# PkgDir = manifest の name (= ResoniteIO)。ローカル zip を Gale に import した時の dir 名。
# build 時の自動 deploy (csproj PostBuild) は廃止し、deploy はこの 1 経路に集約した。
# 配置先 GalePath は container env / repo root の ./gale/ (host) を優先順で解決。
deploy-mod: mod-pack
    #!/usr/bin/env bash
    set -euo pipefail
    GALE_ROOT="${GalePath:-./gale}"
    PKG="ResoniteIO"
    # 正規 version (csproj <Version>) で zip を特定する。mod/build/ は pack 時に
    # 掃除されず旧 version が残るため、mtime (ls -t) ではなく version で pin する。
    VERSION="$(grep -oP '<Version>\K[^<]+' mod/src/ResoniteIO/ResoniteIO.csproj | head -n 1)"
    ZIP="mod/build/mlshukai-ResoniteIO-${VERSION}.zip"
    if [ -z "$VERSION" ] || [ ! -f "$ZIP" ]; then
        echo "ERROR: pack 済み zip が見つかりません ($ZIP)。" >&2
        echo "       'just mod-pack' が成功しているか確認してください。" >&2
        exit 1
    fi
    if [ ! -d "$GALE_ROOT/BepInEx" ]; then
        echo "ERROR: Gale プロファイルが見つかりません ($GALE_ROOT/BepInEx)。" >&2
        echo "       Gale (https://github.com/Kesomannen/gale) v1.5.4+ で '<repo>/gale' に" >&2
        echo "       profile を作り、BepisLoader と必須 plugin を追加してください。" >&2
        exit 1
    fi
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    unzip -q -o "$ZIP" -d "$TMP"
    # --- engine 側: BepInEx/plugins/ResoniteIO/ をクリーンにして展開 ---
    ENGINE_DEST="$GALE_ROOT/BepInEx/plugins/$PKG"
    rm -rf "$ENGINE_DEST"
    mkdir -p "$ENGINE_DEST"
    # root files (manifest/icon/README/CHANGELOG/LICENSE) を package dir 直下へ。
    find "$TMP" -maxdepth 1 -type f -exec cp -p {} "$ENGINE_DEST/" \;
    # plugins/ の中身 (= ResoniteIO/) をそのまま入れる (= engine DLL が一段ネストする)。
    if [ -d "$TMP/plugins" ]; then cp -a "$TMP/plugins/." "$ENGINE_DEST/"; fi
    # --- renderer 側: Renderer/BepInEx/plugins/ResoniteIO/ (framework がある時だけ) ---
    # 旧 deploy 先 (Renderer/BepInEx/plugins/ResoniteIO.Renderer) と新配置先を掃除する。
    rm -rf "$GALE_ROOT/Renderer/BepInEx/plugins/ResoniteIO.Renderer" \
           "$GALE_ROOT/Renderer/BepInEx/plugins/$PKG"
    if [ -d "$TMP/Renderer" ]; then
        if [ -d "$GALE_ROOT/Renderer/BepInEx" ]; then
            RENDERER_DEST="$GALE_ROOT/Renderer/BepInEx/plugins/$PKG"
            mkdir -p "$RENDERER_DEST"
            cp -a "$TMP/Renderer/." "$RENDERER_DEST/"
            echo "Deployed renderer plugin to $RENDERER_DEST/"
        else
            echo "WARN: $GALE_ROOT/Renderer/BepInEx が無いため renderer plugin は未配置。" >&2
            echo "      Gale から Resonite を 1 度起動し BepInExRenderer の展開を待って再実行してください。" >&2
        fi
    fi
    # --- 検証: engine DLL が nested layout に居ること ---
    DLL="$ENGINE_DEST/$PKG/ResoniteIO.dll"
    if [ -f "$DLL" ]; then
        echo "Deployed mod to $ENGINE_DEST/ (engine DLL: $DLL)"
    else
        echo "ERROR: 展開後に engine DLL が見当たりません ($DLL)。zip 内容を確認してください。" >&2
        exit 1
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

# Resonite mod の BepInEx ログを追従する。print-debug の主経路。
# `tail -F` は inode 切り替え (ローテーション / Resonite 再起動) を跨いで再追従する。
# container 内 `just resonite-launch` で起動した mod がここ (gale/BepInEx/LogOutput.log)
# にログを書く。umu/Proton 自体の起動ノイズは別ファイル (gale/BepInEx/umu-launch.log)。
log:
    @GALE_ROOT="${GalePath:-./gale}"; \
    LOG="$GALE_ROOT/BepInEx/LogOutput.log"; \
    if [ ! -f "$LOG" ]; then \
        echo "NOTE: $LOG はまだ存在しません。Gale から Resonite を起動すると tail が自動的に追従します。" >&2; \
    fi; \
    tail -F "$LOG"

# リリース準備の version bump: csproj <Version> (正規ソース) / pyproject.toml /
# uv.lock を lockstep で <version> に揃える。CHANGELOG.md の確定は手動
# (RELEASE.md §4-1)。container 内で実行する (uv が必要)。
#   例: just bump-version 0.4.0 / just bump-version 0.4.0-rc1
bump-version version:
    bash scripts/bump-version.sh {{version}}

# format → gen-proto → build → test → type → check-renderer-prebuilt を直列実行。
# コミット前のゲート。末尾の check-renderer-prebuilt は Renderer ソースを変更したのに
# committed prebuilt の更新を忘れていないかを検出する drift guard (build/test に非依存)。
run: format gen-proto build test type check-renderer-prebuilt

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

# ===== Resonite (devcontainer 内起動) =========================================
#
# devcontainer 内で ResoniteIO mod 込みの Resonite を起動・停止する。利用者向けの
# 正式コマンド `resoio launch` / `resoio terminate` (umu-launcher で engine + renderer
# を起動/kill する非 gRPC のプロセス制御) の薄い wrapper。RESONITE_EXE
# (= /opt/resonite/Resonite.exe、entrypoint.sh が /resonite:ro から同期したコピー) と
# MOD_PATH (= /workspace/gale) は compose の environment が渡す。
#
# 共通前提:
#   - devcontainer 内で実行すること (umu-run が PATH に必要)
#   - ホスト側で GUI session (X11 / Xwayland) と audio (PipeWire / PulseAudio) が動いていること
#   - initialize.sh が DISPLAY / XAUTHORITY_HOST 等を .env に自動設定済みであること
#
# 初回起動は GE-Proton のダウンロード等で数分かかる。Resonite install の同期
# (/resonite -> /opt/resonite) は entrypoint.sh が container 起動時に済ませている。

# Resonite (engine + renderer) を mod 込みで起動し、両 PID を表示する。
# `--vanilla` で mod なし起動、`-e/--exe` `-p/--profile` で明示指定も可。
resonite-launch *ARGS:
    cd python && uv run resoio launch {{ARGS}}

# Resonite を停止する (engine + renderer に SIGTERM -> SIGKILL)。
# 引数なしで実行中インスタンスを自動検出して kill。PID を渡して個別指定も可。
resonite-stop *ARGS:
    cd python && uv run resoio terminate {{ARGS}}

# Resonite install を /resonite (ro bind) から /opt/resonite へ手動同期する。
# entrypoint.sh が container 起動時に一度同期するが、host 側で Resonite を更新した
# 後など、container を作り直さずに最新化したいときに使う。
resonite-sync:
    rsync -a --delete /resonite/ /opt/resonite/
