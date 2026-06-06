# C# Mod

The C# side is documented conceptually here. Per-class C# API reference is not generated on
this site (the docs toolchain, mkdocstrings, only handles Python). For the authoritative
detail, read the source under `mod/src/` and the project design document.

## Two projects, one dependency direction

```text
mod/src/
├── ResoniteIO.Core/      # pure library — NO Resonite dependency
│   ├── <Modality>/       # I<Modality>Bridge + <Modality>Service (per modality)
│   ├── Logging/          # ILogSink (injectable sink)
│   ├── Rpc/              # BridgeFault, BridgeGuard (error handling)
│   └── UnixNanosClock    # cross-cutting clock
└── ResoniteIO/           # BepInEx plugin — engine bridging only
    ├── ResoniteIOPlugin  # starts the server on OnEngineReady; SafeShutdown
    └── Bridge/           # FrooxEngine<Modality>Bridge (per modality)
```

The rule is **Core ← Mod**: the mod references Core, never the reverse. This keeps all
protocol and domain logic in a library that builds and tests without Resonite present.

## Service / Bridge split

Each modality is a pair:

- **`<Modality>Service`** (Core) implements the generated gRPC service base. It owns proto
  mapping and the request/stream lifecycle, but knows nothing about FrooxEngine.
- **`I<Modality>Bridge`** (Core) is the seam to the engine. It is defined in terms of **Core
  POCOs**, never proto types — the service does the `MapToProto`. (A bridge returning proto
  types would make fake bridges fail to satisfy the interface.)
- **`FrooxEngine<Modality>Bridge`** (Mod) implements that interface against the live engine.

Because the seam is a plain interface over POCOs, Core tests inject a fake bridge and run a
full **Kestrel gRPC round-trip over a real UDS** — no Resonite required.

## Engine thread dispatch

FrooxEngine has thread affinity. Bridge implementations follow two rules:

- **Component-graph mutations** must run on the engine update tick — dispatched via
  `World.RunSynchronously` + a `TaskCompletionSource`.
- **Pure reads (snapshots)** may run on any thread.

## Server lifecycle and shutdown

`ResoniteIOPlugin` starts the gRPC `SessionHost` on `OnEngineReady` (on a separate thread so
the engine is never blocked) and routes both partial-failure and `AppDomain.ProcessExit`
through a single `SafeShutdown` dispose chain, stopping modalities in dependency order.

## Further reading

- Repository design document: `resonite_io_plan.md` in the repo.
- The `add-new-modality` skill in `.claude/skills/` codifies the full proto → Core → Mod →
  Python → CLI → tests workflow and the conventions above.
