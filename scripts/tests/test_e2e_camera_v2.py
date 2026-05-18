"""Tests for ``scripts/e2e_camera_v2.py``.

Wave 0 段階の harness は ``--skip-camera`` だけ実用的なので、ここでは
screenshot を subprocess mock で fake して以下を検証する:

- ``--skip-camera`` dry-run: screenshot 成功時に report.json が書かれ exit 0
- screenshot 失敗時に exit 1 と errors[] が記録される
- 標準 path の正常系で report.json schema を満たす
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import e2e_camera_v2  # pyright: ignore[reportMissingImports]


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``_REPO_ROOT`` を tmp_path に向け、テスト終了で元に戻す。"""
    original = e2e_camera_v2._REPO_ROOT
    monkeypatch.setattr(e2e_camera_v2, "_REPO_ROOT", tmp_path.resolve())
    yield tmp_path.resolve()
    monkeypatch.setattr(e2e_camera_v2, "_REPO_ROOT", original)


def _patch_screenshot(
    monkeypatch: pytest.MonkeyPatch,
    *,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    side_effect: Any = None,
) -> dict[str, Any]:
    """``_take_screenshot`` を mock して、呼び出し引数を捕捉する。"""
    captured: dict[str, Any] = {}

    def _fake(
        output: str, monitor: int, bbox: str | None, socket_path: str | None
    ) -> dict[str, Any]:
        captured.update(
            output=output, monitor=monitor, bbox=bbox, socket_path=socket_path
        )
        if side_effect is not None:
            raise side_effect
        return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}

    monkeypatch.setattr(e2e_camera_v2, "_take_screenshot", _fake)
    return captured


def test_skip_camera_dry_run_pass(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_screenshot(monkeypatch, exit_code=0, stdout='{"ok": true}\n')

    args = e2e_camera_v2._build_parser().parse_args(
        ["--skip-camera", "--output-dir", "tmp/e2e-run/0001"]
    )
    rc = e2e_camera_v2.run(args)

    assert rc == 0
    report_path = repo_root / "tmp" / "e2e-run" / "0001" / "report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["pass"] is True
    assert report["fps"] is None
    assert report["frame_count"] == 0
    # 新 protocol: container 側絶対 path で記録される
    expected_screenshot = repo_root / "tmp" / "e2e-run" / "0001" / "screenshot.png"
    assert report["screenshot_path"] == str(expected_screenshot)
    assert report["frame_sample_path"] is None
    assert report["mse"] is None
    assert report["skip_camera"] is True
    assert report["errors"] == []
    # resonite_cli には絶対 path で渡す
    assert captured["output"] == str(expected_screenshot)
    assert captured["monitor"] == 1
    assert captured["bbox"] is None


def test_skip_camera_dry_run_fail_when_screenshot_errors(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_screenshot(
        monkeypatch, exit_code=1, stderr="ERROR: host-agent socket missing"
    )

    args = e2e_camera_v2._build_parser().parse_args(
        ["--skip-camera", "--output-dir", "tmp/e2e-run/fail"]
    )
    rc = e2e_camera_v2.run(args)

    assert rc == 1
    report = json.loads(
        (repo_root / "tmp" / "e2e-run" / "fail" / "report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["pass"] is False
    assert any("screenshot failed" in e for e in report["errors"])


def test_default_output_dir_is_under_tmp_e2e(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_screenshot(monkeypatch, exit_code=0)
    args = e2e_camera_v2._build_parser().parse_args(["--skip-camera"])
    rc = e2e_camera_v2.run(args)

    assert rc == 0
    # tmp/e2e-camera-v2-<nanos>/ 以下が作られているはず。
    tmp_dir = repo_root / "tmp"
    assert tmp_dir.is_dir()
    subdirs = [d for d in tmp_dir.iterdir() if d.is_dir()]
    assert subdirs, "default output dir was not created"
    assert any(d.name.startswith("e2e-camera-v2-") for d in subdirs)


def test_bbox_and_monitor_flow_through_to_screenshot(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_screenshot(monkeypatch, exit_code=0)
    args = e2e_camera_v2._build_parser().parse_args(
        [
            "--skip-camera",
            "--output-dir",
            "tmp/e2e-run/cli-args",
            "--monitor",
            "2",
            "--bbox",
            "10,20,640,480",
            "--socket",
            "/tmp/host-agent.sock",
        ]
    )
    rc = e2e_camera_v2.run(args)
    assert rc == 0
    assert captured["monitor"] == 2
    assert captured["bbox"] == "10,20,640,480"
    assert captured["socket_path"] == "/tmp/host-agent.sock"


def test_camera_mode_passes_when_fps_above_threshold(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_screenshot(monkeypatch, exit_code=0)

    async def _fake_stream(duration_sec: float, frames_cap: int) -> dict[str, Any]:
        return {
            "frame_count": 120,
            "elapsed": 2.0,  # → 60 fps
            "fps": 60.0,
            "last_rgba": None,
            "last_size": None,
            "error": None,
        }

    monkeypatch.setattr(e2e_camera_v2, "_stream_camera", _fake_stream)
    args = e2e_camera_v2._build_parser().parse_args(
        ["--output-dir", "tmp/e2e-run/cam-pass"]
    )
    rc = e2e_camera_v2.run(args)
    assert rc == 0
    report = json.loads(
        (repo_root / "tmp" / "e2e-run" / "cam-pass" / "report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["pass"] is True
    assert report["fps"] == 60.0
    assert report["frame_count"] == 120
    assert report["skip_camera"] is False


def test_camera_mode_fails_when_fps_below_threshold(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_screenshot(monkeypatch, exit_code=0)

    async def _fake_stream(duration_sec: float, frames_cap: int) -> dict[str, Any]:
        return {
            "frame_count": 60,
            "elapsed": 2.0,  # → 30 fps
            "fps": 30.0,
            "last_rgba": None,
            "last_size": None,
            "error": None,
        }

    monkeypatch.setattr(e2e_camera_v2, "_stream_camera", _fake_stream)
    args = e2e_camera_v2._build_parser().parse_args(
        ["--output-dir", "tmp/e2e-run/cam-slow"]
    )
    rc = e2e_camera_v2.run(args)
    assert rc == 1


def test_camera_mode_writes_frame_sample_when_pixels_present(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_screenshot(monkeypatch, exit_code=0)
    rgba = bytes(4 * 4 * 4)  # 4x4 RGBA = 64 bytes

    async def _fake_stream(duration_sec: float, frames_cap: int) -> dict[str, Any]:
        return {
            "frame_count": 200,
            "elapsed": 2.0,
            "fps": 100.0,
            "last_rgba": rgba,
            "last_size": (4, 4),
            "error": None,
        }

    monkeypatch.setattr(e2e_camera_v2, "_stream_camera", _fake_stream)
    args = e2e_camera_v2._build_parser().parse_args(
        ["--output-dir", "tmp/e2e-run/with-sample"]
    )
    rc = e2e_camera_v2.run(args)
    assert rc == 0
    sample = repo_root / "tmp" / "e2e-run" / "with-sample" / "frame_sample.bin"
    assert sample.is_file()
    # header (8 bytes) + 64 bytes payload
    assert sample.stat().st_size == 8 + 64
    report = json.loads(
        (repo_root / "tmp" / "e2e-run" / "with-sample" / "report.json").read_text(
            encoding="utf-8"
        )
    )
    # 新 protocol: container 側絶対 path
    assert report["frame_sample_path"] == str(sample)
