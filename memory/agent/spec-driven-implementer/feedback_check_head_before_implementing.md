---
name: check-head-before-implementing
description: Before implementing a spec, verify whether prior commits already cover the work — especially on feature branches that match the task name.
metadata:
  type: feedback
---

When given an implementation spec on a feature branch whose name matches the task (e.g., `feature/20260516/grpc-session-ping` for a Step 2 Session task), **inspect `git log` first** to see whether a prior agent run already landed the work. The spec's description of the current code ("currently placeholder") may be out of date.

**Why:** A prior run on `feature/20260516/grpc-session-ping` had already committed `SessionClient`, generated stub, and round-trip test as `eea819a feat(python/session): SessionClient と in-process UDS round-trip テスト`. The user-provided spec still described `session.py` as a placeholder. Re-implementing would have either duplicated work or fought the existing commit. Verifying first revealed that only Step 5 (pytest e2e marker + `--ignore=tests/e2e`) and Step 6 (`__init__.py` re-exports) of the spec were missing, which fit cleanly in a follow-on commit.

**How to apply:**

- On task start, run `git log --oneline -10` and `git log --all --oneline -- <key files in spec>` to see what's already there.
- If a commit matching the spec's intent already exists, compare its diff against the spec line-by-line to find the residual gaps.
- Per CLAUDE.md "create a NEW commit rather than amending" — add a follow-on commit for the gaps rather than rewriting the prior one.
- Note this in the final report so the parent agent can reconcile.
