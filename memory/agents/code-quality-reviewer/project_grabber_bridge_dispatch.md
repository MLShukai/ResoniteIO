---
name: grabber-bridge-dispatch-pattern
description: FrooxEngine*Bridge RPC methods share a "resolve world → marshal to engine → resolve per-hand handles" prologue that is a safe DRY target
metadata:
  type: project
---

`FrooxEngine<Modality>Bridge` の各 RPC public メソッドは、ほぼ必ず
`ResolveWorld().RunOnEngineAsync(() => { var world = ResolveWorld(); ...resolve handles...; body }, ct)`
という同形プロローグを持つ。Grabber では 7 メソッド全てがこの形だった。

**Why:** engine thread への one-shot marshal (`EngineDispatch.RunOnEngineAsync`) と、
engine thread 上での per-hand handle 解決 (`ResolveHand`) が全 RPC 共通の前段だから。

**How to apply:** body だけを `Func<World, ..., T>` で受け取る private helper
(例: Grabber の `RunWithHandAsync`) に集約すると clutter が大きく減り、
public API / 振る舞いは不変のまま。helper 内で world を 1 回だけ解決して body に
渡せば、旧コードにあった `ResolveHand(ResolveWorld(), hand)` の二重解決も消える
(同 engine pass 内なので挙動同一)。他モダリティの bridge でも同型の集約が効くはず。

注意: hold-repeater 系 (`_holdGeneration == generation` で running フラグを
下ろすガード) は 3 箇所に重複するが、全箇所が `_holdLock` 保持下のインライン 1 行で、
helper 化すると lock 前提が fragile になり可読性も落ちるため**集約しない**判断をした。
