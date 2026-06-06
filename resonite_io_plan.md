# Resonite IO 実装計画

## 1. プロジェクト概要

**Resonite IO** は、Resonite を AI エージェントの実行環境として利用するための双方向 IPC ブリッジ。

設計思想は **強化学習的な抽象化ではなく、リアルタイムロボティクス的な設計**。`Observation/Action` の抽象レイヤーは持たず、`Camera` / `Speaker` / `Locomotion` といったモダリティごとに独立した機能を提供する。RL の `step()` 同期はスコープ外で、強化学習インターフェイスは Python 側ライブラリで上に構築されるべきもの。

### 機能要件(初期スコープ)

モダリティ単位で実装する。**音声系は双方向を 1 つの service にせず、方向別に独立した modality として分離**する (実装複雑度と将来の format / device 拡張の独立性を優先):

- **Camera**: エージェント一人称視点の RGB フレームストリーミング (Resonite → Python)
- **Speaker**: Resonite が鳴らしている final mix (world audio + 他人 voice + UI sound) を Python に配信 (Resonite → Python)
- **Microphone**: Python が生成した音声を Resonite ユーザー voice として送り込む (Python → Resonite)
- **Locomotion**: 移動・姿勢制御 (Python → Resonite)
- **Manipulation**: Hand pose / Grab / Release (Python → Resonite)
- (将来: 視線・proprioception・触覚など)

各モダリティは **独立した非同期ストリーム** として動作し、**1 service = 1 方向** を原則とする。Camera / Speaker は server-streaming で受信、Locomotion / Manipulation / Microphone は client-streaming で送信。技術的にはすべて gRPC streaming。

### スコープ外

- RL の `step()` 同期インターフェイス (Python 側ライブラリの責務)
- ワールド作者定義 API (ProtoFlux Dynamic Impulse 経由)
- マルチユーザー・マルチエージェント (単一ユーザー操作のみ)
- ワールド固有の機能 (ワールド非依存に設計)

### 非機能要件

- Linux 開発環境を一級でサポート (ディストロ非依存)
- 通信データ型は **pyright strict** をクリアする型付け
- 各モダリティが他のモダリティに依存しない (片方だけ使う構成も可能)

### 設計レイヤー

実装は **コア層** と **mod 層** の二層に分離する。コア層は Resonite に一切依存しないピュアな C# / Python ライブラリとして実装し、mod 層は engine bridging のみを担う薄いアダプタとする。

- **コア層** (`ResoniteIO.Core` / `resoio`): gRPC server / client、UDS lifecycle、proto handler、各モダリティのドメインロジック。BepInEx / FrooxEngine / Renderite を参照しない。実機 Resonite なしで Kestrel ラウンドトリップを含む統合テストが書ける
- **mod 層** (`ResoniteIO`): BepInEx Plugin として Resonite に in-process でロードされ、コア層が要求する callback interface (`ISessionBridge`, `ICameraBridge`, …) を FrooxEngine API で実装する純粋な adapter。ドメインロジックは持たない
- **Python 層** (`resoio`): すでにピュア Python であり、gRPC client のみ。Resonite には依存しない

依存方向: **Core ← Mod** (Mod が Core を参照、逆は禁止)。これにより将来 Crystite 方式の独自ホストや軽量レンダラへ移植する際、Core 層をそのまま再利用できる。

______________________________________________________________________

## 2. アーキテクチャ概要

```text
            [Python Process]                    [Resonite Process]
   ┌────────────────────────────┐    ┌─────────────────────────────────────────┐
   │  resoio (Python pkg)       │    │  ResoniteIO (BepisLoader mod, adapter)  │
   │   ├ Camera client          │    │   ├ FrooxEngineCameraBridge             │
   │   ├ Speaker client         │    │   ├ FrooxEngineSpeakerBridge            │
   │   ├ Microphone client       │   │   ├ FrooxEngineMicrophoneBridge       │
   │   ├ Locomotion client      │    │   ├ FrooxEngineLocomotionBridge         │
   │   ├ Manipulation client    │    │   ├ FrooxEngineManipulationBridge       │
   │   └ Session (gRPC base)    │    │   └ FrooxEngineSessionBridge            │
   │            ▲               │    │            │  (DI: ISessionBridge 等)   │
   │            │               │    │            ▼                            │
   │            │UDS gRPC       │    │  ResoniteIO.Core (pure C# library)      │
   │            │               │←──→│   ├ CameraService                       │
   │            │               │UDS │   ├ SpeakerService                      │
   │            │               │gRPC│   ├ MicrophoneService                   │
   │            │               │    │   ├ LocomotionService                   │
   │            │               │    │   ├ ManipulationService                 │
   │            │               │    │   └ SessionService / SessionHost        │
   └────────────┘               │    └─────────in-process─────────────────────┘
                                                    │
                                              [FrooxEngine]
                                                    ↓ shmem IPC
                                              [Renderite (Unity)]
```

依存方向: **Python client → UDS gRPC → Core ← Mod (Bridge 注入)**。Core は Resonite を知らない。

### 採用方針

- **Mod 方式** (BepisLoader) として実装。Resonite の認証・同期・アセットを丸ごと利用
- 通常クライアント上で動作 (描画が必要なため Headless は不可)
- C# 側のモジュール構造と Python 側のモジュール構造を **モダリティ単位でミラーリング**
- **コア機能は Resonite 非依存** (`ResoniteIO.Core`)。BepInEx / FrooxEngine / Renderite に依存するコードは `ResoniteIO` (mod) に局所化する
- **mod 層は engine bridging のみ**: コアが要求する Bridge インターフェイスを FrooxEngine API で実装し、`OnEngineReady` でコアを起動・shutdown で停止する純粋なアダプタ
- **Bridge インターフェイスはモダリティ単位で分割**: `ISessionBridge` / `ICameraBridge` / `ISpeakerBridge` / `ILocomotionBridge` / `IManipulationBridge` `IMicrophoneBridge` のように独立 IF を保ち、肥大化を防ぐ。**音声系は双方向を 1 IF にまとめず、方向別に分離** (Speaker / Microphone)

### モダリティ別の実装方針

| モダリティ   | Core 側 Service                  | Mod 側 Bridge 実装                                                                               | 通信パターン  |
| ------------ | -------------------------------- | ------------------------------------------------------------------------------------------------ | ------------- |
| Session      | `SessionService` / `SessionHost` | `FrooxEngineSessionBridge` (`FocusedWorld` / `LocalUser` を露出)                                 | unary         |
| Camera       | `CameraService`                  | `FrooxEngineCameraBridge` (`Camera` 生成 + `RenderTextureProvider` 読出)                         | server-stream |
| Speaker      | `SpeakerService`                 | `FrooxEngineSpeakerBridge` (HarmonyLib Postfix で `AudioOutputDriver.AudioFrameRendered` を tap) | server-stream |
| Microphone   | `MicrophoneService`              | `FrooxEngineMicrophoneBridge` (`AudioInput` 派生 + `AudioSystem.RegisterAudioInput`)             | client-stream |
| Locomotion   | `LocomotionService`              | `FrooxEngineLocomotionBridge` (`LocalUser.Root` 直接駆動)                                        | client-stream |
| Manipulation | `ManipulationService`            | `FrooxEngineManipulationBridge` (Hand Slot Pose + `Grabber`)                                     | client-stream |

### 同期戦略

**完全非同期・各モダリティ独立**。

- Camera は描画フレームが出来次第 push
- Speaker は WASAPI audio callback が final mix を渡してきた段階で push (48 kHz / Stereo / float32 LE 固定)
- Locomotion / Manipulation / Microphone は Python 側のタイミングで送信
- グローバルな clock や barrier は持たない

各ストリームに **タイムスタンプ** を付与し、必要な同期は受信側 (Python) で行う。

______________________________________________________________________

## 3. Step 0: 開発環境・プロジェクトセットアップ

> **ステータス: 完了**。Docker ベースの開発環境に切り替わったため、当初想定していた host 直インストールの `setup.sh` は廃止。

### A. Resonite 実行環境 (Linux)

- [x] Steam で Resonite をインストール (Linux ネイティブ FrooxEngine + Proton 経由 Renderite)
- [x] BepisLoader を導入
- [x] Sunshine + Moonlight でリモートデスクトップ動作確認
- ~~開発用プライベートワールド~~ (不要: ワールド非依存に設計)

### B. 開発ツールチェーン (Docker 化)

ホスト側に必要なのは **`docker` / `docker compose v2` / `just` の 3 つだけ**。
.NET SDK / uv / protoc / pre-commit はすべて `debian:bookworm-slim` ベースの単一 image に同梱。

- [x] `.devcontainer/Dockerfile` (.NET 10 SDK / uv / just / protoc + shellcheck/shfmt)
- [x] `compose.yml` (`name: resonite-io-${USER}` で user 単位の名前空間、host repo を `/workspace` に rw bind、`${ResonitePath}` を `/resonite` に ro bind、Gale プロファイルは `/workspace/gale` 経由で参照。`build:` は `context: .devcontainer` / `dockerfile: Dockerfile`)
- [x] `.devcontainer/devcontainer.json` (compose 参照) + `.devcontainer/initialize.sh` (host 側 pre-create フック)
- [x] `scripts/container-init.sh` (container 内 deps restore: `dotnet tool restore` + `uv sync` + `pre-commit install` + Claude settings symlink。devcontainer の `postCreateCommand` から呼ばれる)
- [x] `just init` (host 側 one-time setup: docker / `.env` / Gale プロファイル確認)
- [x] dotnet local tools (`.config/dotnet-tools.json`): `csharpier`, `tcli` (Thunderstore packaging), `ilspycmd` (decompile)
- [x] `pre-commit` (ruff / pyupgrade / docformatter / mdformat / codespell / uv-lock / pygrep / shellcheck / shfmt)
- [x] VSCode 推奨拡張一覧 (`.vscode/extensions.json`): C# Dev Kit / Pylance / Ruff / csharpier / buf / docker など
- ~~`scripts/setup.sh`~~ (廃止: Docker 環境に置き換え)
- [x] **UDS socket 共有ディレクトリの bind**: 当初は `$XDG_RUNTIME_DIR/resonite-io/` を採用予定だったが、Step 2 実装時に **pressure-vessel (Steam Linux Runtime) が `/run/user/<UID>` を sandbox tmpfs で覆い、host 側 IPC を通さない**ことが判明 (詳細: `memory/reference_pressure_vessel_paths.md`)。最終的に `$HOME/.resonite-io/` を host / container 双方で同一絶対パスとして rw bind 共有する方式に変更 (`compose.yml` の long-form bind: `${HOME}/.resonite-io:/home/dev/.resonite-io:rw`、`HOME` は host shell から解決)。container 側 username は `dev` 固定だが host の `~` と同じ inode に到達する。host 側ディレクトリは devcontainer の `initializeCommand` が `0700` で事前作成 (Docker 任せだと root 所有になる)。同 `initializeCommand` が host uid/gid を `.env` に記録し、build-arg でコンテナ user に一致させる。socket ファイル名は mod 側で `resonite-{Process.Id}.sock` を自動命名 (Step 2 で実装済み)。Python client は `RESONITE_IO_SOCKET` (フルパス) → `RESONITE_IO_SOCKET_DIR` → 既定 `$HOME/.resonite-io/` の優先順で探索 (`.env` への記述は通常不要)。
- [x] **Container ↔ Host Resonite debug bridge**: Step 2 で `scripts/host_agent.py` (host 常駐 daemon) + `scripts/resonite_cli.py` (container 側 client) を追加。container 内 `just resonite-start/stop/status` で host の Resonite を Gale 経由で起動・停止できる。トランスポートは本番 IPC と分離した `$HOME/.resonite-io-debug/host-agent.sock` (同じく rw bind)。print-debug (`just log`) と並ぶ二本目の debug 経路で、proto / Core / mod を一切触らない。

### C. モノレポ構造

- **リポジトリ名**: `resonite-io`
- **C# コアライブラリ アセンブリ名**: `ResoniteIO.Core` (Step 2 で新設済み)
- **C# Mod アセンブリ名**: `ResoniteIO` (mod アダプタ層)
- **Python パッケージ名**: `resoio`

下記は Step 3 完了時点の実構造。Audio / Locomotion / Manipulation 配下は `.gitkeep` のみで、後続 Step で実装が入る。

```text
resonite-io/
├── compose.yml                    # dev サービス定義 (UID/GID 一致 / repo を /workspace に bind / ResonitePath ro bind / ~/.resonite-io{,-debug}/ rw bind、build context は .devcontainer/)
├── .devcontainer/
│   ├── devcontainer.json          # compose 参照 (initializeCommand / postCreateCommand)
│   ├── Dockerfile                 # 開発コンテナ image (debian + .NET 10 + uv + protoc)
│   └── initialize.sh              # host 側 pre-create フック (~/.resonite-io{,-debug}/ 0700 作成 + uid/gid を .env に記録)
├── justfile                       # ルートタスクランナー (build / test / resonite-* / host-agent)
├── buf.yaml                       # proto lint/breaking (modules: proto/、SERVICE_SUFFIX + RPC_*_STANDARD_NAME を except)
├── .pre-commit-config.yaml
├── .env.example                   # ResonitePath / GaleProfile / GaleBin の雛形 (.env は gitignore)
├── resonite_io_plan.md            # ◀ 本ファイル (全体計画書)
│
├── proto/                         # 単一の真実: .proto 定義
│   └── resonite_io/v1/
│       ├── session.proto          # Step 1 (Ping RPC)
│       └── camera.proto           # Step 3 (StreamFrames server-streaming)
│                                  # audio/locomotion/manipulation は後続 Step で追加
│
├── mod/                           # C# 側 (.NET 10、Core/Mod 二層構成)
│   ├── ResoniteIO.sln
│   ├── Directory.Build.{props,targets}
│   ├── NuGet.config
│   ├── thunderstore.toml          # Thunderstore メタデータ (tcli が読む)
│   ├── icon.png
│   ├── src/
│   │   ├── ResoniteIO.Core/                       # ◆ Core 層 (Resonite 非依存)
│   │   │   ├── ResoniteIO.Core.csproj             # Protobuf <Server> + Grpc.AspNetCore.Server
│   │   │   ├── Logging/ILogSink.cs                # BepInEx 非依存のロギング abstraction
│   │   │   ├── Bridge/                            # mod から注入される engine callback IF
│   │   │   │   ├── ISessionBridge.cs              # Step 2
│   │   │   │   └── ICameraBridge.cs               # Step 3
│   │   │   ├── Session/
│   │   │   │   ├── SessionService.cs              # Session.SessionBase 実装
│   │   │   │   └── SessionHost.cs                 # Kestrel UDS host (~/.resonite-io/)
│   │   │   └── Camera/CameraService.cs            # StreamFrames (server-streaming) 実装
│   │   └── ResoniteIO/                            # ◆ Mod 層 (BepInEx adapter, ProjectReference: Core)
│   │       ├── ResoniteIO.csproj                  # Core 依存 DLL + AspNetCore shared framework を gale/ に deploy
│   │       ├── ResoniteIOPlugin.cs                # BasePlugin + OnEngineReady で Core を起動
│   │       ├── Loading/PluginAssemblyResolver.cs  # Resonite 同梱旧 Google.Protobuf より Core 同梱版を優先解決
│   │       ├── Logging/BepInExLogSink.cs          # ILogSink → ManualLogSource adapter
│   │       ├── Bridge/                            # FrooxEngine 依存実装 (Core IF の実装)
│   │       │   ├── FrooxEngineSessionBridge.cs    # Step 2
│   │       │   └── FrooxEngineCameraBridge.cs     # Step 3
│   │       └── {Audio,Locomotion,Manipulation}/   # .gitkeep のみ (Step 4+ で実装)
│   └── tests/
│       ├── ResoniteIO.Core.Tests/                 # Kestrel ラウンドトリップ + Camera streaming (Fake Bridge) を含む統合 xunit
│       ├── ResoniteIO.Tests/                      # mod 側 smoke + BepInExLogSink 等の adapter テスト
│       └── manual/                                # 実機 (Resonite 起動) を要する手順書 (Markdown)
│
├── python/                        # Python 側 (Resonite 非依存)
│   ├── pyproject.toml             # requires-python >=3.12, deps: betterproto2[grpclib]
│   ├── uv.lock
│   ├── src/resoio/
│   │   ├── __init__.py            # importlib.metadata で __version__、SessionClient / CameraClient を re-export
│   │   ├── py.typed
│   │   ├── _socket.py             # private: RESONITE_IO_SOCKET / _DIR / ~/.resonite-io 探索
│   │   ├── session.py             # SessionClient (async context manager) + Ping
│   │   ├── camera.py              # CameraClient (numpy ndarray yield)
│   │   └── _generated/            # protoc 出力 (commit、pyright/ruff/coverage の exclude 対象)
│   │       └── resonite_io/v1/
│   └── tests/
│       ├── resoio/{test_session,test_camera,test_init}.py
│       └── e2e/                   # 実 Resonite 接続テスト (pytest --ignore=python/tests/e2e で除外)
│
├── scripts/
│   ├── gen_proto.sh               # .proto → Python コード生成 (C# 側は csproj が build-time に生成)
│   ├── decompile.sh               # ilspycmd で Resonite first-party + Renderite Unity DLL を decompiled/ に展開
│   ├── container-init.sh          # container 内 deps restore
│   ├── lib.sh                     # 共通シェルユーティリティ
│   ├── host_agent.py              # host 常駐 daemon (Step 2 追加、container → host Resonite bridge)
│   └── resonite_cli.py            # container 側 client (`just resonite-{start,stop,status}` から呼ばれる)
│
├── decompiled/                    # ILSpy 出力 (gitignore、`just decompile` で再生成)
├── gale/                          # Gale (Resonite mod manager) profile 展開先 (gitignore、host で Gale が管理)
├── .claude/
│   ├── memory/                    # プロジェクト固有 memory (本リポジトリで git 管理)
│   ├── agent-memory/              # サブエージェント由来の memory (同上)
│   ├── agents/                    # subagent 定義
│   └── settings*.json
├── .github/workflows/             # (未整備)
└── README.md
```

### D. ビルド・デプロイサイクル

| 経路              | 役割                                                                                                                                              |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `just init`       | host 側 one-time setup (docker / `.env` / Gale プロファイル確認、冪等)                                                                            |
| devcontainer      | `just init` 後に「Reopen in Container」/ `devcontainer up` で起動。image build + deps 解決 (`postCreateCommand` = `container-init.sh`) を自動実行 |
| `just gen-proto`  | Python 側コード生成 (C# は csproj `<Protobuf>` で build-time 生成)                                                                                |
| `just deploy-mod` | `dotnet build` → csproj の PostBuild Target で `$(GalePath)/BepInEx/plugins/`                                                                     |
| `just decompile`  | ILSpy で Resonite アセンブリを project 形式で `decompiled/` に展開                                                                                |
| `just log`        | `$(GalePath)/BepInEx/LogOutput.log` を host で `tail -F` (debug 主経路)                                                                           |
| `just mod-pack`   | `dotnet build -t:PackTS` で Thunderstore zip を `mod/build/` に生成                                                                               |

Python 側は `uv sync` で editable install 含めて完結。

**Debug 戦略**: mod は Resonite (host プロセス) に in-process でロードされるため、container 内から直接 attach する経路はない。Step 3 までは `ResoniteIOPlugin.Log` (BepInEx `ManualLogSource`) からの **print-debug + `just log` でのログ tailing** に加え、**container ↔ host Resonite bridge** (`scripts/host_agent.py` + `scripts/resonite_cli.py`、`just resonite-{start,stop,status}`) を二本目の debug 経路として整備済み。Step 2-3 はこの 2 系統で十分間に合ったため、`deploy-mod` 時に同梱される PDB を使う .NET debugger attach (host IDE → Resonite プロセス) は Step 4 以降で必要になった時に整備する。

将来: BepisLoader の .NET Hot Reload (debugger attach 時)。

### E. CI (GitHub Actions)

**C# 側**:

- ビルド (`resonite-modding-group/setup-resonite-env-action` 利用)
- テスト (xunit)
- Formatter チェック (csharpier)
- Linter (Roslyn analyzers + warnings-as-errors)

**Python 側**:

- pytest
- Formatter (ruff format)
- Linter (ruff check)
- Type-check (**pyright strict**)

**Proto 整合性**:

- `.proto` 変更後に `gen_proto.sh` を再実行した結果が commit 済み生成物と一致するかチェック

______________________________________________________________________

## 4. 残った論点

すべての論点が解決済み。詳細は `§5 決定事項` を参照。

______________________________________________________________________

## 5. 決定事項

- ✅ モノレポ (GitHub 単一リポジトリ)
- ✅ リポジトリ名 `resonite-io` / C# Mod `ResoniteIO` / **Python pkg `resoio`**
- ✅ Python パッケージマネージャ: `uv`
- ✅ IPC: gRPC over Unix Domain Socket
- ✅ Python gRPC スタック: `betterproto2` + `grpclib` (async)
  - **Python 3.12+ 必須** (`python/pyproject.toml` の `requires-python` と pyright `pythonVersion` で固定)
  - 依存は `betterproto2[grpclib]`。**`betterproto2_compiler` は別 distribution として配布されており `[compiler]` extra は存在しない** (PyPI metadata 2026-05 で確認済み)。dev グループに固定し、`uv run protoc --python_betterproto2_out=...` で呼び出す
  - 生成コードは Python dataclass + type hints ネイティブで pyright strict をそのまま通る想定
- ✅ C# / Python のモジュール構造はモダリティ単位でミラーリング
- ✅ 各モダリティは独立非同期ストリーム (RL `step()` なし)
- ✅ ワールド非依存・単一ユーザー操作スコープ
- ✅ 通信データ型は pyright strict 準拠
- ✅ **開発環境は Docker 化** (`debian:bookworm-slim` ベース単一 image)。ホストには `docker` / `docker compose v2` / `just` の 3 つだけ要求。当初想定していた `setup.sh` は廃止
- ✅ 補助ツール: ライセンス MIT、formatter (csharpier / ruff)、type-check (pyright strict)、test (xunit / pytest)
- ✅ **C# Linter/Analyzer**: csharpier + Roslyn analyzers + `Nullable=enable` + `TreatWarningsAsErrors=true` (StyleCop は不採用)
- ✅ **C# Mod SDK**: `Microsoft.NET.Sdk` + BepisLoader 公式 Template の NuGet 群 (`BepInEx.ResonitePluginInfoProps` / `ResoniteModding.BepInExResoniteShim` / `ResoniteModding.BepisResoniteWrapper`)。当初検討した `Remora.Resonite.Sdk` は不採用
- ✅ **C# 側 proto 生成**: `Grpc.Tools` の `<Protobuf>` ItemGroup で `dotnet build` 時に自動生成 (Server スタブのみ)。`gen_proto.sh` は Python 側のみを扱う
- ✅ **dotnet local tools** (`.config/dotnet-tools.json`): `csharpier` / `tcli` / `ilspycmd`。global tool + PATH 操作は採らない
- ✅ **proto lint**: `buf` (`buf.yaml`、`SERVICE_SUFFIX` + `RPC_REQUEST_STANDARD_NAME` + `RPC_RESPONSE_STANDARD_NAME` を except)。message 型は `CameraFrame` のようなモダリティ固有ドメイン名で命名する規約 (Step 3 で確立、根拠は `memory/feedback_proto_rpc_naming_except.md`)
- ✅ **mod deploy**: csproj の PostBuild Target が `$(ResonitePath)/BepInEx/plugins/ResoniteIO/` に Copy する一本化。`scripts/deploy_mod.sh` は廃止
- ✅ **mod 配布**: Thunderstore zip を `dotnet build -t:PackTS` (`tcli` ラップ) で生成
- ✅ **proto スキーマは Step ごとに incremental に詰める** (Step 1 で `session.proto`、Step 3 で `camera.proto`、…)
- ✅ **BepInEx PluginGuid**: `net.mlshukai.resonite-io`
- ✅ **コア機能は Resonite 非依存**。BepInEx / FrooxEngine / Renderite に依存するコードは `mod/src/ResoniteIO/` (mod 層) に局所化する
- ✅ **C# は二層構成**: `ResoniteIO.Core` (pure library) と `ResoniteIO` (BepInEx mod アダプタ)。Mod は Core を `ProjectReference` し、Bridge インターフェイス経由で engine 依存処理を注入する
- ✅ **C# proto 生成は Core 側に集約**。`<Protobuf GrpcServices="Server" />` は `ResoniteIO.Core.csproj` に置く。Mod 側 csproj は Core への ProjectReference のみで proto 直接参照は持たない
- ✅ **C# gRPC server**: `Grpc.AspNetCore.Server` (Kestrel + UDS) を Core 側で使用、`WebApplication.CreateSlimBuilder()` で最小構成 (Reflection 等のオマケは含めない)
- ✅ **UDS socket path**: host と container で **`$HOME/.resonite-io/`** を同一絶対パスで rw bind 共有 (`compose.yml` long-form bind + `${HOME}` を host shell から解決。container 側 username は `dev` 固定だが host の `~` と同じ inode に到達)。`$XDG_RUNTIME_DIR/resonite-io/` を当初想定したが pressure-vessel (Steam Linux Runtime) が `/run/user/<UID>` を sandbox tmpfs で覆うため不採用 (詳細: `memory/reference_pressure_vessel_paths.md`)。socket ファイル名は mod が `resonite-{Process.Id}.sock` を採用し、1 host 上で複数 Resonite が共存可能。Python client は `RESONITE_IO_SOCKET` (フルパス) → `RESONITE_IO_SOCKET_DIR` → 既定 `$HOME/.resonite-io/` の順で解決し、ディレクトリ探索時は 1 個なら自動採用 / 複数なら明示指定を要求。host 側ディレクトリは devcontainer の `initializeCommand` が `~/.resonite-io{,-debug}/` を 0700 で先に作成 (`create_host_path: false` で fail-fast)。
- ✅ **AspNetCore shared framework の同梱**: Kestrel が要求する `Microsoft.AspNetCore.*` は framework reference のため、`CopyLocalLockFileAssemblies=true` でも bin/ に出ない。`ResoniteIO.csproj` の `CopyAspNetCoreSharedFrameworkRuntime` Target で `$(NetCoreRoot)shared/Microsoft.AspNetCore.App/$(BundledNETCoreAppPackageVersion)/*.dll` を TargetDir にコピーし、PostBuild の PluginFiles glob で gale 配下に同梱する (Step 2 Phase 4 で実機検証済み)。`Microsoft.NETCore.App` は Resonite ランタイムが既に持っているため include 不要。
- ✅ **Resonite 同梱 DLL との version skew 対策**: `mod/src/ResoniteIO/Loading/PluginAssemblyResolver.cs` が plugin folder を優先する resolver を attach し、Resonite 同梱の旧 `Google.Protobuf` より Core 同梱版を解決させる。Plugin.Load では resolver 接続前に Core 型を絶対触らない (触ると旧 Protobuf 解決で `TypeLoadException: Could not load type 'Google.Protobuf.IBufferMessage'`)。
- ✅ **Container ↔ Host Resonite debug bridge**: Step 2 で `scripts/host_agent.py` + `scripts/resonite_cli.py` を追加。本番 IPC とは分離した `$HOME/.resonite-io-debug/host-agent.sock` を使う。kill 範囲は `Resonite.exe` / `Renderite.Renderer.exe` の名前ベース pkill のみ (Proton / pressure-vessel / Steam reaper には触らない)。GUI session 必須 (gale は `--no-gui` でもディスプレイを要求するため SSH only セッションでは fail-fast)。
- ✅ **gRPC tools の重複型警告 (CS0436) 対策**: Core で Server stub、テスト csproj で Client stub を別生成すると同一 namespace に message 型が重複する。テスト csproj 限定で `<NoWarn>$(NoWarn);CS0436</NoWarn>` を入れる (mod 側は Core を ProjectReference するだけで proto 直参照しない方針なので mod 側は対象外)。
- ✅ **テスト戦略の二層化**:
  - Core 単体: Kestrel ラウンドトリップ含む統合テストを xunit で (Resonite 不要)
  - Mod adapter: BepInEx 依存があるため smoke test のみ
  - Python: in-process server + UDS round-trip で contract を検証
- ✅ **Bridge インターフェイスはモダリティ単位で分割**: `ISessionBridge` / `ICameraBridge` / `ISpeakerBridge` / `ILocomotionBridge` / `IManipulationBridge` `IMicrophoneBridge` のように独立 IF とし、肥大化を防ぐ
- ✅ **音声系は方向別に modality を分割**: 双方向 `Audio` service は採用せず、**Speaker** (Resonite → Python、Step 5 で実装) と **Microphone** (Python → Resonite、Step 7 で実装) を別 proto service として独立させる。理由: (1) 各方向で sample format / device 選択 / latency 要件が独立、(2) 双方向 bidi-stream にすると client 実装複雑度が跳ね上がる、(3) 将来 mic を実装しない選択肢を残せる。Speaker は stereo / Microphone は mono と format も独立に進化させた
- ✅ **Speaker tap 経路は Engine 側 Harmony Postfix で完結**: Step 5 で `AudioOutputDriver.AudioFrameRendered(float[] buffer, double dspTime)` (protected) を HarmonyLib Postfix で patch する経路を実装。Renderer plugin (Camera v2 と同等) は **不要**。サンプル format は **48 kHz / Stereo / float32 LE 固定** で proto に negotiation を持たない (将来別 format が必要になれば別 service として追加)。Patch は WASAPI audio thread から呼ばれるため Bridge 側は thread-safe な Channel (`PushedAudioFrameSpeakerBridge`、capacity 32 / DropWrite) で受ける。詳細: [memory/feedback_speaker_engine_tap.md](memory/feedback_speaker_engine_tap.md)

______________________________________________________________________

## 6. 今後のステップ

### Step 1: スケルトン構築 — **完了**

- [x] BepisLoader mod として最小構成で起動確認 (`mod/src/ResoniteIO/ResoniteIOPlugin.cs` — `BasePlugin.Load()` で `ResoniteHooks.OnEngineReady` を購読し起動ログを出力)
- [x] Python `resoio` パッケージのスケルトン (`session.py` は placeholder、`_generated/` に空の package marker、`__version__` は `importlib.metadata` 経由)
- [x] `proto/resonite_io/v1/session.proto` (Ping RPC) を追加
- [x] xunit smoke test (`mod/tests/ResoniteIO.Tests/`) + pytest scaffolding (`python/tests/resoio/`)
- [x] モダリティ別ディレクトリの `.gitkeep` を C# / Python 両側に配置 (Camera / Audio / Locomotion / Manipulation / Session)
- [x] `Engine.Current.WorldManager.FocusedWorld` から `LocalUser` を引いて Console にログ出力 → **Step 2 で `FrooxEngineSessionBridge` 経由で実装済み**

### Step 2: gRPC Session — **完了**

各 Step は Core/Mod 二層構成を前提に分割する (§設計レイヤー / §5 決定事項)。

- [x] **Core** (`ResoniteIO.Core`): プロジェクト新設、`Grpc.AspNetCore.Server` + `<Protobuf>` を Core 側に集約、`SessionService` (Ping echo + Unix nanos) と `SessionHost` (Kestrel + UDS lifecycle: `~/.resonite-io/` を `0700` で `mkdir`、`resonite-{Process.GetCurrentProcess().Id}.sock` で bind、起動時に stale socket を `File.Delete`、`AppDomain.ProcessExit` で best-effort `unlink`) を実装。Kestrel ラウンドトリップで xunit 統合テスト済 (Resonite 不要)
- [x] **Mod** (`ResoniteIO`): `ResoniteIOPlugin` から `SessionHost` を起動、`ISessionBridge` を FrooxEngine 実装 (`FrooxEngineSessionBridge`) で注入、`FocusedWorld` / `LocalUser` を Bridge 経由で露出 (proto は変更せず Plugin 側のログ出力に留めた判断: `memory/feedback_session_bridge_no_proto_change.md`)、`PluginAssemblyResolver` で Google.Protobuf version skew を回避、`AppDomain.ProcessExit` で best-effort graceful stop (`Engine.OnShutdown` 経路は次以降に先送り: `memory/agents/spec-driven-implementer/feedback_engine_onshutdown_deferred.md`)
- [x] **Python** (`resoio`): `SessionClient` (async context manager) と in-process server を tmp_path UDS で繋ぐ round-trip テスト、`_socket.py` に socket 探索ロジック (`RESONITE_IO_SOCKET` → `RESONITE_IO_SOCKET_DIR` → `~/.resonite-io/`)、`SocketNotFoundError` / `AmbiguousSocketError` を公開
- [x] **付随**: pressure-vessel 起因で UDS path を `~/.resonite-io/` に変更、container ↔ host Resonite debug bridge (`scripts/host_agent.py` + `scripts/resonite_cli.py`) を導入

### Step 3: Camera モジュール — **完了**

- [x] **proto** (`proto/resonite_io/v1/camera.proto`): `Camera.StreamFrames` (server-streaming) RPC。message 名はドメイン名 (`CameraFrame`, `CameraStreamRequest`) で命名し `RPC_REQUEST/RESPONSE_STANDARD_NAME` を except (規約: `memory/feedback_proto_rpc_naming_except.md`)
- [x] **Core** (`ResoniteIO.Core.Camera`): `CameraService` 実装。`ICameraBridge` は optional DI で `null` なら `Status.Unavailable`、`CameraNotReadyException` は `FailedPrecondition` に翻訳。`fps_limit` で pacing (理論値 +2 のスラックで tolerance テスト、根拠: `memory/feedback_streaming_fps_limit_test_tolerance.md`)。Fake Bridge による in-process streaming テスト済 (Resonite 不要)
- [x] **Mod** (`ResoniteIO.Bridge`): `FrooxEngineCameraBridge` でエージェント頭部 Slot に `Camera` コンポーネント生成 + `RenderTextureProvider` 読出。component graph 変更は `World.RunSynchronously` + `TaskCompletionSource` で engine tick 上にディスパッチ (パターン: `memory/feedback_bridge_engine_thread_dispatch.md`)。BGRA8 でなく **RGBA8** で readback (commit `5129bb6` で青被り解消)
- [x] **Python** (`resoio.camera`): `CameraClient` で server-stream を受信、numpy ndarray として yield。`tests/e2e/camera_stream.py` で MP4 dump (`e2e_artifacts/`、30fps) まで実施
- [x] **AspNetCore shared framework deploy 問題の解決**: §5 決定事項参照 (`CopyAspNetCoreSharedFrameworkRuntime` Target で SDK shared framework から DLL コピー)

### Step 4: Locomotion モジュール — **完了**

- [x] **proto** (`proto/resonite_io/v1/locomotion.proto`): `Locomotion.Drive` (client-streaming) RPC + `LocomotionCommand` (`move_forward` / `move_right` / `move_up` / `yaw_rate` / `pitch_rate` / `jump` / `velocity` / `crouch` / `unix_nanos` の 9 field) + `LocomotionDriveSummary`。message 命名規約 (Step 3 で確立した RPC standard-name except) を踏襲
- [x] **Core** (`ResoniteIO.Core.Locomotion`): `LocomotionService` (client-streaming) と `ILocomotionBridge` を実装。`SessionHost` に optional DI で mount (Camera と同形、Bridge `null` のとき `Status.Unavailable`)、`LocomotionNotReadyException` を `FailedPrecondition` に翻訳。Fake bridge + 3 ケース (正常 + `FailedPrecondition` + `Unavailable`) のラウンドトリップ xunit 済
- [x] **Mod** (`ResoniteIO.Bridge`): `FrooxEngineLocomotionBridge` で `HarmonyLib.AccessTools.FieldRefAccess` 経由に `SmoothLocomotionBase._normalInput` / `TargettingControllerBase<ScreenCameraInputs>._inputs` / `HeadSimulator._inputs` の private field を typed delegate で 1 度だけ解決し、`ExternalInput` に毎フレーム書き込む方式。`WorldFocused` で component cache を invalidate。engine update tick への dispatch は不要 (ExternalInput 書き込み自体は任意スレッド安全、消費は engine 側 `Analog3DAction.Evaluate` 等が tick 上で実施)
- [x] **Python** (`resoio.locomotion`): `LocomotionClient` を async ctx mgr として実装、`drive(commands: AsyncIterable[LocomotionCmd]) -> DriveSummary`。`LocomotionCmd` は frozen / slots dataclass、`unix_nanos` は `time.time_ns()` を自動付与。in-process server で 3 ケースの単体テスト済
- [x] **e2e** (`python/tests/e2e/locomotion.py`): Camera 受信と Locomotion 送信を `asyncio.gather` で並行起動、18 秒 8 phase シナリオ (前進 → 高速前進 (`velocity=2.0`) → 右ストラフ → 停止 → 右回転 → 見上げ → ジャンプ → クラウチ) を 30Hz で送信して mp4 dump。実機 E1 (2026-05-19) で **569 frames / 1.4 MB / 1280×720 mpeg4** の動画生成を確認
- [x] **発見事項**: (a) engine が `_verticalAngle -= y` で pitch を反転加算するため Bridge 側で `external_y = -pitch_rate` の符号反転を入れる、(b) `ExternalInput` は engine update tick で消費 + null reset されるため入力保持には 30Hz の連続発行が必要、(c) Camera bridge が現在 `CameraStreamRequest` の width/height を無視して renderer ネイティブ解像度を返す既存 bug を発見 — locomotion e2e の `VideoWriter` を初フレーム dimension に追従する lazy 初期化で吸収済み (`camera_stream.py` 側は未対応、§7 継続観察に追加)

### Step 5: Speaker モジュール — **完了**

> 旧計画の Step 5 = Manipulation / Step 6 = Audio (bidi) を入れ替え + 方向別分割した結果、Speaker (Resonite → Python) を先行して Step 5 に再配置した (ユーザー判断、2026-05-20)。Manipulation は Step 6 へ降格、Microphone は新規 Step 7 として独立。

- [x] **proto** (`proto/resonite_io/v1/speaker.proto`): `Speaker.StreamAudio(SpeakerStreamRequest) returns (stream AudioFrame)` (server-streaming) RPC。message 命名は `AudioFrame` (generic で将来 Microphone から import 再利用できる余地を残す) + `SpeakerStreamRequest`。format は 48 kHz / Stereo / float32 LE / interleaved 固定で proto に negotiation を持たない
- [x] **Core** (`ResoniteIO.Core.Speaker`): `SpeakerService` (server-stream) + `ISpeakerBridge` + `PushedAudioFrameSpeakerBridge` (`Channel` cap=32 / DropWrite / frame_id 0 から monotonic) + `SpeakerNotReadyException` を実装。`SessionHost` に optional DI で mount (Camera と同形、bridge=null のとき `Status.Unavailable`)。Bridge IF は **proto 型ではなく Core POCO `AudioFrame` (record struct)** を返す設計 (Fake bridge の CS0738 を避ける: `memory/feedback_bridge_iface_uses_core_poco.md`)。Fake bridge + 4 ケース (Unavailable / FailedPrecondition / Internal / 正常 3 frame) のラウンドトリップ xunit 済
- [x] **Mod** (`ResoniteIO.Bridge`): `FrooxEngineSpeakerBridge` で `AudioOutputDriver.AudioFrameRendered(float[], double)` (protected) を **HarmonyLib Postfix** で patch、WASAPI audio thread から `PushedAudioFrameSpeakerBridge.Push` 経由で channel へ送り込む。`Engine.Current.AudioSystem.PrimaryOutput` を対象とし、`DefaultAudioOutputChanged` event で device swap にも追従。`_singleton` static field 設計 (Postfix が static method 制約のため)。Camera v2 のような Renderer-side plugin は **不要** (Engine 側で完結)
- [x] **Python** (`resoio.speaker`): `SpeakerClient` を async ctx mgr として実装、`stream() -> AsyncIterator[AudioChunk]` で `AudioChunk.samples: NDArray[float32] shape=(N, 2)` を yield。定数 `SAMPLE_RATE=48000`, `CHANNELS=2`, `DTYPE=np.float32` を top-level export。in-process server で round-trip 単体テスト済
- [x] **CLI** (`resoio record`): `python/src/resoio/cli/record.py` で `resoio record -o OUTPUT [--duration SEC]` flat command を追加 (既存 `resoio capture` と並ぶ action 名 flat 哲学)。`.wav` 拡張子で WAV file 書き出し (stdlib `struct` で `WAVE_FORMAT_IEEE_FLOAT` header を手書き、close 時に size field を seek-back で更新)、`-o -` で raw float32 LE PCM stdout (ffmpeg pipe 用)。BrokenPipeError は rc=0 で正常終了 (capture と同パターン)
- [x] **e2e** (`python/tests/e2e/speaker_record.py`): 実機 Resonite から `SpeakerClient.stream()` で audio を受信し WAV へ書き出して `ffprobe` で format 検証 (sample rate 48000 / channels 2 / float / 期待秒数)

### Step 6: Manipulation モジュール — **完了**

> Step 6 (Manipulation) と Step 7 (Microphone) の実装順は **ユーザー判断で Step 7 を先行** (2026-05-20)。Speaker 完了直後に音声系を完結させたいニーズが優先された。Manipulation はその後に着手し完了 (2026-06-06)。
>
> **スコープ変更 (2026-06-06、実機調査に基づくユーザー判断)**: 当初計画の **Hand Pose 制御は除外**。`TrackedDevicePositioner.BeforeInputUpdate` が `[DefaultUpdateOrder(-1000000)]` で毎 input update に hand slot を tracked-device pose で上書きし、Locomotion のような `ExternalInput` フックも無いため engine 的にクリーンな注入経路が無い (desktop は laser/IK 駆動)。よって **Grab / Release のみ**を実装。また pose を外したことで操作は離散の edge-triggered となり、当初の client-streaming ではなく **ContextMenu と同じ unary RPC** を採用した。

- [x] **proto** (`proto/resonite_io/v1/manipulation.proto`): unary 3 RPC `Grab(ManipulationGrabRequest) returns (ManipulationGrabResult)` / `Release(ManipulationReleaseRequest) returns (ManipulationGrabState)` / `GetState(ManipulationGetStateRequest) returns (ManipulationGrabState)`。`ManipulationHand` enum (UNSPECIFIED/PRIMARY/LEFT/RIGHT、ContextMenuHand と同規約) + `WorldPoint` (message 不在 = 手の現在位置)。grab は world point + radius (radius\<=0 は Service 側で 0.1m default)
- [x] **Core** (`ResoniteIO.Core.Manipulation`): `ManipulationService` + `IManipulationBridge` + Core POCO (`ManipulationHandSelector` / `ManipulationPoint` / `GrabSnapshot` / `GrabOutcome`) + `ManipulationNotReadyException`。ContextMenuService と同形 (optional DI、bridge=null → `Unavailable`、NotReady → `FailedPrecondition`)。`SessionHost` に mount。Kestrel ラウンドトリップ + Fake bridge で xunit 済 (Core 185 tests green)
- [x] **Mod** (`ResoniteIO.Bridge`): `FrooxEngineManipulationBridge` で `world.LocalUser.GetInteractionHandler(side).Grabber` に到達し `Grabber.Grab(float3 point, float radius)` / `Release()` / `IsHoldingObjects` + `GrabbedObjects` を呼ぶ。ContextMenu bridge と同じ one-shot `RunOnEngineAsync` (engine thread dispatch)。掴んだ object は `HolderSlot` に reparent され手に自動追従するため **per-frame repeater 不要** (Locomotion と対照的)。engine 状態を持たず **非 IDisposable**
- [x] **Python** (`resoio.manipulation`): `ManipulationClient` を async ctx mgr として実装、`grab(*, hand, point, radius)` / `release(*, hand)` / `get_state(*, hand)`。dataclass `GrabResult` / `GrabState`、hand は `Literal["primary","left","right"]` (ContextMenu と同様 enum を避ける)。in-process grpclib + 実 UDS で round-trip 単体テスト済
- [x] **CLI** (`resoio manipulate`): `python/src/resoio/cli/manipulate.py` で flat positional action `{grab,release,state,interactive}` + `--hand` / `--point X Y Z` / `--radius` (ContextMenu 流)。`interactive` は locomotion 流 raw-tty キー操作 (g=grab / r=release / s=state / q=quit)
- [x] **e2e** (`python/tests/e2e/manipulation.py`): 実機 Resonite に対し get_state/grab/release の RPC 経路を検証 (mod ロード・Bridge が実 `Grabber` に到達・例外なし・hand 解決・release で is_holding False)。実機 green (1 passed / 55s)。default home に grabbable が無く API で決定的に spawn もできないため **positive grab (`grabbed=True` + object が手に追従する目視確認) は `mod/tests/manual/manipulation-verification.md` の人手手順**に残した

### Step 7: Microphone モジュール — **完了**

旧 Audio (bidi) service の片割れ。Python → Resonite に音声 (生成 voice / TTS / 外部 mic 入力 etc.) を送り込む経路。Step 6 (Manipulation) より先行実装 (上記ノート参照)。

- [x] **proto** (`proto/resonite_io/v1/microphone.proto`): `Microphone.StreamAudio(stream MicrophoneAudioFrame) returns (MicrophoneStreamSummary)` (client-streaming) RPC。Speaker の `AudioFrame` とは **共有せず独立 message** (`MicrophoneAudioFrame`) を新設 (Speaker = stereo / Microphone = mono で channel 数が異なるため、誤接続を型で防ぐ意図)。format は 48 kHz / Mono / float32 LE 固定で proto に negotiation を持たない
- [x] **Core** (`ResoniteIO.Core.Microphone`): `MicrophoneService` (client-stream) + `IMicrophoneBridge` + `MicrophoneNotReadyException` を実装。Locomotion パターン (Graceful / Cancelled / Errored の disconnect 通知) を踏襲。proto `bytes samples` → `float[]` は `MemoryMarshal.Cast<byte, float>` で defensive copy。`SessionHost` に optional DI で mount (Bridge null のとき `Status.Unavailable`)。Fake bridge + 5 ケース (Accumulates / BridgeNull / NotReady / GenericException / Cancellation) のラウンドトリップ xunit 済
- [x] **Mod** (`ResoniteIO.Bridge`): `FrooxEngineMicrophoneBridge` で `FrooxEngine.AudioInput` 派生 `ResoniteIOAudioInput` を `AudioSystem.RegisterAudioInput` に **virtual capture device** として登録。`SubmitFrame` で内部 ring buffer (2 sec 容量) に append、Locomotion 流 `World.RunInUpdates(0, TickStep)` self-rescheduling repeater が engine update thread から `WriteSamples<MonoSample>` 経由で AudioInput に push。`MonoSample` は `Elements.Assets.dll` にあり csproj に reference 追加。`AudioSystem.UnregisterAudioInput` API が engine 側に存在しないため Dispose は `AudioInputs.Remove` best-effort で対処 (再 load 時の重複登録 warning は機能影響なし)
- [x] **Python** (`resoio.microphone`): `MicrophoneClient` を async ctx mgr として実装、`stream(chunks: AsyncIterable[MicrophoneAudioChunk]) -> MicrophoneStreamSummary` で送信。caller が `frame_id` を指定、`unix_nanos=0` のとき client が `time.time_ns()` で auto-stamp。定数 `SAMPLE_RATE=48000`, `CHANNELS=1`, `DTYPE=np.float32` を top-level export
- [x] **CLI** (`resoio mic`): `python/src/resoio/cli/mic.py` で `resoio mic -i {PATH|-} [--duration SEC]` flat command を追加。WAV は sampwidth=4 (float32) と 2 (int16 → normalize) を受容、stereo は `(L+R)/2` で mono に down-mix、48 kHz 以外と channels>2 は exit 2。`-i -` で stdin から raw float32 LE mono PCM 受信。BrokenPipeError は rc=0
- [x] **e2e** (`python/tests/e2e/mic_send.py`): 440 Hz / 48 kHz / mono / float32 / 5 秒の正弦波 fixture WAV (`python/tests/e2e/fixtures/sine_440hz_5s_mono_48k.wav`、再現性のため commit、`generate_sine.py` で再生成可、Bridge ring buffer 2 秒を超える長さで pacing 動作を可視化) を `MicrophoneClient` 経由で送信して例外なく完走 + `received_frames=234 / received_samples=239616` を assert (CLI chunk 1024 で割り切った値、端数は drop)。voice として実際に他ユーザーに届くかの確認は本質的に人間しかできない (別アカウントで join + 聴覚確認) ため [mod/tests/manual/microphone-verification.md](mod/tests/manual/microphone-verification.md) に手動手順を残す
- [x] **CLI pacing** (`resoio.cli.mic` WAV mode): pre-loaded buffer を burst で流すと Bridge ring buffer (2 秒) を超える長さで末尾が drop され、また CLI が音声再生終了を待たず即終了する UX 問題を解消。warmup 5 chunks (≒107 ms) 分は engine tick の drain ramp-up を吸収する pre-buffer として burst、それ以降は `resoio.microphone.paced()` async generator helper に委譲して 1 chunk あたり 21.3 ms の wall-clock pacing。stdin pipe は上流が natural pacing なので未変更。`MicrophoneClient.stream` の default は producer のペース尊重 (TTS / live mic で二重 pacing を避けるため) で、`paced()` は opt-in helper として `__all__` に export

### Step 8 (将来): 独自クライアント / 並列化

- Crystite 方式の独自ホスト検討 — `ResoniteIO.Core` を別 host から再利用 (BepInEx 不要なため移植が容易)
- 軽量レンダラへの置き換え (PJB blog 参照)

______________________________________________________________________

## 7. リスク・未解決事項

### 解決済み (Step 2-5 で対処)

- ✅ **Renderite IPC のドキュメント不足**: Camera readback については `decompiled/` を読みながら Step 3 で実装完了。`Camera.RenderToBitmap` 経由で安全に readback できることが確認できた。BGRA8 → RGBA8 の色順問題に時間を取られた (commit `5129bb6`)。他モダリティで Renderite IPC 知見が必要になったら同じく decompile を読みつつ進める。
- ✅ **Kestrel が引き連れる依存と Resonite 同梱 DLL の version skew**: `Grpc.AspNetCore.Server` の transitive 群 (`Microsoft.AspNetCore.*` / `Microsoft.Extensions.*` / `System.IO.Pipelines`) は §5 の "AspNetCore shared framework の同梱" 方針で解決。Resonite 同梱の **旧 Google.Protobuf** との衝突は `PluginAssemblyResolver` で plugin folder を優先解決させる方針で解決 (`mod/src/ResoniteIO/Loading/`)。Plugin.Load 内で resolver attach 以前に Core 型を触ってはならないという制約が残る (詳細: `memory/reference_load_bearing_whys.md`)。
- ✅ **UDS socket の host ↔ container 共有**: pressure-vessel が `/run/user/<UID>` を sandbox tmpfs で覆うため、**`$HOME/.resonite-io/` ベースに変更**して解決 (§5 決定事項参照)。stale socket は SessionHost が bind 直前に `File.Delete` で除去する `unlink` 前提運用で十分機能している。
- ✅ **`AccessTools.FieldRefAccess` 経由の private field 解決**: Step 4 で `SmoothLocomotionBase._normalInput` / `TargettingControllerBase<ScreenCameraInputs>._inputs` / `HeadSimulator._inputs` を typed delegate で取得し ExternalInput を書き込む経路を実機検証。`AccessTools.FieldRefAccess<TDeclaring, TField>("name")` の generic 引数順 (declaring → field type) を含め、E1 動画 569 frames で機能を確認済。**緩和策**: field 名は engine update で silent に壊れる可能性があるため manual-test に「初回 `received_count > 0`」を pass 判定に入れ、Resonite update を踏んだら decompile 再生成 + field 名 diff 確認を行う。
- ✅ **engine update tick が `ExternalInput` を 1 frame で消費するセマンティクス**: `Analog3DAction.Evaluate` ([decompiled/FrooxEngine/FrooxEngine/Analog3DAction.cs](decompiled/FrooxEngine/FrooxEngine/Analog3DAction.cs)) が `_intermediateResult += ExternalInput.Value` 直後に `ExternalInput = null` する設計を実機確認。入力を維持したい場合は Python 側から **30Hz 程度で連続発行** する必要があり、stream を止めれば即 idle に戻る (送信責務 = active input、無送信 = neutral、というセマンティクス)。Bridge への書き込み自体は任意スレッドから安全 (engine thread dispatch 不要)。
- ✅ **Speaker (Resonite → Python) の取得経路**: Step 5 で `AudioOutputDriver.AudioFrameRendered(float[] buffer, double dspTime)` (protected) を HarmonyLib Postfix で patch する経路を確立。`Engine.Current.AudioSystem.PrimaryOutput` が WASAPI audio thread 上で final mix (world + voice + UI) を渡してくるため、Bridge は thread-safe Channel (cap=32 / DropWrite) で受けて gRPC server-stream に流す。Renderer plugin (Camera v2 と同等) は **不要**。`VideoTextureAudioWriter/Reader` ペア (Cloudtoid.Interprocess) は engine final mix と接続されておらず video export 専用のため使わない。detail: [memory/feedback_speaker_engine_tap.md](memory/feedback_speaker_engine_tap.md)。

### 継続観察

- ✅ **Microphone (Python → Resonite) の経路**: Step 7 で `FrooxEngine.AudioInput` 派生クラスを `AudioSystem.RegisterAudioInput` で virtual capture device として登録する経路を確立。`UserAudioStream<MonoSample>` が `DefaultAudioInput.NewFilteredSamples` を subscribe し `OpusStream<MonoSample>` 経由で他ユーザーに自動 broadcast されるため、**Opus encode は engine 側自動 (Bridge 不要)**。`AudioSystem.UnregisterAudioInput` API 不在の制約は `AudioInputs.Remove` best-effort で受け流す (機能影響なし)。Renderer plugin / HarmonyLib patch は **不要**。format は 48 kHz / Mono / float32 LE 固定 (voice broadcast 経路の `MonoSample` と直結し変換コストゼロ、Speaker = stereo とは proto 上 channel 数が異なる非対称設計)。**default mic 昇格は Bridge ctor で `AudioSystem.OverrideAudioInputIndex` 経由の非永続 auto-promote を採用** (2026-05-27 旧 UI 手動切替方針を revoke、user の `DevicePriorities` 設定ファイルは物理的に無傷)。残るマニュアル要素は別アカウントでの voice 受信耳確認のみで、起動・dispose 時の override 状態遷移は [python/tests/e2e/mic_auto_default.py](python/tests/e2e/mic_auto_default.py) が自動検証。手順書: [mod/tests/manual/microphone-verification.md](mod/tests/manual/microphone-verification.md)。detail: [memory/feedback_microphone_engine_tap.md](memory/feedback_microphone_engine_tap.md)。
- **ライセンス・ToS**: Resonite は明示的な研究用 bot 規定なし。慣習的には黙認〜歓迎。商用化や派手な公開実験を始める前にユーザーに確認する。
- **マルチエージェント**: スコープ外だが、将来は 1 Resonite インスタンス = 1 エージェントのコスト問題が出てくる。
- **Bridge インターフェイスの粒度**: モダリティが増えるにつれ IF が肥大化する懸念。各モダリティで独立 IF (`ISessionBridge`, `ICameraBridge`, …) として分割する方針 (§2 採用方針)。Step 3 完了時点で 2 IF (Session / Camera) のため肥大化はまだ起きていない。
- **`BasePlugin` に Unload 相当が無い**: BepInEx 6 の `BasePlugin` には mod 終了時 hook が無い。Step 2 で `AppDomain.ProcessExit` 経由の best-effort 停止を採用し、Step 3 でも `Engine.OnShutdown` 経路の調査は先送り継続中 (Camera 実装スケジュール優先、`FrooxEngineCameraBridge` も engine shutdown 後の `RunSynchronously` 例外を飲んで best-effort 設計にしている)。Step 4 以降で graceful shutdown 不整合に当たったら decompile 調査を再開する (`memory/agents/spec-driven-implementer/feedback_engine_onshutdown_deferred.md`)。
- **Bridge での engine-thread dispatch コスト**: Step 3 で `World.RunSynchronously` + `TaskCompletionSource` パターンを確立した。Step 4 (Locomotion) は ExternalInput 書き込みが任意スレッド安全だったため engine thread dispatch 不要で済んだが、Manipulation 以降で毎フレーム component graph 変更が必要なら一括化 (`UpdateOrder` 経由の per-tick callback 等) を検討する。
- **Camera bridge が `CameraStreamRequest.width/height` を無視している既存 bug**: Step 4 locomotion e2e の調査中に発覚。client が要求した解像度に関係なく renderer ネイティブ解像度 (E1 実測 1280×720) のフレームが返ってくる。locomotion 側は `VideoWriter` を初フレーム dimension に追従する lazy 初期化で吸収済みだが、`camera_stream.py` 側は要求解像度で `VideoWriter` を先に作る設計のため 257-byte の空 mp4 で false-pass する可能性がある (実害は出ていない)。Step 5 着手前に Camera 側の挙動修正 (要求解像度に追従させるか、proto から width/height を除いて renderer-native のみとする) を別 PR で着手する。

______________________________________________________________________

## 8. 参考リンク

- BepisLoader / Resonite Modding: <https://modding.resonite.net/>
- Remora.Resonite.Sdk: <https://www.nuget.org/packages/Remora.Resonite.Sdk>
- Crystite (custom headless): <https://github.com/Nihlus/Crystite>
- 独自レンダラ実装記録 (PJB blog): <https://slugcat.systems/post/25-04-25-making-a-custom-resonite-renderer/>
- Camera コンポーネント wiki: <https://wiki.resonite.com/Component:Camera>
- betterproto2: <https://github.com/betterproto/python-betterproto2>
- grpclib: <https://github.com/vmagamedov/grpclib>
- Grpc.AspNetCore.Server (Kestrel + UDS): <https://learn.microsoft.com/en-us/aspnet/core/grpc/aspnetcore>
