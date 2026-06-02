---
name: modality-client-dedup
description: Python modality clients (resoio) share a repeated unary-RPC body shape; how to dedup it without touching public API
type: project
---

resoio modality clients (`context_menu.py`, `display.py`, etc.) each have N near-identical
unary-RPC methods: `stub = require_stub()` -> build request -> `return _decode(await stub.X(req))`.

**Why:** betterproto2 stubs expose one method per RPC with distinct request types, so the
per-method request construction must stay inline, but the not-connected guard + proto->dataclass
decode are identical across all RPCs.

**How to apply:** when a client has >=3 such methods, extract a private `async def _dispatch(self, rpc: Callable[[Stub], Awaitable[PbState]]) -> State` that holds the `_stub is None` guard
and the decode, then call `await self._dispatch(lambda stub: stub.X(request))` from each method.
Keeps request construction explicit & per-method, removes the guard/decode duplication.
display.py has only 2 RPC methods (apply/get) -> below the abstraction threshold, leave inline.
The not-connected RuntimeError message must contain "not connected" (pinned by tests like
`test_*_raises_when_not_connected` with `match="not connected"`).
