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

**`_dispatch` arity varies legitimately by modality — do not flag the wider one as over-abstraction.**
context_menu.py uses 1-arg `_dispatch(rpc) -> State` (hardcoded decoder) because all its RPCs
return one dataclass. grabber.py uses 2-arg `_dispatch(rpc, decode)` because grab→GrabResult
while release/get_state→GrabState; the generic `decode` param is the minimal way to keep a single
not-connected guard across mixed return types. Single-return-type clients → 1-arg; mixed → 2-arg.

Other non-findings confirmed clean on grabber.py/cli/manipulate.py (2026-06-06 review, no
changes made): the `pb.<msg> is not None else <Pb>()` guard on optional message fields (betterproto2
`optional=True`, e.g. GrabberGrabResult.state) is REQUIRED for pyright strict, not dead code.
`_hand_to_proto`/`_hand_from_proto`/`_state_from_proto`/`_result_from_proto` decode distinct
directions/messages and must NOT be merged. The interactive CLI's `_raw_tty` cbreak helper is an
intentional minimal local copy of locomotion.py's (not shared via a util module) — accepted pattern,
not a DRY violation. Single-line vs parenthesized imports in `__init__.py` that fit 88 cols are
taste-only (ruff won't wrap) — leave alone.
