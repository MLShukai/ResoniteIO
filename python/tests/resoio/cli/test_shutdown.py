"""Tests for the ``resoio shutdown`` CLI command.

The command's real behaviour (read the engine PID from Info, send
``Lifecycle.Shutdown``) is covered by ``test_lifecycle.py`` against a real
grpclib server. Here we only pin the CLI dispatch contract: it drives
``resoio.lifecycle.shutdown`` and renders the result — ``resonite_pid=<pid>``
on success, ``resonite not running`` when no engine was reachable. We stub our
own first-party ``shutdown`` so the dispatch is exercised in isolation.
"""

import pytest

from resoio.cli import _amain, _build_parser


async def test_shutdown_prints_pid_on_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    async def _fake_shutdown(*, socket_path: str | None) -> int:
        return 4242

    monkeypatch.setattr("resoio.lifecycle.shutdown", _fake_shutdown)
    args = _build_parser().parse_args(["shutdown"])
    rc = await _amain(args)

    assert rc == 0
    assert capsys.readouterr().out.strip() == "resonite_pid=4242"


async def test_shutdown_reports_nothing_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    async def _fake_shutdown(*, socket_path: str | None) -> None:
        return None

    monkeypatch.setattr("resoio.lifecycle.shutdown", _fake_shutdown)
    args = _build_parser().parse_args(["shutdown"])
    rc = await _amain(args)

    assert rc == 0
    assert capsys.readouterr().out.strip() == "resonite not running"
