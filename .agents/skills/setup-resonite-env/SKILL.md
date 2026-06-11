---
name: setup-resonite-env
description: "Use when setting up the resonite-io dev environment on a fresh clone, configuring Gale profile, setting Steam Launch Options (WINEDLLOVERRIDES), or troubleshooting mod-load failures. Triggers: 'just init', 'Gale プロファイル', 'WINEDLLOVERRIDES', 'check-gale', 'mod が読まれない', '環境構築', 'fresh clone'."
version: 0.1.0
---

# Setup Resonite-IO Dev Environment

resonite-io をホストで動かすために必要な準備の一覧と落とし穴の解説。ホスト側で必要なものは **`docker` / `docker compose v2` / `just` に加えて devcontainer を開く手段 (VS Code の Dev Containers 拡張 / Zed / `@devcontainers/cli`) のいずれか**。.NET / uv / protoc / pre-commit はすべてコンテナ内に閉じている。

______________________________________________________________________

## 1. Docker 開発環境

開発ツール (.NET 10 SDK / uv / protoc / dotnet local tools / pre-commit) は **`debian:bookworm-slim` ベースの単一 image** に同梱し、host にはインストールしない。

- `compose.yml` は `name: resonite-io-${USER}` で **user 単位の名前空間** に分離 (同一ホストの複数アカウント / 複数 worktree が衝突しない)。`.devcontainer/devcontainer.json` がこの compose を参照する
- 作業ディレクトリは **host repo を `/workspace` に直接 rw bind**。host 側の編集が即座に container 側に反映され、container 内の build 成果物 (`bin/`, `obj/`, `python/.venv/` 等) も `.gitignore` 経由で host 側に出る
- Resonite フォルダは `/resonite` に **read-only bind** のみ (FrooxEngine.dll 等の HintPath 参照専用; mod の deploy 先ではない)
- Gale プロファイル (`./gale/`) は `/workspace/gale` 経由で参照する (`environment.GalePath: /workspace/gale` が csproj の deploy 先を解決)
- コンテナ内 `dev` user の **UID/GID を host user に一致** させて build (`HOST_UID` / `HOST_GID` を build-arg で渡す)。これにより `deploy-mod` で出力された DLL/PDB が host user 所有になり、host 側 git からそのまま見える
- NuGet / uv のキャッシュは **named volume** にマウントして再ビルドを高速化 (`/home/dev/.nuget` / `/home/dev/.cache/uv`)
- `csharpier` / `tcli` 等の .NET CLI ツールは **`.config/dotnet-tools.json` の local tool** として固定し、`dotnet tool restore` + `dotnet <tool>` で呼び出す

初回 setup フロー:

1. `.env.example` を `.env` にコピーし、`ResonitePath` を Steam の Resonite 実行ファイルディレクトリ絶対パスに設定。必要に応じて `GaleProfile` / `GaleBin` も
2. `just init` を host 側で実行 — docker / docker compose v2 検出 → `.env` 検証 → `ResonitePath` 検証 → Gale プロファイル確認を冪等に実施
3. devcontainer を開く — **VS Code**: 「Dev Containers: Reopen in Container」、**Zed**: dev container として開く、**CLI** (任意・headless / CI 用): `devcontainer up --workspace-folder .` → `devcontainer exec --workspace-folder . bash` (`@devcontainers/cli`、既定では未インストール)
4. devcontainer が自動実行する:
   - `initializeCommand` (host 側・作成前): `~/.resonite-io{,-debug}/` を 0700 で事前作成し、host UID/GID を `.env` に記録 (build-arg でコンテナ user に一致させ、deploy 成果物が host 所有になる)
   - `postCreateCommand` (container 内・作成後): `scripts/container-init.sh` を実行 (deps 解決: `dotnet tool restore` + `uv sync` + `pre-commit install` + Codex settings symlink)
5. 以降はコンテナ内ターミナルで `just gen-proto` / `just build` / `just deploy-mod` 等を従来どおり実行する

______________________________________________________________________

## 2. Gale プロファイル方式

**ホスト Resonite には BepisLoader を直接インストールしない** (Vanilla 維持)。代わりに [Gale](https://github.com/Kesomannen/gale) (v1.5.4+) のカスタムプロファイル機能で repo root の `./gale/` を mod sandbox にする。

手動セットアップ手順:

1. Gale で profile を新規作成し、パスを `<repo>/gale` に指定 (**指定先は EMPTY である必要があり、`./gale/` を事前に作らない**)
2. profile に以下 6 個を install:
   - `ResoniteModding-BepisLoader` (>=1.5.1)
   - `ResoniteModding-BepInExResoniteShim` (>=0.9.3)
   - `ResoniteModding-BepisResoniteWrapper` (>=1.0.2)
   - `ResoniteModding-BepInExRenderer` (>=5.4) ← Camera v2 で追加 (Renderer 側 BepInEx 5 framework、`Renderer/BepInEx/core/` に framework deploy)
   - `ResoniteModding-RenderiteHook` (>=1.1.1) ← Camera v2 で追加 (engine → Renderer doorstop inject)
   - `Nytra-InterprocessLib` (>=3.0.0) ← Camera v2 で追加 (engine ↔ Renderer shared-mem queue)
3. Gale で Resonite を起動すると `LinuxBootstrap.sh` がプロファイル版に差し替わり、BepInEx が有効化される
4. `just check-gale` (または `just init`) で必須 DLL の在中を検証
5. `just deploy-mod` で `gale/BepInEx/plugins/ResoniteIO/` に DLL+PDB が配置される (deploy 先 dir は csproj の `<Copy>` が自動 mkdir する)

`just check-gale` は BepInExRenderer 検出時に `Renderer/BepInEx/core/BepInEx.Preloader.dll` の存在で判定する (plugin dir ではなく framework dir に deploy するため。`feedback_bepinex_renderer_as_framework.md` 参照)。

### Camera v2 Renderer plugin (committed prebuilt)

Camera v2 の Renderer 側 plugin (`ResoniteIO.Renderer`、net472 Unity Mono、BepInEx 5) は、ローカル build 時に Renderer.csproj の `DeployRendererPlugin` が `gale/Renderer/BepInEx/plugins/ResoniteIO.Renderer/` へ DLL を deploy する (engine 側 `gale/BepInEx/plugins/ResoniteIO/` とは別系統)。

UnityEngine.CoreModule が非再配布で CI build 不可のため、配布物 (Thunderstore zip) には **committed prebuilt** `mod/prebuilt/renderer/` を同梱する (release-resonite skill §7 参照)。**Renderer のソース (`mod/src/ResoniteIO.Renderer/` ∥ `mod/src/ResoniteIO.RendererShared/`) を変更したら、Resonite のあるローカルで `just renderer-prebuild` を実行し `mod/prebuilt/` の差分を commit する**。忘れると `just run` 末尾の `check-renderer-prebuilt` (および CI の drift guard) が fail する。

ホスト Resonite を Vanilla で起動 (Gale を介さず Steam から直接起動) した場合は mod は読み込まれない。注意: Gale 経由起動後にホスト Resonite ディレクトリへ `hookfxr.ini` (`enable=true`) 等が残る場合がある。Vanilla 復帰時は確認すること。

______________________________________________________________________

## 3. Steam Launch Options (Camera v2 で必須)

Steam で Resonite を選択 → Properties → Launch Options に以下を設定する:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

- **なぜ必須**: Wine は system 同梱 `winhttp.dll` を優先するため、RenderiteHook が deploy した hook 版 `winhttp.dll` (= doorstop) を読ませるには Launch Options で override が必要。これが無いと Renderer 側 BepInEx は永遠に起動せず、Camera v2 の renderer-side plugin が load されない
- **debug が困難**: 真の原因が Steam Launch Options 漏れであることは `/proc/<pid>/environ` で確認できないと見抜けない (Wine プロセスの env を host から見るのが面倒)
- **代替経路は無い**: `host_agent.py` から env で `WINEDLLOVERRIDES` を渡しても Steam が sanitize するため通らない。Steam Launch Options が唯一の経路

______________________________________________________________________

## 4. UDS パスと pressure-vessel sandbox

- 本番 gRPC IPC は **`$HOME/.resonite-io/`**、container ↔ host debug bridge は **`$HOME/.resonite-io-debug/`** で host/container 同一絶対パスの bind 共有
- `$XDG_RUNTIME_DIR/` (= `/run/user/<UID>/`) は **pressure-vessel sandbox が通さない**ため不採用
- `/tmp/` も通らない。`$HOME/` 配下のみが安全
- 詳細は [`reference_pressure_vessel_paths.md`](../../../memory/reference_pressure_vessel_paths.md)

______________________________________________________________________

## 5. 関連 memory

- [`reference_pressure_vessel_paths.md`](../../../memory/reference_pressure_vessel_paths.md) — pressure-vessel の filesystem 共有経路
- [`reference_resonite_modding.md`](../../../memory/reference_resonite_modding.md) — BepisLoader / BepInEx / `bep6resonite` テンプレ / `ResoniteHooks` / Thunderstore packaging
- [`feedback_camera_v2_constraints.md`](../../../memory/feedback_camera_v2_constraints.md) — Wine sandbox 制約 / Renderite framebuffer 直取り / InterprocessLib / OverlayCamera / Settings API の落とし穴
- [`feedback_bepinex_renderer_as_framework.md`](../../../memory/feedback_bepinex_renderer_as_framework.md) — BepInExRenderer は plugin dir を作らず framework として deploy する規約 (check-gale の判定で重要)

______________________________________________________________________

## 6. 実機 mod load 検証手順

`just resonite-start` (host-agent 経由で Resonite を起動) → `just log` で `gale/BepInEx/LogOutput.log` を tail し、`Loading Plugin ResoniteIO` 行が出るのを確認 → `just resonite-stop` の流れ。Codex が container 内から host-agent bridge 経由で完結できる。詳細な debug 経路は [/debug-resonite-mod skill](../debug-resonite-mod/SKILL.md) を参照。
