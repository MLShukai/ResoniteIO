---
name: froox-in-param-lvalue
description: FrooxEngine の in-param API (GlobalDirectionToLocal 等) には float3.Up 等の static property を直接渡せず、ローカル変数で受けてから渡す必要がある
metadata:
  type: reference
---

FrooxEngine の `Slot.GlobalDirectionToLocal(in float3)` のような `in` パラメータを取る API には、`float3.Up` / `float3.Forward` / `float3.Right` などの static property を **直接渡せない** (CS8156: by-ref 不可)。一旦 `var worldUp = float3.Up;` のようにローカル変数で受けてから `GlobalDirectionToLocal(in worldUp)` に渡す。

**Why:** static property は値を返すため lvalue でなく、`in` (readonly ref) には渡せない。`viewRot * float3.Forward` のような演算結果も同様に一旦ローカルに置く必要がある。

**How to apply:** `FrooxEngineLocomotionBridge.ApplyToEngine` の `worldForward`/`worldRight`/`worldUp` ローカルはこの制約由来で、冗長ではない。レビューで「ローカル変数が不要」と判定しないこと。新規モダリティ Bridge で `in` API を使う際は同じパターンを踏襲する。命名は `world<Axis>` (slot 変換後は `slot<Axis>`) で揃える。
