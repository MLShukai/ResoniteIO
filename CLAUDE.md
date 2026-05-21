# CLAUDE.md

このファイルは Claude Code (claude.ai/code) がこのリポジトリを扱う際のガイダンスを提供する。

## プロジェクト概要

`resonite-io` は **Resonite を AI エージェントの実行環境として使うための双方向 IPC ブリッジ**。Resonite クライアント側で動く C# Mod (`ResoniteIO`、BepisLoader) と Python パッケージ (`resoio`) を、gRPC over Unix Domain Socket で接続する monorepo。

設計思想は **強化学習的な抽象化ではなく、リアルタイムロボティクス的な設計**。`Observation/Action` の抽象は持たず、`Camera` / `Speaker` / `Microphone` / `Locomotion` / `Manipulation` といったモダリティ単位で独立した非同期ストリームを提供する。音声系は方向別に `Speaker` (Resonite → Python) と `Microphone` (Python → Resonite) を分離。RL の `step()` 同期はスコープ外で、Python 側ライブラリで上に構築されるべきもの。

C# 実装は **Core/Mod 二層構成**: コア機能 (gRPC server / Service / proto handler / 各モダリティのドメインロジック) は **Resonite に一切依存しないピュアライブラリ `ResoniteIO.Core`** に置き、BepInEx Plugin `ResoniteIO` は engine bridging のみを担う薄いアダプタとする。依存方向は **Core ← Mod** で逆参照禁止。Python (`resoio`) も Resonite 非依存。詳細は [feedback_core_mod_layering.md](.claude/memory/feedback_core_mod_layering.md) 参照。

C# / Python 両側のモジュール構造は **モダリティ単位でミラーリング** する。新規モダリティは Core 側 `<Modality>Service` + Mod 側 `FrooxEngine<Modality>Bridge` のペアで追加する。

詳細な背景・スコープ・採用技術・段階的実装計画は [resonite_io_plan.md](resonite_io_plan.md) を **必ず** 参照すること（Step 0〜8、決定事項一覧、リスク欄を含む）。

## メモリ・スキル参照

セッション開始時、または規約が関係しそうなタスクに着手する前に [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md) のインデックスを確認すること。タスク発火型の手順 (環境セットアップ / debug / 新規モダリティ追加) は [.claude/skills/](.claude/skills/) 配下に置き、Claude harness が trigger に応じて自動で読み込む。

新しい規約・フィードバックが判明したら `.claude/memory/feedback_*.md` を追加し `MEMORY.md` に 1 行リンクを張る。プロジェクト固有の規約は `.claude/memory/` に集約し、harness が自動ロードする `~/.claude/projects/.../memory/` パスは使わない (git 管理を優先する方針)。

## プロジェクト状況

**現状: Step 0〜5 と Step 7 が完了 (Step 6 は次に着手)**。Step 0 = Docker 化開発環境、Step 1 = mod/python/proto スケルトン、Step 2 = `Session.Ping`、Step 3 = Camera server-streaming RPC、Step 4 = Locomotion client-streaming RPC、Step 5 = Speaker server-streaming RPC、Step 7 = Microphone client-streaming RPC。次は **Step 6 (Manipulation モジュール)**。

詳細な Step 履歴・RPC 仕様・Bridge クラス命名等は [resonite_io_plan.md](resonite_io_plan.md) を正規とする。新規モダリティ追加の規約は [.claude/skills/add-new-modality/](.claude/skills/add-new-modality/) に集約。

実装済みの主要要素 (概観):

- 開発環境: `Dockerfile` / `docker-compose.yml` / `justfile` / `scripts/host_agent.py` + `scripts/resonite_cli.py` (container ↔ host Resonite bridge)
- C# Core (`mod/src/ResoniteIO.Core/`): モダリティ単位で IF と Service を `<Modality>/` 配下にまとめる (Session / Camera / Speaker / Microphone / Locomotion / Display)。共通基盤として `UnixNanosClock` / `ILogSink`
- C# Mod (`mod/src/ResoniteIO/`): `ResoniteIOPlugin` (OnEngineReady で SessionHost 起動、SafeShutdown で partial-failure / ProcessExit を統合) / `Bridge/FrooxEngine<Modality>Bridge`
- Python (`python/src/resoio/`): モダリティごとに `<Modality>Client` (`SessionClient` / `CameraClient` / `SpeakerClient` / `MicrophoneClient` / `LocomotionClient`) と `_socket.py` / `_generated/`
- CLI (`python/src/resoio/cli/`): action 名 flat command (`resoio ping` / `record` / `mic` / `locomotion` / `display`)。subgroup 階層化はしない。`record` は `--video` / `--audio` の filter フラグ (両方未指定で muxed mp4/mkv) で Camera/Speaker を取得する Resonite→Python 方向、`mic` は Microphone を Python→Resonite に流す独立コマンド
- proto: `proto/resonite_io/v1/{session,camera,locomotion,speaker,microphone,display}.proto`
- UDS path: 本番 gRPC IPC は `$HOME/.resonite-io/`、debug bridge は `$HOME/.resonite-io-debug/`

リポジトリ実構造:

```text
resonite-io/
├── Dockerfile / docker-compose.yml / justfile / .env.example / buf.yaml
├── resonite_io_plan.md        # 全体計画書 (Step 0〜8、決定事項、リスク)
├── proto/resonite_io/v1/      # *.proto (single source of truth)
├── mod/                       # C# 側 (.NET 10、Core/Mod 二層)
│   ├── src/ResoniteIO.Core/   # pure library (Resonite 非依存)
│   ├── src/ResoniteIO/        # BepInEx adapter (engine bridging のみ)
│   └── tests/                 # Core.Tests (Kestrel ラウンドトリップ) / Tests (smoke) / manual/
├── python/                    # Python 側 (uv + betterproto2 + grpclib)
│   └── src/resoio/            # Client 群 + cli/ + _generated/
├── scripts/                   # gen_proto / decompile / host_agent / resonite_cli
├── gale/                      # Gale (Resonite mod manager) profile (gitignore)
├── decompiled/                # ILSpy 出力 (gitignore)
└── .claude/                   # memory/ + agent-memory/ + skills/ + agents/
```

## ツーリング

- タスクランナー: **`just`** (`set dotenv-load := true` で `.env` から `ResonitePath` 等を読む)。ビルド / テスト / gen-proto は **コンテナ内で実行する前提**
- C# (mod): **.NET 10 SDK** + BepisLoader 公式 Template (`dotnet new bep6resonite`) 準拠。フォーマッタ `csharpier`、配布 `tcli` (`.config/dotnet-tools.json` の local tool)。テスト `xunit`、`Nullable=enable` + `TreatWarningsAsErrors=true`
- Python (resoio): **`uv`** + Python `>=3.12`。gRPC は **`betterproto2[grpclib]`** (async)。`pyright` strict、`ruff` (line-length 88、ダブルクォート、isort + combine-as-imports)、`pytest` + `pytest-asyncio`/`pytest-cov`/`pytest-mock`
- proto: C# 側は csproj の `<Protobuf>` で `dotnet build` 時に自動生成 (Server スタブのみ、commit しない)。Python 側は `just gen-proto` で `python/src/resoio/_generated/` に書き、**commit する**。lint は `buf` (`SERVICE_SUFFIX` / `RPC_REQUEST_STANDARD_NAME` / `RPC_RESPONSE_STANDARD_NAME` を except)
- Docker 開発環境: `debian:bookworm-slim` ベースの単一 image に .NET / uv / protoc / dotnet local tools / pre-commit を同梱。詳細セットアップは [setup-resonite-env skill](.claude/skills/setup-resonite-env/SKILL.md) 参照

## コマンド

`just` レシピが C# / Python / proto をまたぐ作業をラップする。主要レシピ:

| レシピ                                                  | 役割                                                                                   |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `just run`                                              | `format` → `gen-proto` → `build` → `test` → `type` を直列実行 (コミット前の必須 check) |
| `just gen-proto`                                        | `.proto` から Python 側コードを生成 (C# 側は csproj が build-time 生成)                |
| `just deploy-mod`                                       | mod build + `gale/BepInEx/plugins/ResoniteIO/` へ DLL+PDB 配置                         |
| `just log`                                              | host 側で `gale/BepInEx/LogOutput.log` を tail -F (print-debug の主経路)               |
| `just decompile`                                        | Resonite first-party DLL を ILSpy で `decompiled/` に展開                              |
| `just container-{build,up,init,shell,down,clean}`       | Docker 環境の操作 (`up` 時に `~/.resonite-io{,-debug}/` を 0700 で事前作成)            |
| `just check-gale`                                       | Gale プロファイルに必須 plugin が揃っているか検証                                      |
| `just host-agent` / `just resonite-{start,stop,status}` | container ↔ host Resonite 起動・停止 bridge (debug 用)                                 |

全レシピは `just --list` で取得可能。サブコマンド分離 (`just py-test` / `just mod-build` 等) は troubleshooting 時のフォールバック。

**`.proto` を変更した場合は必ず `just gen-proto` を再実行し、生成物の差分も同じ commit に含める** (CI で再生成 diff を取るチェックを入れる予定)。

## 実行環境

**ホスト側に必要なものは `docker` / `docker compose v2` / `just` の 3 つだけ**。.NET / uv / protoc / pre-commit はすべてコンテナ内に閉じている。Resonite 自体は host で起動 (Steam)、コンテナは build / deploy 専用。`.env` の `ResonitePath` に Resonite 実行ファイルディレクトリ絶対パスを指定。

初回環境構築 (Docker / Gale プロファイル / Steam Launch Options) と debug 経路 (`just log` / `just decompile` / container ↔ host bridge) の詳細は専用 skill に集約済み:

- 初回セットアップ: [setup-resonite-env skill](.claude/skills/setup-resonite-env/SKILL.md)
- デバッグ手順: [debug-resonite-mod skill](.claude/skills/debug-resonite-mod/SKILL.md)

ライセンス・ToS: Resonite は明示的な研究用 bot 規定なし。慣習的には黙認〜歓迎 (詳細は [resonite_io_plan.md](resonite_io_plan.md) §7)。商用化や派手な公開実験を始める前にユーザーに確認する。

## コーディング規約とテスト方針

各モダリティは他のモダリティに依存しない (片方だけ使う構成も可)。グローバルな clock / barrier は持たず、各ストリームに **タイムスタンプ** を付与し、必要な同期は受信側で行う。通信データ型は **pyright strict をクリアする型付け**。

C# / Python の詳細な規約 (名前空間、Core/Mod 責務、Bridge engine thread dispatch、`Nullable` / warnings-as-errors、private prefix + `__all__`、proto 命名 except 等) と **テスト方針** (基本原則・gRPC in-process round-trip・Kestrel テストパターン) は [add-new-modality skill](.claude/skills/add-new-modality/SKILL.md) に集約。新規モダリティ追加時はこの skill を必ず参照する。

## Git 運用

### ブランチ

- `main`: 開発の主軸
- 作業用ブランチの命名規則: `<種別>/<日付>/<内容>` (例: `feature/20260509/grpc-skeleton`、`fix/20260509/uds-permission`)
  - 種別: `feature`, `fix`, `refactor`, `docs`, `chore`
- 必ずブランチ上で commit する (`main` に直接 commit しない)。作業ブランチは `main` から分岐
- `main` へのマージはユーザーが判断・実行する

### コミットメッセージ

`<種別>(<スコープ>): <内容>` の形式に従う。

- 種別: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- スコープ: `mod`, `python`, `proto`, `scripts`, `ci`, `docs` などの top-level、または `mod/camera`、`python/locomotion` のようなモダリティ単位
- 例: `feat(mod/session): UDS gRPC server をエンジン起動時に bind` / `feat(python/camera): server-streaming で RGB フレームを受信`

## 自走開発フロー

### 基本サイクル

1. **要件確認**: [resonite_io_plan.md](resonite_io_plan.md) の該当 Step を読み、スコープと未解決事項を把握する
2. **作業ブランチ作成**: `main` から `<種別>/<日付>/<内容>` で分岐
3. **作業はコンテナ内で行う** (`just container-shell` で attach。ビルド/テスト/gen-proto はすべてコンテナ内)
4. **実装**: コードを書く (C# / Python / proto)
5. **検証**: proto 変更時は `just gen-proto` を再実行。**コミット前に必ず `just run` を実行する** (全パス green)
6. **コミット**: 細かい単位で、1 コミットに複数の関心事を混ぜない
7. 4-6 を機能単位で繰り返す

### 判断基準

- plan に明記されている内容はそのまま実装する
- plan に記載がない実装の詳細は自分で判断してよい
- plan の未決事項に関わる部分は、合理的なデフォルトで実装し、コミットメッセージに判断理由を記載
- 型チェックエラー (pyright strict / C# warnings-as-errors) を放置しない
- スコープ外 (RL `step()`、マルチエージェント、ワールド作者向け API 等) は実装しない

## エージェントチーム戦略

「エージェントチームで行う」という指示があり具体的な手順が示されていない場合、以下のサイクルに従う。利用可能なエージェントは [.claude/agents/](.claude/agents/) のもの。

1. **spec-planner**: 要件を分析し、インターフェース設計と実装計画を策定する (コードは書かない)
2. **spec-driven-implementer → code-quality-reviewer**: 計画に基づき実装し、リファクタリング。品質が十分になるまで繰り返す
3. **docstring-author**: 最後にコメント・ドキュメントの追加・更新が必要か確認する

変更規模に応じて並列に実行 (モダリティが独立しているので Camera と Locomotion を別 implementer に投げる等)。
