---
name: debug-resonite-mod
description: "Use when debugging resonite-io mod runtime — adding logs, decompiling Resonite DLLs, starting/stopping Resonite from container, tailing BepInEx logs. Triggers: 'just log', 'just decompile', 'host-agent', 'Resonite を起動', 'Resonite を停止', 'BepInEx LogOutput', 'AssemblyLoadContext', 'mod の挙動を確認', 'TypeLoadException', 'Renderer の挙動'."
version: 0.1.0
---

# Debug Resonite-IO Mod

mod は Resonite (host プロセス) に in-process でロードされるため、container 内から直接 attach する経路はない。基本戦略は **print-debug + ログ tailing**。

______________________________________________________________________

## 1. ログ追従 (print-debug の主経路)

- C# 側は `ResoniteIOPlugin.Log` (BepInEx `ManualLogSource`) から `LogInfo` / `LogDebug` 等を出す
- 出力先: Gale 経由起動時 **`gale/BepInEx/LogOutput.log`** (プロファイル側)
- host 側で `just log` を別ターミナルで走らせ、`tail -F` で追従 (Resonite 再起動・ログローテーションを跨いで再 attach)
- Python 側は通常の `logging` でクライアント側の挙動を確認

`.NET debugger attach` (host IDE → Resonite プロセス) は必要になった時に整備する (print-debug + `just log` で多くは足りる)。PDB は `deploy-mod` 時に DLL と一緒に配置済みなのでシンボル解決の前提は満たしている。

______________________________________________________________________

## 2. Renderite IPC のドキュメント不足対策 (decompile)

Camera readback など Renderite 周辺の実装は **decompile を読みながら**進める前提:

- `just decompile` で `decompiled/` 配下に Resonite first-party DLL を ILSpy (`ilspycmd`) で project 形式に展開できる (gitignore 済み)
- Renderite Unity DLL も対象に含まれる
- `.env` の `ResonitePath` 必須
- 手探りで判った仕様はコメントではなく `memory/feedback_*.md` に残すこと

______________________________________________________________________

## 3. Container → Host bridge (Resonite start/stop)

container 内 shell から host の Resonite を Gale 経由で起動・停止する debug 経路。print-debug (`just log`) と並ぶ二本目の debug 経路。

- **host 側**: GUI session の端末で `just host-agent` を foreground 常駐させる
  - **gale CLI は `--no-gui` 指定時もディスプレイを要求する** ため、SSH only / TTY only セッションでは起動できない (Python 内で DISPLAY/WAYLAND_DISPLAY を検査して fail-fast する)
  - Ctrl+C で停止、socket は自動 unlink
- **container 側**:
  - `just resonite-start [--profile NAME]` で起動
  - `just resonite-stop` で停止 (`Resonite.exe` / `Renderite.Renderer.exe` を SIGTERM → 3 秒待ち → SIGKILL の二段構え)
  - `just resonite-status` で実行状態を JSON 表示
- **設定**: `.env` の `GaleProfile=<name>` を既定 profile に使う (`--profile` で都度 override 可)。`gale` バイナリが PATH 上に無い場合 (AppImage 等) は `.env` の `GaleBin=/abs/path/to/Gale.AppImage` で絶対パス指定
- **トランスポート**: 本番 gRPC IPC の `$HOME/.resonite-io/` とは分離した `$HOME/.resonite-io-debug/host-agent.sock` を使う (両方とも pressure-vessel が通す `$HOME` 配下を採用)。mod 側 socket 探索ロジック (`resonite-*.sock`) と命名衝突しない設計
- **kill 範囲**: 名前ベース pkill のみで Proton / pressure-vessel / reaper は触らない (Steam セッションを壊さないため Steam reaper の自走回収に委ねる)

______________________________________________________________________

## 4. 典型的な debug シナリオ

### `TypeLoadException` / `MissingMethodException` が出る

`Google.Protobuf` 3.15+ API (`UnsafeByteOperations` 等) を Core 側で使うと、Resonite 同梱の 3.11.4 と衝突して TypeLoadException で死ぬ。`PluginAssemblyResolver` でも救えないケースあり。詳細: [`feedback_protobuf_3_11_4_in_resonite.md`](../../../memory/feedback_protobuf_3_11_4_in_resonite.md)

### Camera v2 / Renderer 側 plugin が load されない

- まず Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%` が入っているか確認 (これが無いと Renderer 側 BepInEx は起動しない)
- `gale/Renderer/BepInEx/LogOutput.log` を確認 (Renderer 側ログは engine 側と別ファイル)
- InterprocessLib の callback signature は `Action<T[]?>` で、namespace は DLL 名と独立して `InterprocessLib`。static event は Dispose で必ず `-=`。詳細: [`feedback_interprocesslib_callback_signature.md`](../../../memory/feedback_interprocesslib_callback_signature.md)

### mod がそもそも load されない

- `just check-gale` で必須 plugin 6 個 (+ BepInExRenderer framework) を確認
- `gale/BepInEx/plugins/ResoniteIO/` に DLL + PDB が居るか
- Vanilla 起動 (Steam 直起動) になっていないか — Gale 経由でなければ mod は読まれない
- 詳細な setup 周りは `setup-resonite-env` skill 参照

### Camera readback / Renderite の挙動が不明

`just decompile` で `decompiled/` を生成し、Renderite Unity DLL を直接読む。
詳細な制約集約は [`feedback_camera_v2_constraints.md`](../../../memory/feedback_camera_v2_constraints.md)。

______________________________________________________________________

## 5. 関連 memory

- [`feedback_protobuf_3_11_4_in_resonite.md`](../../../memory/feedback_protobuf_3_11_4_in_resonite.md) — Resonite 同梱 Google.Protobuf 3.11.4 制約
- [`feedback_interprocesslib_callback_signature.md`](../../../memory/feedback_interprocesslib_callback_signature.md) — InterprocessLib の使い方と event 解除
- [`feedback_camera_v2_constraints.md`](../../../memory/feedback_camera_v2_constraints.md) — Camera v2 全般の制約集約
- [`reference_resonite_modding.md`](../../../memory/reference_resonite_modding.md) — BepisLoader 関連 URL マップ
