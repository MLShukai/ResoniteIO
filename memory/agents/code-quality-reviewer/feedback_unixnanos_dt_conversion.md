---
name: unixnanos-dt-conversion-duplication
description: DateTime->unix-nanos conversion is reimplemented per-bridge with diverging precision; flag drift on new bridges
metadata:
  type: feedback
---

Mod-side bridges that emit `*UnixNanos` from a `DateTime` each hand-roll the same conversion, and they have drifted.

- `FrooxEngineWorldBridge.ToUnixNanos(DateTime)` and `FrooxEngineInventoryBridge.ToUnixNanos(DateTime)` both use ticks (`(utcTicks - UnixEpoch.Ticks) * 100L`), i.e. 100ns resolution, and clamp/guard negatives.
- `FrooxEngineAuthBridge.ReadStatus()` (Auth modality, added 2026-06) inlines a *different* version: `new DateTimeOffset(dt.ToUniversalTime()).ToUnixTimeMilliseconds() * 1_000_000L` — only millisecond resolution, and handles `DateTimeKind.Unspecified` differently (SpecifyKind Utc only for Unspecified, else ToUniversalTime via the DateTimeOffset ctor).
- Core has `UnixNanosClock.Now()` for "now" but no shared DateTime->nanos converter.

**Why:** Each bridge reaches into engine `DateTime` values independently; no shared helper existed, so each implementer rewrote it. The Auth one is lossier and subtly different.

**How to apply:** When reviewing a new/edited mod bridge that converts a `DateTime` to unix nanos, check it against the World/Inventory tick-based form. The clean fix (Core\<-Mod-safe, all internal) is a single `internal static` helper (e.g. in a Mod-side util or Core `UnixNanosClock.FromUtc(DateTime)`) reused by all three. Until then, at minimum flag precision/Kind divergence. Wire format (`int64` nanos) is unaffected so this is wire-safe.
