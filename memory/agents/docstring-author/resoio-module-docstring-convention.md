---
name: resoio-module-docstring-convention
description: Standard first-line + body shape for python/src/resoio/<modality>.py module docstrings (role + direction + RPC form)
metadata:
  type: feedback
---

Every `python/src/resoio/<modality>.py` module docstring should open with
one line of the shape:

`"""Client for the Resonite IO `\`<Modality>`\` modality (<direction>)."""\`

where `<direction>` is one of `Resonite -> Python` (server-streaming
sources: Camera, Speaker), `Python -> Resonite` (client-streaming or
unary control: Microphone, Locomotion, Grabber, ContextMenu, Cursor,
Dash, Inventory, World), or omitted-but-implied for the bidirectional
Connection modality.

After a blank line, add a short body line naming the **RPC form**
(server-streaming / client-streaming / unary) plus a one-clause role.
Keep it to ~2 lines; don't lengthen modules that already carry rich
bodies (Microphone / Locomotion have detailed bridge-mechanism prose
below the standard opener — insert the role+RPC line above it, leave the
rest).

**Why:** the public docs site (MkDocs Material + mkdocstrings,
`docstring_style: google`) renders these module docstrings as API-page
intros. Before the 2026-06-09 pass the granularity was inconsistent
(some 1-line, some bridge-detailed), so direction/RPC-form was the
agreed normalizing axis.

**How to apply:** when a new modality is added or an existing module
docstring is touched, conform to this opener. Direction + RPC form is
the minimum bar; do not pad beyond that.

Related: \[\[resoio-pytest-doctest-modules-not-enabled\]\]. Load-bearing
WHY comments under `python/src/resoio/` (e.g. the mono/stereo wire-format
const comments) are catalogued in `reference_load_bearing_whys.md` and
must survive trim passes.
