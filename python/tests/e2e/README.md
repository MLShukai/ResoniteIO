# E2E tests (live Resonite)

These tests exercise the full stack against an actual running Resonite
client. They are **excluded from default pytest collection** (see
`pyproject.toml`: `addopts = ["--ignore=tests/e2e"]`) and only execute
when explicitly targeted.

## Prerequisites

1. **Host-agent running on host (GUI session, foreground):**

   ```bash
   just host-agent
   ```

   This brings up the debug bridge daemon (`~/.resonite-io-debug/host-agent.sock`).
   See `scripts/host_agent.py` for details.

2. **`.env` configured** with a `GaleProfile` that has BepisLoader + the
   `ResoniteIO` mod installed (`just deploy-mod` deploys the local build
   into the Gale profile).

3. **Resonite installed** (Linux native FrooxEngine + Proton-managed
   Renderite). `just init` walks through the host-side preconditions.

## Run

From the dev container:

```bash
just e2e-test               # run every e2e file (default)
just e2e-test connection    # run only tests/e2e/connection.py
```

The recipe forwards to `pytest -m e2e` with `--override-ini='python_files=*.py'`
so files in `tests/e2e/` do not need the `test_` prefix. Each scenario lives
in its own `<name>.py` to keep the run target self-describing.

`connection.py` orchestrates:

- `just resonite-start` (boots Resonite via Gale)
- Polls `~/.resonite-io/resonite-*.sock` until the mod binds the UDS
  (up to 120 s).
- Calls `Connection.Ping("e2e-smoke")` once via `ConnectionClient`.
- `just resonite-stop` in `finally:` so Resonite is stopped even on
  failure.

If host-agent is not running on host, the test will skip with a clear
message.

## Scope (Step 2)

Only one smoke case is implemented. Continuous pings, error paths
(stopping Resonite mid-call, missing mod), and multi-modality tests
land in later Steps.
