---
name: resonite-linux-native-engine
description: Resonite on Linux runs the engine natively (.NET, IsWine=false); only the renderer runs under Wine/Proton. Engine PIDs are real host Linux PIDs, but pgrep -f Resonite.exe matches the Steam/Proton wrappers, not the engine.
metadata:
  type: reference
---

Linux 上の Resonite は **engine と renderer でランタイムが分かれている** (2026-06-13 に
`resoio info` の `is_wine=false` 実測 + `decompiled/FrooxEngine/FrooxEngine/RenderSystem.cs`
精読 + e2e 実測で確定)。設計判断に効くので固定知識として残す。

## 事実

- **engine プロセス (`Resonite.exe`) はネイティブ Linux .NET** で動く。`Engine.IsWine == false`。
- **renderer プロセス (`Renderite.Renderer.exe`) のみ Wine/Proton** (Unity ビルドが Windows-only)。
- engine は renderer を **ネイティブ Linux .NET の `System.Diagnostics.Process`** として起動する
  (`RenderSystem.cs`: `RendererPath = AppPath/Renderer/Renderite.Renderer.exe`)。
  `RenderSystem.RendererProcess.Id` が取れる。

## e2e 実測 (host PID との突き合わせ)

`resoio info` (engine 自己申告) と host-agent の `pgrep` 結果を突き合わせた:

- `info.renderer_pid` == host `pgrep -f Renderite.Renderer.exe` の PID と **完全一致**。
  → Info の `renderer_pid` (= `RenderSystem.RendererProcess.Id`) は本物の host Linux PID。
- `info.resonite_pid` (= `Environment.ProcessId`) は engine の本物の host PID だが、
  **`pgrep -f Resonite.exe` には出ない**。`pgrep -f Resonite.exe` がヒットするのは
  Steam/Proton の **launch wrapper 群** (reaper / pressure-vessel / srt-bwrap など、cmdline に
  "Resonite.exe" を含むだけ)。実 engine プロセスの cmdline には "Resonite.exe" が無い。

## 帰結 (PID と終了の扱い)

- engine PID は **Info からのみ** 取得する。`pgrep -f Resonite.exe` で engine を探す/kill するのは
  **誤りかつ危険** (触ってはいけない Steam reaper / pressure-vessel をヒットする)。
- `ServerInfo` に `resonite_pid` (=`Environment.ProcessId`) と `renderer_pid`
  (=`RenderSystem.RendererProcess?.Id ?? 0`) を持たせる (どちらも host PID)。`info` は RPC なので
  container からでも取れる。
- `resoio shutdown` は **`Lifecycle.Shutdown` (graceful) のみ**。SIGTERM/SIGKILL のシグナル
  エスカレーションは持たない: engine が `Engine.RequestShutdown` で自分で終了し、Steam/Proton が
  renderer と launch wrapper を自動回収する (e2e で host status が running=False になるのを確認)。
  純 gRPC なので host-native 制約も無く container からも動く。`shutdown` は engine PID
  (Info 由来) を報告のために返すだけ。**旧名 `terminate` は deprecated** (2026-06-14): CLI /
  `resoio.terminate` ともに `shutdown` に forward しつつ警告を出すだけのエイリアスで、メンテ
  対象外・将来削除予定。新規利用は `shutdown` を使う。

> 注意: 「engine も Wine だから `Environment.ProcessId` は Wine 側 PID で使えない」は **誤り**
> (engine はネイティブ Linux)。一方で「engine を `pgrep -f Resonite.exe` で見つけられる」も **誤り**
> (それは wrapper 群)。どちらの罠も踏みやすいので注意。

関連: \[\[resonite-modding-wiki\]\] / \[\[pressure-vessel-paths\]\] / `RenderSystem.cs` (decompiled)。
