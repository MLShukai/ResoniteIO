---
name: debug-resonite-mod
description: "Use when debugging resonite-io mod runtime — adding logs, decompiling Resonite DLLs, starting/stopping Resonite in the container, tailing BepInEx logs. Triggers: 'just log', 'just decompile', 'just resonite-launch', 'just resonite-stop', 'Resonite を起動', 'Resonite を停止', 'BepInEx LogOutput', 'AssemblyLoadContext', 'mod の挙動を確認', 'TypeLoadException', 'Renderer の挙動'."
version: 0.1.0
---

# Debug Resonite-IO Mod

mod は Resonite プロセスに in-process でロードされ、Resonite 自体は devcontainer 内で起動する (`just resonite-launch`)。.NET debugger attach は未整備なので、基本戦略は **print-debug + ログ tailing**。

______________________________________________________________________

## 1. ログ追従 (print-debug の主経路)

- C# 側は `ResoniteIOPlugin.Log` (BepInEx `ManualLogSource`) から `LogInfo` / `LogDebug` 等を出す
- 出力先: Gale 経由起動時 **`gale/BepInEx/LogOutput.log`** (プロファイル側)。umu/Proton 自体の起動ノイズは別ファイル `gale/BepInEx/umu-launch.log`
- container 内で `just log` を別ターミナルで走らせ、`tail -F` で追従 (Resonite 再起動・ログローテーションを跨いで再 attach)
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

## 3. container 内 Resonite control (launch/stop)

container 内で mod 込み Resonite を起動・停止する debug 経路。print-debug (`just log`) と並ぶ二本目の debug 経路。`resoio launch` / `resoio terminate` (`python/src/resoio/launcher.py`) を `just` レシピ越しに叩く。

- `just resonite-launch` で **mod 込み**を起動 (= `resoio launch`)。`MOD_PATH` の Gale プロファイル `./gale` (= `/workspace/gale`) を hookfxr + doorstop で読む。`./gale/BepInEx` が無ければ fail-fast (先に `just deploy-mod`)。engine 側は hookfxr、Renderer 側は doorstop (hook 版 `winhttp.dll`) で、`resoio launch` が `WINEDLLOVERRIDES="winhttp=n,b"` を自動 export するため Steam Launch Options の手動設定は不要 (host Steam 起動では手動設定が要る)。engine (native の `dotnet` プロセス) と renderer (`Renderite.Renderer.exe`) の両プロセスが現れるまで待ってから両 host PID を返す。既に起動中なら error (single-instance)
- `just resonite-stop` で停止 (= `resoio terminate`)。engine + renderer を psutil 経由で SIGTERM → 3 秒待ち → SIGKILL の段階 kill。engine の実体は `dotnet` プロセスで、`Resonite.exe` 名のプロセスは wine ブートストラップにすぎない
- 起動状態の確認は `pgrep -af Renderite.Renderer.exe` (renderer プロセスの有無で判定)
- mod を読まない素の起動が要るときは `just resonite-launch --vanilla` (起動確認用、setup-resonite-env skill §5 参照)
- **ログ**: mod 本体は `gale/BepInEx/LogOutput.log` (`just log`)、umu/Proton の起動ノイズは `gale/BepInEx/umu-launch.log`

______________________________________________________________________

## 4. 典型的な debug シナリオ

### `TypeLoadException` / `MissingMethodException` が出る

`Google.Protobuf` 3.15+ API (`UnsafeByteOperations` 等) を Core 側で使うと、Resonite 同梱の 3.11.4 と衝突して TypeLoadException で死ぬ。`PluginAssemblyResolver` でも救えないケースあり。詳細: [`feedback_protobuf_3_11_4_in_resonite.md`](../../memory/feedback_protobuf_3_11_4_in_resonite.md)

### Camera v2 / Renderer 側 plugin が load されない

- `WINEDLLOVERRIDES="winhttp=n,b"` は **両経路で必要** (これが無いと hook 版 `winhttp.dll` doorstop が読まれず Renderer 側 BepInEx は起動しない、2026-06-19 実機検証)。container 内 `just resonite-launch` 経路では `resoio launch` が自動で export するため手動設定は不要。host Steam 経由起動の場合のみ Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%` を手で設定する (Steam は env を sanitize するため)
- `gale/Renderer/BepInEx/LogOutput.log` を確認 (Renderer 側ログは engine 側と別ファイル)
- InterprocessLib の callback signature は `Action<T[]?>` で、namespace は DLL 名と独立して `InterprocessLib`。static event は Dispose で必ず `-=`。詳細: [`feedback_interprocesslib_callback_signature.md`](../../memory/feedback_interprocesslib_callback_signature.md)

### mod がそもそも load されない

- `just check-gale` で必須 plugin 6 個 (+ BepInExRenderer framework) を確認
- `gale/BepInEx/plugins/ResoniteIO/ResoniteIO/` に DLL + PDB が居るか (nested install layout。直下にはプロジェクトファイルが入る)
- Vanilla 起動 (`just resonite-launch --vanilla` / host Steam 直起動) になっていないか — mod 込みは `just resonite-launch` で起動する
- 詳細な setup 周りは `setup-resonite-env` skill 参照

### Camera readback / Renderite の挙動が不明

`just decompile` で `decompiled/` を生成し、Renderite Unity DLL を直接読む。
詳細な制約集約は [`feedback_camera_v2_constraints.md`](../../memory/feedback_camera_v2_constraints.md)。

______________________________________________________________________

## 5. 関連 memory

- [`feedback_protobuf_3_11_4_in_resonite.md`](../../memory/feedback_protobuf_3_11_4_in_resonite.md) — Resonite 同梱 Google.Protobuf 3.11.4 制約
- [`feedback_interprocesslib_callback_signature.md`](../../memory/feedback_interprocesslib_callback_signature.md) — InterprocessLib の使い方と event 解除
- [`feedback_camera_v2_constraints.md`](../../memory/feedback_camera_v2_constraints.md) — Camera v2 全般の制約集約
- [`reference_resonite_modding.md`](../../memory/reference_resonite_modding.md) — BepisLoader 関連 URL マップ
