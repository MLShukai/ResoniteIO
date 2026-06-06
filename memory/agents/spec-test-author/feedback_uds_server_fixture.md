---
name: uds-server-fixture
description: Shared python/tests/conftest.py uds_server factory fixture for grpclib end-to-end client tests, and the IServable typing gotcha
metadata:
  type: feedback
---

`python/tests/conftest.py` provides a shared `uds_server` async factory
fixture for the canonical "grpclib end-to-end round-trip" harness. Prefer
it over hand-rolled `Server([fake])` + `monkeypatch.setenv` + try/finally
in each `test_<modality>.py`.

Shape: `socket_path = await uds_server(fake_servicer)` (returns the socket
path str; sets `RESONITE_IO_SOCKET`; closes server + unlinks socket on
teardown via tmp_path). It is a factory so the test builds its fake first
(often configured per-test) then brings the server up.

**Why a factory, not a plain fixture:** fakes are configured per-test
(constructor args, response protos, fail-on-index), so the test must own
fake construction. Factory also supports >1 server per test if ever needed.

**How to apply / gotchas:**

- Only capture the return value when the test asserts
  `client.socket_path == socket_path`; otherwise just `await uds_server(fake)`
  (a bare `socket_path = await ...` triggers ruff F841 unused-variable).
- `grpclib.Server([...])` accepts `IServable`, but that type lives in the
  PRIVATE `grpclib._typing` module (TYPE_CHECKING-only; `from grpclib.server import IServable` fails at runtime). Type the fixture/param
  with a `TYPE_CHECKING`-guarded import and a module-level
  `UdsServer = Callable[["IServable"], Awaitable[str]]` alias. This keeps
  pyright strict-clean without importing 3rd-party internals at runtime.
- Tests that exercise socket *discovery* (SocketNotFound / Ambiguous) need
  raw `tmp_path` + `monkeypatch` (they set `RESONITE_IO_SOCKET_DIR`, never
  start a server) — do NOT migrate those to `uds_server`.
- Mechanical bulk migration of N uniform try/finally blocks: a Python regex
  with DOTALL capturing the try-body, then de-denting each body line by 4
  spaces, is reliable. Watch for outlier tests (a local fake subclass
  defined between the preamble and `fake = ...`, or a configured-fake
  preamble) that the regex misses — fix those by hand.

**Migrated to uds_server (B-2, 2026-06-06):** test_session (1 of 3),
test_camera, test_speaker, test_microphone, test_locomotion, test_display,
test_inventory, test_manipulation, test_world, test_context_menu, test_dash.
**Left alone:** cli/test_record.py (B-3) — its server interleaves with a
running CLI record loop (concurrency) and uses `type[CameraBase]` factory
funcs, so the simple `async with client` teardown timing does not match;
not worth the behavior-change risk.
