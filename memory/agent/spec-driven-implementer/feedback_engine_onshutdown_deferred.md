---
name: engine-onshutdown-deferred
description: BepInEx 6 BasePlugin に Unload 相当が無いため、mod 停止は AppDomain.ProcessExit で best-effort。Engine.OnShutdown 調査は Step 3 でも未着手で先送り継続中。
metadata:
  type: feedback
---

ResoniteIO mod の Session gRPC server (Core 側 `SessionHost`) と Camera Bridge の停止は、
現状 **`AppDomain.ProcessExit` 一本** で best-effort cleanup を行っている
(`SessionHost.cs:121` で `processExitHandler` を attach、`ResoniteIOPlugin.cs:80` でも
`OnProcessExit` を attach)。これは plan §7 リスク欄「`BasePlugin` に Unload 相当が無い」
と整合する暫定実装。

**Why:** BepInEx 6 の `BasePlugin` には mod 終了時 hook が無い。FrooxEngine 側
の `Engine.OnShutdown` 系 API がより早く graceful に Kestrel を畳めるなら
そちらを購読すべきだが、Step 2 ではここに時間をかけず `AppDomain.ProcessExit`
で先に進む決定をし、**Step 3 (Camera) でも調査せず先送りした** (Camera 実装と E2E
スケジュール優先)。SIGKILL されたら socket file は残るが、`SessionHost.Start` が
bind 直前に stale socket を `File.Delete` するので次回起動時には自動回復する。
Camera Bridge 側も `FrooxEngineCameraBridge.cs:288` で「engine shutdown 後の
RunSynchronously は no-op になり例外を飲む」と明示しており、ProcessExit 経由で
畳めれば問題ない設計になっている。

**How to apply:** Step 4 (Locomotion) 着手時 (または engine shutdown 起因の不具合が
出たとき) に以下を確認する:

1. `just decompile` 出力で `FrooxEngine.Engine.OnShutdown` 相当のイベントが
   公開されているかを `decompiled/FrooxEngine/` で検索 (`OnShutdown`,
   `Shutdown`, `Disposing`, `OnEnginePreShutdown` 等)。
2. あれば `ResoniteHooks` が wrap している可能性も確認 (`BepInExResoniteShim`
   側の decompile)。なければ自前で event を hook する必要がある。
3. graceful shutdown が確認できたら `OnEngineReady` で `Engine.OnShutdown +=`
   を仕掛け、`AppDomain.ProcessExit` は二次防衛に降格する。
4. \[\[grpc-tools-message-duplication\]\] は Step 2 で確立済みなので、新規モダリ
   ティ proto を追加するときの NoWarn 規約は維持する。
