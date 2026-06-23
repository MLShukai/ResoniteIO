"""Tests for the ``resoio launch`` CLI command.

The happy path (spawning umu-run and PID-diffing a real Resonite into
existence) needs a live Resonite and lives in the e2e suite
(``tests/e2e/launcher.py``). Here we pin the CLI contract: the error path
(a missing exe renders :class:`resoio.launcher.LauncherError` to stderr and
exits 1, triggered with a real missing path) and the argparse-to-call plumbing
for ``--prefix`` / ``--proton-path`` (verified by stubbing our own first-party
``launch`` and capturing the kwargs it was called with).
"""

from __future__ import annotations

import pytest

from resoio.cli import _amain, _build_parser


async def test_launch_missing_exe_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("RESONITE_EXE", "/nonexistent/Resonite.exe")
    rc = await _amain(_build_parser().parse_args(["launch"]))
    assert rc == 1
    assert "not found" in capsys.readouterr().err


async def test_launch_forwards_prefix_and_proton_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    # Plumbing pin: --prefix / --proton-path on the CLI must reach launch() as
    # prefix= / proton_path=. We stub our own first-party launch() to capture the
    # kwargs so the argparse-to-call wiring is exercised in isolation (the real
    # launch behaviour is covered in test_launcher.py against real processes).
    captured: dict[str, object] = {}

    def _fake_launch(**kwargs: object):
        captured.update(kwargs)
        from resoio.launcher import LaunchResult

        return LaunchResult(resonite_pid=11, renderer_pid=22)

    monkeypatch.setattr("resoio.launcher.launch", _fake_launch)
    args = _build_parser().parse_args(
        ["launch", "--vanilla", "--prefix", "/tmp/pfx", "--proton-path", "GE-Latest"]
    )
    rc = await _amain(args)

    assert rc == 0
    assert captured["prefix"] == "/tmp/pfx"
    assert captured["proton_path"] == "GE-Latest"


async def test_launch_passes_none_when_prefix_and_proton_path_unset(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    # Without the flags, launch() receives prefix=None / proton_path=None so it
    # falls back to umu's defaults / PROTONPATH env.
    captured: dict[str, object] = {}

    def _fake_launch(**kwargs: object):
        captured.update(kwargs)
        from resoio.launcher import LaunchResult

        return LaunchResult(resonite_pid=11, renderer_pid=22)

    monkeypatch.setattr("resoio.launcher.launch", _fake_launch)
    args = _build_parser().parse_args(["launch", "--vanilla"])
    rc = await _amain(args)

    assert rc == 0
    assert captured["prefix"] is None
    assert captured["proton_path"] is None
