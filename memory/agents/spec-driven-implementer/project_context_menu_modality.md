---
name: context-menu-modality
description: ContextMenu modality (Step 6-ish) — unary RPC modality mirroring Display, added to resonite-io
type: project
---

ContextMenu is a unary request/response modality mirroring the Display modality template.

**Why:** Lets AI agents drive Resonite's radial (T-key) context menu over gRPC/UDS — open/close/get-state/highlight/invoke.

**How to apply:** When extending or touching ContextMenu Core code, mirror Display, not the streaming modalities (Camera/Speaker/Microphone/Locomotion).

Key facts:

- Generated gRPC base: `ResoniteIO.V1.ContextMenu.ContextMenuBase`; messages in `ResoniteIO.V1` (referenced as `V1.*` from `ResoniteIO.Core.*` files — no explicit `using ResoniteIO;` needed since they share the `ResoniteIO` root).
- proto enum `ContextMenuHand`: UNSPECIFIED=0, PRIMARY=1, LEFT=2, RIGHT=3 → C# `Unspecified/Primary/Left/Right`. Core selector `ContextMenuHandSelector` has only Primary/Left/Right; UNSPECIFIED+PRIMARY both map to Primary.
- Service exception mapping: ContextMenuNotReadyException→FailedPrecondition, ArgumentOutOfRangeException(bad index)→InvalidArgument, null bridge→Unavailable, other→Internal. Pass context.CancellationToken to bridge calls.
- Mod-side Open requires reflection on private `InteractionHandler.OpenContextMenu(MenuOptions.Default)`; enumerate/highlight/invoke/close are all public API.
