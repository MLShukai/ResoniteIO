---
name: e2e-harness-collection
description: How to verify a new python/tests/e2e/<modality>.py harness without a live Resonite, and the bare-pytest hang gotcha
metadata:
  type: feedback
---

When authoring a new `python/tests/e2e/<modality>.py` harness, verify it
WITHOUT triggering a real Resonite launch.

**Why:** Running `pytest tests/e2e/<file>.py` bare appears to hang in the
container. The `require_mod_deployed` autouse fixture (in
`python/tests/e2e/conftest.py`) DOES skip when the mod is not deployed to
`./gale` (no `BepInEx` dir), but combined with `log_cli = true` (pyproject)
the invocation can stall before/around the skip rather than returning
promptly. Do not wait on it.

**How to apply:**

- Validate the harness with `pytest tests/e2e/<file>.py --collect-only -q`
  (returns fast, proves no import/collection error) plus a plain
  `python -c "from resoio.<modality> import ..."` to prove every imported
  public symbol resolves.
- Never execute the e2e scenario yourself — the orchestrator runs it
  against live Resonite via `just e2e-test` (which overrides the
  `python_files` pattern to collect non-`test_*.py` files; that is why
  e2e files are named `<modality>.py`, not `test_<modality>.py`, and stay
  out of default collection).
- Mirror `python/tests/e2e/context_menu.py`: `@mark_e2e` from
  `tests.helpers`, `resonite_session` fixture, and the shared screenshot
  helper (in-engine Camera capture via `CameraClient.shot()`, the same
  path as the `resoio screenshot` CLI — the host-side desktop pyscreenshot
  bridge was removed), artifacts under `python/tests/e2e/e2e_artifacts/`, a
  FAILED_PRECONDITION readiness poll, and a `_HOME_LOAD_SETTLE_S` wait
  before the first screenshot.
