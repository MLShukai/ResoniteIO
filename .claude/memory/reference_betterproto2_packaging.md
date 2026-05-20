---
name: betterproto2 packaging quirk
description: betterproto2 has no [compiler] extra; the compiler is a separate distribution
type: reference
---

On PyPI as of 2026-05, `betterproto2` does NOT expose a `[compiler]` extra. The protoc plugin ships as a separate distribution named `betterproto2_compiler`.

**How to apply:**

- In `pyproject.toml`, list `betterproto2[grpclib]` in runtime deps and `betterproto2_compiler` in the dev group — never `betterproto2[compiler]`.
- In `scripts/gen_proto.sh`, `uv run --with 'betterproto2[compiler]' -- protoc ...` is suspicious (likely a no-op extra). Prefer adding `betterproto2_compiler` to the dev group and invoking `uv run protoc ...` directly, since `protoc-gen-python_betterproto2` is shipped by the compiler distribution.
