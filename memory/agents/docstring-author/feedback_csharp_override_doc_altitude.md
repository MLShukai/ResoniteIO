---
name: csharp-override-doc-altitude
description: In mod/src Core Service classes, RPC override methods get no XML summary; only the class and conversion helpers are documented.
metadata:
  type: feedback
---

In `mod/src/ResoniteIO.Core/<Modality>/<Modality>Service.cs`, the public RPC
`override` methods (`GetSettings`, `KickUser`, `List`, etc.) deliberately carry
**no** `<summary>`. Only the class itself and the private conversion helpers
(`ToProto` / `ToPatch` / `ToTarget`) are documented.

**Why:** The csproj has no `GenerateDocumentationFile`, so CS1591 is not
enforced — bare overrides do not break `TreatWarningsAsErrors`. The overrides
are thin proto\<->POCO adapters whose intent is fully captured by the class
`<remarks>` (which lists the full exception-translation table) plus the
`I<Modality>Bridge` interface XML doc. `InventoryService` and `SessionService`
both follow this; adding per-override summaries would diverge from siblings.

**How to apply:** When documenting a Core Service, do not add `<summary>` to
each RPC override. Put the why (DI optionality, the exception-translation map)
on the class `<remarks>`, and document the contract on the `I<Modality>Bridge`
interface instead. See \[\[modality-client-class-contracts\]\] for the Python
analogue.
