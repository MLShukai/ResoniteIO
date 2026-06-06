---
name: world-service-translate-pattern
description: WorldService (and same-shape modality Services) repeat per-RPC try/catch→exception-translation; unify with a private CallBridgeAsync wrapper
type: feedback
---

C# Core `<Modality>Service` overrides (e.g. `WorldService`) tend to repeat per-RPC:
`RequireBridge(rpc)` → build query/target → `try { await bridge.Xxx() } catch (Exception ex) { throw Translate(rpc, ex, ctx); }`.

**Refactor:** collapse into one private generic helper
`Task<T> CallBridgeAsync<T>(string rpc, ServerCallContext ctx, Func<IWorldBridge, CancellationToken, Task<T>> call)`
that does the null-bridge `Unavailable` throw + the try/catch translation in one place. For void-returning RPCs (e.g. `Leave`), return a throwaway `bool` from the lambda.

**Why:** the 8 RPCs each had identical 6-line try/catch blocks. One wrapper removed ~50 lines without touching any public/`internal` API (overrides, ctor, POCOs, enums all pinned by `WorldServiceTests`/`ApiContractTests` — do not edit tests).

**How to apply:** preserve the client-cancel passthrough exactly. Original code re-threw the original exception when `ex is OperationCanceledException or IOException && ct.IsCancellationRequested`. Reproduce with an exception filter on the catch (`when (ex is not (OperationCanceledException or IOException) || !ctx.CancellationToken.IsCancellationRequested)`) so the original exception propagates untranslated — keep `Translate` only mapping NotReady→FailedPrecondition / NotFound→NotFound / else→Internal. Keep `#pragma warning disable CA1031`.

In the matching `FrooxEngine<Modality>Bridge`, the two engine-dispatch helpers also dedup: implement `RunOnEngineTaskAsync(Func<Task>)` as `await (await RunOnEngineAsync(fn, ct))` instead of copying the TCS/RunSynchronously/ct.Register block.

SessionHost per-modality DI/MapGrpcService/null-warning blocks repeat across ALL modalities — do NOT extract a World-only helper there; that's a cross-modality change out of a single-modality refactor's scope.
