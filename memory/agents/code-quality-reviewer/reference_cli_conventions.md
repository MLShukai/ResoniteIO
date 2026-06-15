---
name: cli-conventions
description: resoio CLI (python/src/resoio/cli/) handler + output conventions used to judge new command modules during review
type: reference
---

resoio CLI handler conventions (anchor when reviewing a new `cli/<modality>.py`):

- Each handler is `async def _run_*(args) -> int`; heavy imports (grpclib, AuthClient, prompt_toolkit) are deferred inside the handler so `resoio --help` stays fast.
- Result rendering goes through `resoio.cli.output`: `output.is_structured(args.format)` -> `output.emit(payload, fmt)`; else the command's own human `print` path. `--format` is attached only to result-producing leaves via `output.build_format_parent()` (nested) or `output.add_format_argument` (top-level), never the common parent.
- GRPCError handling is per-handler and inconsistent across modules: `info.py`/`mic.py`/`drive.py` catch GRPCError and print a clean `error: ...`/`resoio X: ...` line to stderr + return 1; some handlers let it propagate. There is NO shared GRPCError->stderr helper. When reviewing, a handler that lets GRPCError propagate to a traceback is a UX wart but matches some existing modules — flag as low/medium, not a hard bug.
- `--format json` output MUST be exactly one parseable JSON document on stdout (tests do `json.loads(capsys...out)`). Any `print(...)`/`input(prompt)` that writes to stdout on a code path reachable under `--format json` corrupts that contract. `input(prompt)` writes the prompt to STDOUT (not stderr).
- Exit codes seen: 0 ok, 1 runtime/RPC failure, 2 usage / bad input, 130 KeyboardInterrupt (top-level in cli/__init__.py).
