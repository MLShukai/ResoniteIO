# Changelog

このファイルはプロジェクトのリリースノート。`v*` tag の publish 時に
`.github/workflows/publish.yml` が `## [X.Y.Z]` セクションを抽出して GitHub Release
本文にする。形式は [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) に従う。

## [Unreleased]

## [0.1.0] - 2026-06-07

最初の公開リリース。Resonite を AI エージェントの実行環境として使うための双方向 IPC
ブリッジ (C# Mod `ResoniteIO` ↔ Python パッケージ `resoio`、gRPC over Unix Domain
Socket) の基盤一式。

### Added

- **IPC 基盤**: gRPC over Unix Domain Socket による双方向ブリッジ。本番 IPC は
  `$HOME/.resonite-io/`、debug bridge は `$HOME/.resonite-io-debug/` の UDS を使用
- **C# Core/Mod 二層アーキテクチャ**: Resonite 非依存のピュアライブラリ
  `ResoniteIO.Core` (gRPC server / Service / 各モダリティのドメインロジック) と、
  engine bridging のみを担う薄い BepInEx adapter `ResoniteIO` (BepisLoader) に分離。
  依存方向は Core ← Mod
- **モダリティ群** (各モダリティは独立した非同期ストリーム): `Session` (Ping) /
  `Camera` (server-streaming RGB フレーム) / `Speaker` (server-streaming 音声、
  Resonite → Python) / `Microphone` (client-streaming 音声、Python → Resonite) /
  `Locomotion` (client-streaming) / `Manipulation` (Grab/Release unary) /
  `Display` / `World` / `ContextMenu` / `Dash` / `Inventory` /
  `Cursor` (desktop カーソルを正規化座標で set/get)
- **Python パッケージ `resoio`**: モダリティ単位の async クライアント
  (`SessionClient` / `CameraClient` / `SpeakerClient` / `MicrophoneClient` /
  `LocomotionClient` / `ManipulationClient` / `DisplayClient` / `WorldClient` /
  `ContextMenuClient` / `DashClient` / `InventoryClient` / `CursorClient`)。
  betterproto2 + grpclib ベース、pyright strict 準拠
- **CLI `resoio`**: action 名 flat command (`ping` / `record` / `mic` /
  `locomotion` / `manipulate` / `display` / `world` / `context-menu` / `dash` /
  `inventory` / `cursor`)。`record` は `--video` / `--audio` フィルタで
  Camera/Speaker を mp4/mkv 取得、`mic` は Microphone を Resonite に流す
- **proto 定義**: `proto/resonite_io/v1/` を single source of truth とし、Python 側
  生成物を commit、C# 側は csproj が build-time 生成
- **開発環境**: `debian:bookworm-slim` ベースの devcontainer
  (`compose.yml` / `.devcontainer/`)、`justfile` タスクランナー、container ↔ host
  Resonite bridge スクリプト (`scripts/host_agent.py` / `scripts/resonite_cli.py`)
- **CI / リリース / ドキュメント**: GitHub Actions の品質ゲート
  (`pre-commit` / `test` / `type-check` / `dotnet` / `proto-check`)、`v*` tag 駆動で
  Thunderstore mod + PyPI パッケージを同時公開する `publish.yml`、mike による
  バージョン付きドキュメントサイト (MkDocs Material)

[0.1.0]: https://github.com/MLShukai/ResoniteIO/releases/tag/v0.1.0
[unreleased]: https://github.com/MLShukai/ResoniteIO/compare/v0.1.0...HEAD
