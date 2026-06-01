#!/usr/bin/env bash
# resoio CLI bash completion. Sourced from /etc/bash.bashrc inside the dev
# container. Idempotent — re-sourcing is safe and a no-op when `resoio` is not
# yet on PATH (e.g. before the devcontainer postCreateCommand runs uv sync) or when the
# argcomplete helper cannot be located.
#
# `register-python-argcomplete` ships in the project's uv-managed venv at
# /workspace/python/.venv/bin/, which is not on PATH inside non-activated
# shells. We invoke it through `uv run --project` so it stays version-pinned
# with the rest of resoio's deps.

# shellcheck disable=SC2317  # `exit 0` is the fallback when this file is run
# directly instead of sourced; shellcheck can't tell statically.
if ! command -v resoio >/dev/null 2>&1; then
  return 0 2>/dev/null || exit 0
fi
if ! command -v uv >/dev/null 2>&1; then
  return 0 2>/dev/null || exit 0
fi
if [[ ! -d /workspace/python/.venv ]]; then
  return 0 2>/dev/null || exit 0
fi
_resoio_completion="$(uv run --project /workspace/python --no-sync \
  register-python-argcomplete resoio 2>/dev/null)" || return 0 2>/dev/null || exit 0
eval "$_resoio_completion"
unset _resoio_completion
