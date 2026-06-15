---
name: betterproto-test-traps
description: Two recurring traps when writing resoio Python tests over real UDS grpclib round-trips (betterproto2 falsy messages, float32 wire precision)
metadata:
  type: feedback
---

Two traps that surface when verifying proto values over the real UDS
round-trip in `python/tests/resoio/` (the `uds_server` fixture harness),
not in isolated proto construction. Both cost a debug cycle if not known.

**1. An all-default betterproto2 message is falsy.**
In a recording fake's `__init__`, never write `self._x = arg or default`
for a proto message argument. A protobuf message with every field at its
zero/default value (e.g. `SessionSettings(access_level=UNSPECIFIED)`,
which is enum value 0 + all empty strings/zeros) evaluates falsy, so
`arg or default` silently replaces the caller's deliberate "all zeros"
snapshot with the default — masking the exact edge case under test (this
hid a `get_settings(UNSPECIFIED)` rejection test). Use explicit
`arg if arg is not None else default`.

**Why:** \[\[don't repeat - this is a betterproto2 behaviour\]\] betterproto2
messages define `__bool__` via field emptiness, unlike normal dataclasses.
**How to apply:** every fake servicer constructor in tests that accepts an
optional proto message/list arg — use `is None` checks, never truthiness.

**2. proto `float` is 32-bit; pick wire-exact values in equality asserts.**
proto3 `float` (not `double`) is single precision. A value like `0.8`
survives a real serialize/deserialize as `0.800000011920929`, so a
dataclass `==` assertion against `0.8` fails — the test ends up asserting
float precision, not the field mapping. Use values exactly representable
in float32 (`0.5`, `12.5`, `7.0`, `90.0`, integers, powers of two and
their halves) for any `float` field checked by equality over the wire.
Resoio float fields seen so far: `SessionUser.local_volume`,
`SessionSettings.away_kick_minutes` / `*_interval_*`,
`LocomotionCommand.*`, `Display.max_fps`.
**How to apply:** when a real-UDS test asserts equality on a proto `float`
field, choose a float32-exact literal (or assert with `pytest.approx`).
