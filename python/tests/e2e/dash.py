"""E2E: drive the Dash modality against a live Resonite and screenshot.

Exercises the full closed loop on the real Esc dash (userspace overlay):
open -> introspect the UI tree (language-independent ``ref_id`` + ``locale_key``
per element) -> operate elements by ``ref_id`` (invoke / highlight / scroll)
-> close. Each step is followed by a host-side desktop screenshot via the
host-agent (``scripts/resonite_cli.py screenshot``) since the dash is a
local-user overlay an in-world Camera would not capture.

Open/close is driven as a symmetric ``close -> open -> close -> open`` so a
real toggle is distinguishable from a no-op on an already-open dash.

Note on the localization goal: ``ref_id`` (engine RefID) and ``locale_key``
(LocaleStringDriver key) are asserted to be present and to stay stable across
two introspection snapshots. Confirming they are *identical* under a different
UI language requires switching Resonite's locale (a manual follow-up), but
their language-independence is structural: neither derives from the displayed
``label``.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from datetime import datetime
from pathlib import Path

import grpclib
from grpclib.const import Status

from resoio.dash import DashClient, DashElement, DashTree
from tests.helpers import mark_e2e

# parents[2] is python/; the repo root (where scripts/ lives) is parents[3].
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# UDS bind and UserspaceRadiantDash readiness race: while the engine is still
# booting, the Dash bridge raises DashNotReadyException -> FAILED_PRECONDITION.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0

# The bridge becomes ready before the home world has finished loading; give it
# time to settle so the desktop is fully rendered before driving the dash.
_HOME_LOAD_SETTLE_S = 20.0

# Let the dash open/close lerp finish and the renderer present a frame before
# grabbing the desktop, so screenshots are not torn mid-animation.
_SETTLE_S = 0.6


def _screenshot(out_dir: Path, name: str) -> None:
    """Grab the host desktop into ``out_dir/name`` via the host-agent
    bridge."""
    path = out_dir / name
    subprocess.run(
        ["python3", "scripts/resonite_cli.py", "screenshot", "--output", str(path)],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=30.0,
    )


def _format_tree(tree: DashTree) -> str:
    lines = [
        f"screen={tree.screen_width}x{tree.screen_height} count={len(tree.elements)}"
    ]
    for e in tree.elements:
        lines.append(
            f"  [{e.ref_id}] {e.type} locale={e.locale_key!r} label={e.label!r} "
            f"enabled={e.enabled} interactable={e.interactable}"
        )
    return "\n".join(lines)


class TestDash:
    @mark_e2e
    def test_open_introspect_operate_close(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"dash_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "states.txt"
        log_lines: list[str] = []

        def record(step: str, text: str) -> None:
            block = f"=== {step} ===\n{text}"
            log_lines.append(block)
            print(block)

        async def wait_for_ready() -> bool:
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while True:
                try:
                    async with DashClient() as dash:
                        return (await dash.get_state()).is_open
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            f"Dash bridge never became ready within {_READY_TIMEOUT_S:.0f}s"
                        ) from e
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def settle_shot(step: str) -> None:
            await asyncio.sleep(_SETTLE_S)
            _screenshot(out_dir, f"{step}.png")

        async def scenario() -> None:
            # 0. baseline: engine ready, dash closed. Let the home world settle.
            await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            await wait_for_ready()

            async with DashClient() as dash:
                # 1. symmetric close -> open -> close -> open so a real toggle is
                #    distinguishable from a no-op on an already-open dash.
                await dash.close()
                s_closed = await dash.get_state()
                record("00_closed", f"is_open={s_closed.is_open}")
                await settle_shot("00_closed")
                assert not s_closed.is_open, "dash should be closed"

                opened = await dash.open()
                record(
                    "01_open", f"is_open={opened.is_open} open_lerp={opened.open_lerp}"
                )
                await settle_shot("01_open")
                assert opened.is_open, "dash should be open after open()"

                await dash.close()
                assert not (await dash.get_state()).is_open
                reopened = await dash.open()
                record("02_reopen", f"is_open={reopened.is_open}")
                await settle_shot("02_reopen")
                assert reopened.is_open

                # 2. introspect the dash UI tree. Every element must carry a
                #    language-independent ref_id; at least one should expose a
                #    locale_key (the dash chrome is localized).
                tree = await dash.get_tree()
                record("03_tree", _format_tree(tree))
                await settle_shot("03_tree")
                assert tree.elements, "open dash should expose UI elements"
                assert all(e.ref_id for e in tree.elements), (
                    "every element needs a ref_id"
                )
                assert any(e.locale_key for e in tree.elements), (
                    "at least one element should carry a language-independent locale_key"
                )

                # ref_id / locale_key are stable across snapshots (not derived
                # from transient layout or the displayed label).
                tree2 = await dash.get_tree()
                keys1 = {(e.ref_id, e.locale_key) for e in tree.elements}
                keys2 = {(e.ref_id, e.locale_key) for e in tree2.elements}
                assert keys1 & keys2, (
                    "ref_id/locale_key should be stable across snapshots"
                )

                # 3. operate an interactable element by ref_id (language-independent).
                interactable = await dash.get_tree(interactable_only=True)
                record("04_interactable", _format_tree(interactable))
                target: DashElement | None = next(iter(interactable.elements), None)
                if target is not None:
                    highlighted = await dash.highlight(target.ref_id)
                    record(
                        "05_highlight",
                        f"ok={highlighted.ok} found={highlighted.found} "
                        f"ref_id={target.ref_id} detail={highlighted.detail!r}",
                    )
                    await settle_shot("05_highlight")
                    assert highlighted.found, "highlight target should resolve"

                    invoked = await dash.invoke(target.ref_id)
                    record(
                        "06_invoke",
                        f"ok={invoked.ok} found={invoked.found} detail={invoked.detail!r}",
                    )
                    await settle_shot("06_invoke")
                    assert invoked.found, "invoke target should resolve"

                # 4. close, leaving a clean state for the next run.
                await dash.close()
                final = await dash.get_state()
                record("07_closed", f"is_open={final.is_open}")
                await settle_shot("07_closed")
                assert not final.is_open, "dash should be closed after close()"

        try:
            asyncio.run(scenario())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
