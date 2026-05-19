"""Tests for the ``screenshot`` subcommand of ``scripts/resonite_cli.py``.

S4 protocol: PNG bytes は host_agent が base64 で response に乗せて返し、
resonite_cli が container 側 ``--output`` path に書き出す。CLI 側 path
validation は緩く、絶対 / 相対 / ``..`` を含む path も受け入れる (container
側ファイルなので host repo root 拘束は無い)。

検証範囲:
- subparser: ``--output`` required、``--bbox`` 既定 None
- ``_resolve_screenshot_output``: 空文字拒否、絶対 / 相対 / ``..`` 受容、
  ``.png`` 以外で stderr warning
- ``_parse_bbox_arg``: malformed 形式拒否、空白 strip、None pass-through
- ``main``: request 本文に ``output`` / ``monitor`` が含まれず ``bbox`` のみ
- ``_handle_screenshot_response``: base64 decode → ``--output`` への
  write、``payload_bytes`` mismatch で error、summary JSON を stdout に出す
- 任意 container path (``/tmp/...`` 等、repo 外) に書ける
- error response はそのまま JSON で表示し exit 1
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

import resonite_cli  # pyright: ignore[reportMissingImports]


# ----- parser ---------------------------------------------------------------


def test_parser_screenshot_requires_output(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        resonite_cli._parse_args(["screenshot"])
    err = capsys.readouterr().err
    assert "--output" in err


def test_parser_screenshot_default_bbox_is_none() -> None:
    ns = resonite_cli._parse_args(["screenshot", "--output", "tmp/a.png"])
    assert ns.action == "screenshot"
    assert ns.output == "tmp/a.png"
    assert ns.bbox is None


def test_parser_screenshot_accepts_bbox() -> None:
    ns = resonite_cli._parse_args(
        ["screenshot", "--output", "a.png", "--bbox", "10,20,100,50"]
    )
    assert ns.output == "a.png"
    assert ns.bbox == "10,20,100,50"


# ----- output path resolution ----------------------------------------------


def test_resolve_screenshot_output_rejects_empty() -> None:
    with pytest.raises(SystemExit) as exc:
        resonite_cli._resolve_screenshot_output("")
    assert exc.value.code == resonite_cli.EXIT_USAGE


@pytest.mark.parametrize(
    "ok_path",
    [
        "/tmp/desktop.png",  # 絶対パス (S3 で許容に変更)
        "tmp/foo.png",  # 相対パス
        "../escape/x.png",  # `..` を含む (container 側は自由)
        "/workspace/tmp/x.png",  # repo 外でも OK
        "a/b/c/d.png",
    ],
)
def test_resolve_screenshot_output_accepts_any_container_path(ok_path: str) -> None:
    path = resonite_cli._resolve_screenshot_output(ok_path)
    assert isinstance(path, Path)
    assert str(path) == ok_path


def test_resolve_screenshot_output_warns_on_non_png(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = resonite_cli._resolve_screenshot_output("tmp/no_extension")
    assert str(path) == "tmp/no_extension"
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert ".png" in err


def test_resolve_screenshot_output_no_warning_for_png(
    capsys: pytest.CaptureFixture[str],
) -> None:
    resonite_cli._resolve_screenshot_output("tmp/a.png")
    assert capsys.readouterr().err == ""


# ----- bbox parsing ---------------------------------------------------------


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


# ----- main: request body ---------------------------------------------------


_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"FAKEPAYLOAD" * 4


def _fake_screenshot_response() -> dict[str, Any]:
    return {
        "ok": True,
        "action": "screenshot",
        "data": {
            "png_b64": base64.b64encode(_FAKE_PNG).decode("ascii"),
            "width": 320,
            "height": 240,
            "payload_bytes": len(_FAKE_PNG),
        },
    }


def test_main_request_excludes_output_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """S3 protocol: request body に ``output`` フィールドは含めない。"""
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()
    captured: dict[str, Any] = {}

    def _fake_send(socket_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        captured["socket"] = socket_path
        captured["request"] = request
        return _fake_screenshot_response()

    monkeypatch.setattr(resonite_cli, "_send_request", _fake_send)

    output_path = tmp_path / "desktop.png"
    rc = resonite_cli.main(
        [
            "--socket",
            str(sock_path),
            "screenshot",
            "--output",
            str(output_path),
            "--bbox",
            "0,0,640,480",
        ]
    )

    assert rc == 0
    assert captured["socket"] == sock_path
    assert captured["request"] == {
        "action": "screenshot",
        "bbox": [0, 0, 640, 480],
    }
    # PNG が書き出されている
    assert output_path.read_bytes() == _FAKE_PNG
    # stdout の summary JSON が parse できる
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "path": str(output_path),
        "width": 320,
        "height": 240,
        "payload_bytes": len(_FAKE_PNG),
    }


def test_main_screenshot_omits_bbox_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()
    captured: dict[str, Any] = {}

    def _fake_send(socket_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        captured["request"] = request
        return _fake_screenshot_response()

    monkeypatch.setattr(resonite_cli, "_send_request", _fake_send)

    resonite_cli.main(
        [
            "--socket",
            str(sock_path),
            "screenshot",
            "--output",
            str(tmp_path / "a.png"),
        ]
    )
    assert captured["request"]["bbox"] is None
    assert "output" not in captured["request"]


# ----- main: response handling ---------------------------------------------


def test_main_writes_png_to_container_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()
    monkeypatch.setattr(
        resonite_cli, "_send_request", lambda *_: _fake_screenshot_response()
    )

    # 親 dir が存在しないケース: mkdir parents が効くこと。
    output = tmp_path / "nested" / "dirs" / "snap.png"
    rc = resonite_cli.main(
        ["--socket", str(sock_path), "screenshot", "--output", str(output)]
    )

    assert rc == 0
    assert output.read_bytes() == _FAKE_PNG


def test_main_payload_bytes_mismatch_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()

    def _bad_response(*_: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "action": "screenshot",
            "data": {
                "png_b64": base64.b64encode(_FAKE_PNG).decode("ascii"),
                "width": 320,
                "height": 240,
                "payload_bytes": len(_FAKE_PNG) + 999,  # 嘘の値
            },
        }

    monkeypatch.setattr(resonite_cli, "_send_request", _bad_response)

    output = tmp_path / "x.png"
    rc = resonite_cli.main(
        ["--socket", str(sock_path), "screenshot", "--output", str(output)]
    )

    assert rc == resonite_cli.EXIT_ACTION_FAILED
    err = capsys.readouterr().err
    assert "payload_bytes mismatch" in err
    # 書き出しは失敗側なので、ファイルは作られない。
    assert not output.exists()


def test_main_invalid_b64_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()

    monkeypatch.setattr(
        resonite_cli,
        "_send_request",
        lambda *_: {
            "ok": True,
            "action": "screenshot",
            "data": {
                "png_b64": "not!!valid!!base64",
                "width": 1,
                "height": 1,
                "payload_bytes": 0,
            },
        },
    )

    rc = resonite_cli.main(
        [
            "--socket",
            str(sock_path),
            "screenshot",
            "--output",
            str(tmp_path / "a.png"),
        ]
    )

    assert rc == resonite_cli.EXIT_ACTION_FAILED
    err = capsys.readouterr().err
    assert "base64 decode" in err


def test_main_error_response_passes_through(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()

    monkeypatch.setattr(
        resonite_cli,
        "_send_request",
        lambda *_: {
            "ok": False,
            "action": "screenshot",
            "error": "capture_failed",
            "detail": "X server unreachable",
        },
    )

    rc = resonite_cli.main(
        [
            "--socket",
            str(sock_path),
            "screenshot",
            "--output",
            str(tmp_path / "x.png"),
        ]
    )

    assert rc == resonite_cli.EXIT_ACTION_FAILED
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["ok"] is False
    assert parsed["error"] == "capture_failed"


def test_main_writes_to_absolute_path_outside_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``/tmp/...`` のような container 側絶対 path (repo 外) でも書ける。"""
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()
    monkeypatch.setattr(
        resonite_cli, "_send_request", lambda *_: _fake_screenshot_response()
    )

    output = tmp_path / "outside" / "repo.png"  # tmp_path は pytest が用意した
    # 一時 dir で、テスト用 "container 側絶対 path" の代用。
    rc = resonite_cli.main(
        ["--socket", str(sock_path), "screenshot", "--output", str(output)]
    )
    assert rc == 0
    assert output.is_file()


def test_main_missing_png_b64_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sock_path = tmp_path / "fake.sock"
    sock_path.touch()
    monkeypatch.setattr(
        resonite_cli,
        "_send_request",
        lambda *_: {
            "ok": True,
            "action": "screenshot",
            "data": {"width": 1, "height": 1},
        },
    )
    rc = resonite_cli.main(
        [
            "--socket",
            str(sock_path),
            "screenshot",
            "--output",
            str(tmp_path / "x.png"),
        ]
    )
    assert rc == resonite_cli.EXIT_ACTION_FAILED
    err = capsys.readouterr().err
    assert "png_b64" in err
