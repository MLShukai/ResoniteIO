---
name: session-bridge-no-proto-change
description: Step 2 で ISessionBridge を導入する際、Ping proto は変更せず Bridge を Plugin 側のログ出力に閉じた判断
metadata:
  type: feedback
---

# Session.Ping proto を変更せず Bridge をログ出力に閉じる

Step 2 で `ISessionBridge` を Core 側 (`ResoniteIO.Core.Bridge`) に追加し、
`FrooxEngineSessionBridge` を Mod 側に実装したが、`Session.Ping` proto / RPC 自体は
**変更しなかった**。`PingResponse` に `FocusedWorldName` / `LocalUserName` を載せていない。

**Why:**
Ping RPC は「socket 越しに mod が生きていることの確認 + 時刻 echo」が責務で、世界状態の
取得は別 RPC (将来の `Session.GetState` 等) に切り出すべき。proto を変更すると Python 側
の生成物 commit、`SessionClient.ping` 返り値型、`SessionRoundTripTests`、`test_session_ping_e2e.py`
の assertion まで波及するが、Step 2 のスコープ (Bridge 注入の足場作り + FocusedWorld/LocalUser
の Console ログ出力) には不要なコスト。`SessionHost.Start` に optional
`ISessionBridge? bridge = null` 引数だけ追加し DI 登録の口だけ作って、Service 側は
今は consume しない。将来 `Session.GetState` を追加する際に `SessionService` ctor へ
Bridge を後付け DI すれば proto 拡張 + Bridge 消費を同時に踏める。

**How to apply:**
モダリティ単位で新しい Bridge IF を導入するとき (Step 3+ の Camera / Locomotion 等)、
最初の Step では IF 定義 + Plugin での DI 登録 + 最低限の engine 状態ログ出力に閉じ、
proto 拡張 (Response にフィールドを増やす等) は Service が実際にそのデータを返す段になって
からまとめて行う。proto 拡張の波及範囲を測ってから判断する習慣を維持する。

## 関連

- \[\[worldmanager-world-focused\]\]: Bridge が露出する FocusedWorld / LocalUser の取得経路
- \[\[core-mod-layering\]\]: Bridge IF は Core、engine 実装は Mod
