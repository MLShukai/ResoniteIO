"""Tests for the ``screenshot`` subcommand of ``scripts/resonite_cli.py``.

container 側 CLI が:
- subparser を正しく登録し ``--output`` を required にしている
- output / monitor / bbox を host_agent への request dict に正しく組み立てる
- 不正な ``--output`` / ``--bbox`` を fail-fast (exit 2) で弾く
- host_agent からの response を stdout に表示し ok=true なら exit 0 を返す
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import resonite_cli  # pyright: ignore[reportMissingImports]


def test_parser_screenshot_requires_output(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        resonite_cli._parse_args(["screenshot"])
    err = capsys.readouterr().err
    assert "--output" in err


def test_parser_screenshot_default_monitor_is_1() -> None:
    ns = resonite_cli._parse_args(["screenshot", "--output", "tmp/a.png"])
    assert ns.action == "screenshot"
    assert ns.output == "tmp/a.png"
    assert ns.monitor == 1
    assert ns.bbox is None


def test_parser_screenshot_accepts_monitor_and_bbox() -> None:
    ns = resonite_cli._parse_args(
        ["screenshot", "--output", "a.png", "--monitor", "0", "--bbox", "10,20,100,50"]
    )
    assert ns.output == "a.png"
    assert ns.monitor == 0
    assert ns.bbox == "10,20,100,50"


@pytest.mark.parametrize(
    "bad",
    [
        "/abs.png",
        "../escape.png",
        "tmp/../etc.png",
        "weird*.png",
        "has space.png",
        "",
    ],
)
def test_validate_screenshot_output_rejects_invalid(bad: str) -> None:
    with pytest.raises(SystemExit) as exc:
        resonite_cli._validate_screenshot_output(bad)
    assert exc.value.code == resonite_cli.EXIT_USAGE


def test_validate_screenshot_output_accepts_repo_relative() -> None:
    assert resonite_cli._validate_screenshot_output("tmp/e2e/x.png") == "tmp/e2e/x.png"


@pytest.mark.parametrize(
    "bad",
    [
        "1,2,3",
        "1,2,3,foo",
        "",
        "1, 2",
    ],
)
def test_parse_bbox_arg_rejects_invalid(bad: str) -> None:
    with pytest.raises(SystemExit) as exc:
        resonite_cli._parse_bbox_arg(bad)
    assert exc.value.code == resonite_cli.EXIT_USAGE


def test_parse_bbox_arg_none() -> None:
    assert resonite_cli._parse_bbox_arg(None) is None


def test_parse_bbox_arg_strips_whitespace() -> None:
    assert resonite_cli._parse_bbox_arg("10, 20 ,100 , 50") == [10, 20, 100, 50]


def test_main_sends_correct_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Main() が組み立てる host_agent 向け request dict を検証する。"""
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()  # exists() を通すためのダミー (実際の send は mock)
    captured: dict[str, Any] = {}

    def _fake_send(socket_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        captured["socket"] = socket_path
        captured["request"] = request
        return {
            "ok": True,
            "action": "screenshot",
            "data": {
                "path": request["output"],
                "width": 1920,
                "height": 1080,
                "monitor": request["monitor"],
            },
        }

    monkeypatch.setattr(resonite_cli, "_send_request", _fake_send)

    rc = resonite_cli.main(
        [
            "--socket",
            str(sock_path),
            "screenshot",
            "--output",
            "tmp/desktop.png",
            "--monitor",
            "1",
            "--bbox",
            "0,0,640,480",
        ]
    )

    assert rc == 0
    assert captured["socket"] == sock_path
    assert captured["request"] == {
        "action": "screenshot",
        "output": "tmp/desktop.png",
        "monitor": 1,
        "bbox": [0, 0, 640, 480],
    }
    out = capsys.readouterr().out
    assert json.loads(out)["ok"] is True


def test_main_returns_nonzero_when_response_not_ok(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()

    def _fake_send(socket_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "action": "screenshot",
            "error": "capture_failed",
            "detail": "X server unreachable",
        }

    monkeypatch.setattr(resonite_cli, "_send_request", _fake_send)

    rc = resonite_cli.main(
        ["--socket", str(sock_path), "screenshot", "--output", "tmp/x.png"]
    )
    assert rc == resonite_cli.EXIT_ACTION_FAILED


def test_main_screenshot_omits_bbox_when_unset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()
    captured: dict[str, Any] = {}

    def _fake_send(socket_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        captured["request"] = request
        return {"ok": True, "action": "screenshot", "data": {}}

    monkeypatch.setattr(resonite_cli, "_send_request", _fake_send)

    resonite_cli.main(
        ["--socket", str(sock_path), "screenshot", "--output", "tmp/a.png"]
    )
    assert captured["request"]["bbox"] is None
