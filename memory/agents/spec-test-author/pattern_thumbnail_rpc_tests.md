---
name: pattern-thumbnail-rpc-tests
description: Recurring shape for testing a <Modality>Client.fetch_thumbnail unary RPC over real in-process UDS gRPC, mirroring the World client tests
metadata:
  type: feedback
---

When a modality gains a `fetch_thumbnail` unary RPC returning image bytes + content_type, the canonical test shape is the one in `python/tests/resoio/test_world.py::TestFetchThumbnail`. Mirror it for the new modality.

**Why:** thumbnail RPCs all share the same contract (an id/uri/path arg travels verbatim on the wire; response carries `data: bytes` + `content_type: str`; empty content_type is allowed and must surface verbatim, not coerced). Reusing the proven shape keeps tests spec-faithful and consistent.

**How to apply:**

- Parameterize the fake's constructor with a `thumbnail_response: <Pb>ThumbnailResponse | None = None` kwarg (default to an empty generated response), record incoming requests in a `fetch_thumbnail_requests: list[...]` list, and return the canned response from the `async def fetch_thumbnail` handler. The generated `<Modality>Base` already exposes the `fetch_thumbnail` servicer slot, so grpclib wires it over the real UDS — no mocking.
- Three tests: (1) bytes + content_type round-trip AND the id arg arrives verbatim on the wire (use realistic bytes `b"RIFF\x00\x00\x00\x00WEBPVP8 "` + `"image/webp"`); (2) empty content_type surfaces verbatim with returned bytes; (3) raises RuntimeError matching "not connected" when used outside the client's async context.
- If the client converts the generated response into a public frozen dataclass (e.g. Inventory's `InventoryThumbnail(data, content_type)`), assert equality against that dataclass; if it returns the generated response directly (e.g. World), assert `isinstance(resp, <Pb>ThumbnailResponse)` + field values.
- Use the shared `uds_server` fixture from `python/tests/conftest.py` (real `grpclib.server.Server` on a `tmp_path` UDS). Per testing-strategy: no return type annotations on test functions; build the fake first, then `await uds_server(fake)`.
