---
name: modality-client-class-contracts
description: In python/src/resoio modality clients, cross-cutting contracts (targeting, permissions, statelessness) belong on the class/module docstring, not repeated per method.
metadata:
  type: feedback
---

In `python/src/resoio/<modality>.py`, contracts shared across several methods
are stated **once** on the `<Modality>Client` class docstring or the module
docstring — not duplicated into each method docstring.

Examples observed:

- `InventoryClient`: "stateless and path-based" + recursive-flag rules on the
  module docstring; per-method docstrings are one-liners.
- `WorldClient`: `_require_world` protocol-violation note centralizes the
  "missing field is a bug, not a signal" contract.
- `SessionClient`: the user-targeting precedence (`local=True` -> self, else
  `user_id` first, `user_name` fallback, ambiguous-name fails) and the
  host-gated-writes-raise-`PermissionDenied` contract live on the class
  docstring, since `kick`/`ban`/`silence`/`respawn`/`set_user_role` all share
  them.

**Why:** Repeating the same paragraph on five methods is noise; mkdocstrings
renders the class docstring above the methods, so readers see it once. The
per-method docstring then only needs the bit unique to that method.

**How to apply:** Before adding the same caveat to multiple methods, hoist it
to the class or module docstring. Keep method docstrings to the one-liner that
states intent unique to that call. C# analogue: \[\[csharp-override-doc-altitude\]\].
