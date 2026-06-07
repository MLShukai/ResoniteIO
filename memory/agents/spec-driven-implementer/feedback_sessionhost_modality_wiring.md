---
name: sessionhost-modality-wiring
description: The 4 disjoint edit points in GrpcHost.cs needed to wire a new modality
type: feedback
---

Wiring a new modality into `mod/src/ResoniteIO.Core/Hosting/GrpcHost.cs` requires exactly 4 surgical edits, all mirroring the existing modalities:

**Why:** GrpcHost aggregates every modality's gRPC service onto one UDS endpoint; missing one of these silently drops the modality.

**How to apply:** When adding modality `<X>` (bridge `I<X>Bridge`, service `<X>Service`):

1. `using ResoniteIO.Core.<X>;` (alphabetical with other modality usings)
2. Add `I<X>Bridge? <x>Bridge = null` as the LAST param of `Start(...)` (after the prior bridges)
3. `if (<x>Bridge is not null) builder.Services.AddSingleton(<x>Bridge);` next to the other AddSingleton bridge registrations (before ConfigureKestrel)
4. `app.MapGrpcService<<X>Service>();` in the MapGrpcService block
5. Per-modality null-warning: `if (<x>Bridge is null) log.LogWarning("<X> modality is not configured.");` in the warning block after listen.

(That's effectively 5 spots, but 3+5 are the registration pair.) The pattern is uniform across Connection/Camera/Display/Locomotion/Speaker/Microphone.
