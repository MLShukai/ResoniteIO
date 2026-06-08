# Changelog

このファイルはプロジェクトのリリースノート。`v*` tag の publish 時に
`.github/workflows/publish.yml` が `## [X.Y.Z]` セクションを抽出して GitHub Release
本文にする。形式は [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) に従う。

## [Unreleased]

## [0.2.0] - 2026-06-08

Python クライアント `resoio` の public API を実装都合の漏れから洗練する**破壊的**
リリース。あわせて locomotion の入力モデルを部分更新方式に刷新し、視点回転 (yaw/pitch)
の実機反映バグを修正した。0.1.x からの移行には下記 Removed / Changed の API 変更への
追従が必要。

### Added

- **Python `resoio`**: top-level export に受信チャンク型 `SpeakerChunk` と、`World`
  modality の生成 proto 応答型 `ListSessionsResponse` / `ListRecordsResponse` /
  `FetchThumbnailResponse` を追加

### Changed

- **Python `resoio` Locomotion (破壊的)**: 移動入力を全 field 必須の単発コマンド
  `LocomotionCmd` から、変化した field だけを送る部分更新 `LocomotionClient.send(field=None)`
  に刷新。`None` の field は wire に乗せず Resonite 側 bridge が前回値を保持する。drive
  summary は `async with` 終了後に `drive_summary` property で取得する。基盤として proto
  `LocomotionCommand` の制御 8 field を `optional` 化 (field presence)、C# Core に
  `LocomotionPartialInput` + `MergeInto` を追加し present field のみ held state へ
  マージする方式へ変更
- **Python `resoio` Speaker (破壊的)**: 受信チャンク型 `AudioChunk` を `SpeakerChunk`
  にリネーム。定数 `CHANNELS` / `DTYPE` / `SAMPLE_RATE` を top-level export から除外
  (microphone と名前衝突するため `resoio.speaker` module-level には残置)
- **Python `resoio` Microphone (破壊的)**: ラッパ型 `MicrophoneAudioChunk` を撤去し、
  `stream()` / `paced()` が raw NumPy ndarray を直接受け取るように変更 (frame_id /
  unix_nanos はライブラリが自動管理)
- **Python `resoio` Camera (破壊的)**: `Frame.width` / `height` / `channels` を `pixels`
  由来の read-only property に変更。`stream()` から `width` / `height` / `fps_limit`
  引数を除去 (解像度設定は Display modality の責務)
- **Python `resoio` World (破壊的)**: 出力 mirror dataclass `RecordPage` / `SessionPage`
  / `Thumbnail` を撤去し、生成 proto 応答型を直接公開。入力側の enum remap (`RecordSort`
  等) は維持
- **Python `resoio` (破壊的)**: socket 例外 `AmbiguousSocketError` / `SocketNotFoundError`
  の定義元を `resoio.connection` から内部 `resoio._client` に移し top-level から
  re-export。`resoio.connection` module は `Ping` 専用に純化 (top-level の import 名は
  不変だが `from resoio.connection import AmbiguousSocketError` 等は破壊的)
- **Thunderstore mod**: 配布パッケージに `CHANGELOG.md` と `LICENSE` を同梱
- **Thunderstore mod**: publish categories を拡充 (`mods` に加えて `tools` /
  `audio` / `controls`)
- **ドキュメント**: Linux のみ対応 (Windows 非対応) を README / docs サイトに明記

### Removed

- **Python `resoio`**: top-level export から `LocomotionCmd` / `AudioChunk` /
  `MicrophoneAudioChunk` / `CHANNELS` / `DTYPE` / `SAMPLE_RATE` / `RecordPage` /
  `SessionPage` / `Thumbnail` を削除 (上記 Changed の API 刷新に伴う)

### Fixed

- **Thunderstore mod**: 配布パッケージが ASP.NET Core shared framework を丸ごと同梱して
  131 files / 24MB に膨張し (Blazor / MVC / Razor / Identity / SignalR 等の未使用 DLL を
  含む)、Thunderstore のモデレーションで「別 mod のファイル混入」と見なされ reject
  (Invalid submission) されていた問題を修正。同梱 DLL を GrpcHost (Kestrel + gRPC) の
  実依存閉包だけに絞る allow-list 方式 (`_BundledAspNetCoreDll`) に変更し、
  67 files / 4.9MB に削減 (機能・wire 互換に変更なし)
- **mod Locomotion**: 視点回転 (yaw/pitch) が cursor lock の無い間 engine に届かず
  avatar が回頭しなかった問題を修正。`ScreenCameraInputs.Look.Active` が
  `InputInterface.IsCursorLocked` に gate されるため、look 入力中だけ低 priority の
  cursor lock を内部取得して前提を満たす (入力が 0 / Dispose 時等に解放、既存の
  cursor lock は上書きしない)
- **Python `resoio` Locomotion**: `LocomotionClient.__aexit__` が drive task の例外時に
  channel close を skip して接続を leak していたのを try/finally で常時 close するよう修正

## [0.1.1] - 2026-06-07

0.1.0 公開後に判明したパッケージング不備の hotfix。配布物が動作しない 2 件を修正。

### Fixed

- **Thunderstore mod**: 配布パッケージに `ResoniteIO.dll` / `.pdb` しか含まれず、
  Core/Mod 二層の `ResoniteIO.Core.dll` や Kestrel/gRPC ランタイム DLL が欠落して
  mod がロードできなかった問題を修正。Gale deploy と同じ `@(PluginFiles)` 集合を
  staging して同梱するようにし、必須 DLL を漏れなくパッケージする
  (`StageThunderstorePlugin` target + `thunderstore.toml`)
- **Python `resonite-io`**: `pip install resonite-io` 後の `import resoio` が
  betterproto2 の version 不整合で `ImportError` になる問題を修正。runtime 依存を
  生成物の compiler と major.minor 一致させ `betterproto2[grpclib]>=0.10,<0.11` に
  固定 (compiler 0.10.1 で `_generated/` を再生成、dev も lockstep)

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
- **モダリティ群** (各モダリティは独立した非同期ストリーム): `Connection` (Ping) /
  `Camera` (server-streaming RGB フレーム) / `Speaker` (server-streaming 音声、
  Resonite → Python) / `Microphone` (client-streaming 音声、Python → Resonite) /
  `Locomotion` (client-streaming) / `Manipulation` (Grab/Release unary) /
  `Display` / `World` / `ContextMenu` / `Dash` / `Inventory` /
  `Cursor` (desktop カーソルを正規化座標で set/get)
- **Python パッケージ `resoio`**: モダリティ単位の async クライアント
  (`ConnectionClient` / `CameraClient` / `SpeakerClient` / `MicrophoneClient` /
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
[0.1.1]: https://github.com/MLShukai/ResoniteIO/compare/v0.1.0...v0.1.1
[0.2.0]: https://github.com/MLShukai/ResoniteIO/compare/v0.1.1...v0.2.0
[unreleased]: https://github.com/MLShukai/ResoniteIO/compare/v0.2.0...HEAD
