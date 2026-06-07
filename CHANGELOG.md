# Changelog

このファイルはプロジェクトのリリースノート。`v*` tag の publish 時に
`.github/workflows/publish.yml` が `## [X.Y.Z]` セクションを抽出して GitHub Release
本文にする。形式は [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) に従う。

## \[Unreleased\]

### Added

- 最小構成の BepisLoader mod スケルトン (load 時にバージョン情報をログ出力)
- `ResoniteHooks.OnEngineReady` の購読 (Step 2 以降の配線ポイント)
