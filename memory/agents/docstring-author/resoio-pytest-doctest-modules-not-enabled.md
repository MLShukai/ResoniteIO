---
name: resoio-pytest-doctest-modules-not-enabled
description: This project's pytest addopts do NOT include --doctest-modules; doctests in src/ files are not auto-collected by default, contrary to the AGENTS.md harness preset.
metadata:
  type: project
---

`python/pyproject.toml` `[tool.pytest.ini_options].addopts` is just
`["--color=yes", "--durations=0", "--strict-markers"]` and `testpaths`
is `tests/resoio`. As of 2026-05-21, `--doctest-modules` is NOT in
the default invocation (`uv run pytest --no-cov -q`).

**Why:** The harness-level AGENTS.md mentions "pytest --doctest-modules
is enabled — meaning every `>>>` doctest example will be executed",
but that is the harness-wide assumption. In this repo doctests are
not auto-run.

**How to apply:** Doctests are still safe to add (and idiomatic for
small pure helpers like `_video_pts_from_nanos`), but do not rely on
them executing as part of the normal test run unless you also add
`--doctest-modules` to addopts or to a dedicated `just` recipe. If
you write a doctest, verify the math by hand because no CI gate will
catch a typo.
