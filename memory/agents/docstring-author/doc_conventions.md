---
name: resonite-io doc conventions
description: Docstring/XML-doc conventions discovered while documenting resonite-io (language split, mkdocstrings rendering gotcha, cross-ref role style)
type: project
---

Documentation conventions observed in resonite-io (verified 2026-06-10):

- **Language split**: Python docstrings are English (Google style,
  `docstring_style: google` in mkdocs.yml). C# XML docs in
  `mod/src/ResoniteIO.Core/` and `mod/src/ResoniteIO/` are **Japanese**
  (e.g. `Connection/IConnectionBridge.cs`). Match each side's language.
- **mkdocstrings rendering gotcha**: `docs/api/<modality>.md` pages use
  **per-symbol** `::: resoio.<module>.<Symbol>` directives only — module
  docstrings are NOT rendered on the site. Design rationale that must
  reach docs readers has to live in a rendered symbol's docstring, not
  only the module docstring. Page symbol list must match the package
  `__all__` in `python/src/resoio/__init__.py` (module-level `__all__`
  may be wider, e.g. `info.fetch_server_info` is module-public but not
  package-public, hence not on the page).
- **Cross-ref roles**: docstrings use Sphinx-ish `:class:`/`:func:`/
  `:mod:` roles throughout (e.g. speaker.py). mkdocstrings does not
  resolve them as links, but it is the established style — match it,
  do not "fix" project-wide.
- **Recurring why-patterns worth keeping in docs**: Info modality is
  module-level functions (not a `Client`) because the once-per-process
  version probe in `_client._maybe_warn_version_mismatch` runs before
  any client is usable; Info's 4 values are fixed at OnEngineReady
  (`DetectWine()` completes inside `Engine.Initialize`), so bridges
  snapshot once in ctor and need no engine dispatch.
- **Admonitions in docs/**: `!!!` bodies keep 4-space indent by hand —
  `docs/` is excluded from mdformat; `just docs-build --strict` is the
  gate (write-docs skill).
