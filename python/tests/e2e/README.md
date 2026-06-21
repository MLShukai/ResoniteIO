# E2E tests (live Resonite)

These tests exercise the full stack against an actual running Resonite
client. They are **excluded from default pytest collection** (see
`pyproject.toml`: `addopts = ["--ignore=tests/e2e"]`) and only execute
when explicitly targeted.

## Prerequisites

Run everything from inside the dev container.

1. **Mod deployed to `./gale`:**

   ```bash
   just deploy-mod
   ```

   The `resonite_session` fixture boots Resonite from the `./gale` Gale
   profile via `resoio.launch` (the launcher Python API), so the `ResoniteIO`
   mod (BepInEx + plugin) must be present there. The `require_mod_deployed`
   autouse fixture skips with a clear message when `./gale/BepInEx` is absent.

2. **Resonite installed** and the in-container launch prerequisites met
   (host graphical session + PipeWire/PulseAudio, AppArmor userns relaxation,
   `.env`'s `ResonitePath`). `just init` walks through the host-side
   preconditions; see the setup-resonite-env skill for details.

## Run

From the dev container:

```bash
just e2e-test               # run every e2e file (default)
just e2e-test connection    # run only tests/e2e/connection.py
```

The recipe forwards to `pytest -m e2e` with `--override-ini='python_files=*.py'`
so files in `tests/e2e/` do not need the `test_` prefix. Each scenario lives
in its own `<name>.py` to keep the run target self-describing.

The `resonite_session` fixture (`conftest.py`) owns the lifecycle and
`connection.py` exercises it:

- `resoio.launch` (`python/src/resoio/launcher.py`): boots Resonite in the
  container via umu-run + hookfxr loading the mod from `./gale`, and blocks
  until the engine + renderer host PIDs appear (up to 120 s).
- `wait_for_ready` polls `Connection.Ping` on `~/.resonite-io/resonite-*.sock`
  until the mod binds the UDS and answers.
- Waits 30 s after readiness so the focused home world can finish
  loading before a scenario starts.
- Calls `Connection.Ping("e2e-smoke")` once via `ConnectionClient`.
- `resoio.terminate` of the launched PIDs in `finally:` so Resonite is
  stopped even on failure.

If the mod is not deployed to `./gale`, the test will skip with a clear
message.

## Scope (Step 2)

Only one smoke case is implemented. Continuous pings, error paths
(stopping Resonite mid-call, missing mod), and multi-modality tests
land in later Steps.
