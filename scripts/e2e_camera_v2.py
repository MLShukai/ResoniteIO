#!/usr/bin/env python3
"""Camera v2 end-to-end harness for Claude self-verification.

Camera v2 が実装された後、Claude が ``just e2e-camera-v2`` 1 発で
「Resonite 起動済み → CameraClient.stream で N frame 取得 → 同時に
host screenshot 撮影 → fps + (将来) pixel diff を判定」できる harness。

Wave 0 の段階では:
- ``--skip-camera`` mode: screenshot 1 発のみ撮って成功すれば pass
- camera mode: CameraClient.stream を回し fps を測る + last frame を
  ``.npy`` で dump。PNG decode が container 側に重い依存 (Pillow 等) を
  要求するため、MSE 計算は **future work** として ``null`` に固定する

Usage:
    python scripts/e2e_camera_v2.py [--frames N] [--duration SEC]
                                    [--output-dir DIR] [--skip-camera]
                                    [--monitor 1] [--bbox X,Y,W,H]
                                    [--socket /uds/path]

Report (output-dir/report.json):
    {
      "fps": float | null,
      "frame_count": int,
      "screenshot_path": str,         # repo-relative
      "frame_sample_path": str | null, # last CameraFrame の raw RGBA dump (.npy)
      "mse": null,                     # future work; image decode 依存を避ける
      "pass": bool,
      "thresholds": {"fps": 55, "mse": null},
      "skip_camera": bool,
      "duration_sec": float,
      "errors": [str, ...]
    }

Exit code: 0 if pass else 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# screenshot は資料側で完結させたいので resonite_cli を subprocess で叩く。
# scripts/ は package 化されていないので、絶対パスで呼ぶ。
_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent

# camera mode の合格 fps しきい値 (plan 由来。 Camera v2 の目標は 60fps なので
# 余裕を持って 55 を採用)。
FPS_THRESHOLD = 55.0

# camera 取得を諦めるまでの保険 timeout。
DEFAULT_DURATION_SEC = 5.0


def _take_screenshot(
    output: str,
    monitor: int,
    bbox: str | None,
    socket_path: str | None,
) -> dict[str, Any]:
    """``resonite_cli.py screenshot`` を subprocess で呼ぶ。"""
    cmd = [
        sys.executable,
        str(_SCRIPTS_DIR / "resonite_cli.py"),
    ]
    if socket_path is not None:
        cmd.extend(["--socket", socket_path])
    cmd.extend(["screenshot", "--output", output, "--monitor", str(monitor)])
    if bbox is not None:
        cmd.extend(["--bbox", bbox])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


async def _stream_camera(duration_sec: float, frames_cap: int) -> dict[str, Any]:
    """``resoio.CameraClient`` で N frame 受信し fps を測る。

    返り値: ``frame_count`` / ``elapsed`` / ``fps`` / ``last_rgba`` /
    ``last_size`` / ``error`` の dict。エラーは raise せず ``error`` フィー
    ルドに格納する。
    """
    try:
        from resoio import CameraClient  # type: ignore[import-not-found]
    except ImportError as e:
        return {
            "frame_count": 0,
            "elapsed": 0.0,
            "fps": 0.0,
            "last_rgba": None,
            "last_size": None,
            "error": f"resoio.CameraClient import failed: {e}",
        }

    frame_count = 0
    last_rgba: bytes | None = None
    last_size: tuple[int, int] | None = None
    start = time.monotonic()
    deadline = start + duration_sec
    error: str | None = None
    try:
        async with CameraClient() as client:  # type: ignore[call-arg]
            async for frame in client.stream(width=0, height=0, fps_limit=0):
                frame_count += 1
                # CameraFrame の正確な属性は実装依存。最低限 numpy 互換 .pixels
                # を持つことを想定する。
                pixels = getattr(frame, "pixels", None)
                if pixels is not None:
                    last_rgba = bytes(pixels.tobytes())
                    shape = getattr(pixels, "shape", None)
                    if shape is not None and len(shape) >= 2:
                        last_size = (int(shape[1]), int(shape[0]))
                if frame_count >= frames_cap or time.monotonic() >= deadline:
                    break
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    elapsed = time.monotonic() - start
    fps = (frame_count / elapsed) if elapsed > 0 else 0.0
    return {
        "frame_count": frame_count,
        "elapsed": elapsed,
        "fps": fps,
        "last_rgba": last_rgba,
        "last_size": last_size,
        "error": error,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="出力先 dir (repo-relative)。未指定時は tmp/e2e-camera-v2-<nanos>/",
    )
    parser.add_argument(
        "--frames", type=int, default=300, help="取得 frame 数の上限 (default=300)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_SEC,
        help=f"取得時間の上限秒 (default={DEFAULT_DURATION_SEC})",
    )
    parser.add_argument(
        "--skip-camera",
        action="store_true",
        help="CameraClient を呼ばず screenshot のみ撮る (Camera 未実装時の dry run)",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=1,
        help="screenshot の monitor index (default=1=primary)",
    )
    parser.add_argument(
        "--bbox",
        default=None,
        help="screenshot bbox 'x,y,w,h'。未指定なら full monitor",
    )
    parser.add_argument(
        "--socket",
        default=None,
        help="host-agent UDS path (default は resonite_cli.py のデフォルト)",
    )
    return parser


def _default_output_dir() -> str:
    return f"tmp/e2e-camera-v2-{time.monotonic_ns()}"


def run(args: argparse.Namespace) -> int:
    """Harness 本体。``args`` は ``_build_parser().parse_args(...)`` の結果。

    return: process exit code (0 if pass else 1)
    """
    output_dir_rel = args.output_dir or _default_output_dir()
    output_dir_abs = (_REPO_ROOT / output_dir_rel).resolve()
    output_dir_abs.mkdir(parents=True, exist_ok=True)

    screenshot_rel = f"{output_dir_rel}/screenshot.png"
    errors: list[str] = []

    # 1) screenshot を撮る
    screenshot_result = _take_screenshot(
        screenshot_rel, args.monitor, args.bbox, args.socket
    )
    screenshot_ok = screenshot_result["exit_code"] == 0
    if not screenshot_ok:
        # resonite_cli は応答を stdout に JSON で出すため、stdout も合わせて拾う。
        detail = (
            screenshot_result["stderr"].strip() or screenshot_result["stdout"].strip()
        )
        errors.append(
            f"screenshot failed: exit={screenshot_result['exit_code']} {detail}"
        )

    # 2) (option) Camera stream
    camera_fps: float | None = None
    frame_count = 0
    frame_sample_rel: str | None = None
    if args.skip_camera:
        pass
    else:
        camera = asyncio.run(_stream_camera(args.duration, args.frames))
        camera_fps = camera["fps"]
        frame_count = camera["frame_count"]
        if camera["error"]:
            errors.append(f"camera stream failed: {camera['error']}")
        if camera["last_rgba"] and camera["last_size"]:
            # raw RGBA bytes を .npy ではなく .bin で素朴に書く (numpy 依存を
            # 抑える)。最初の 2 つの uint32 = width, height を header に入れる。
            sample_path_abs = output_dir_abs / "frame_sample.bin"
            width, height = camera["last_size"]
            with sample_path_abs.open("wb") as f:
                f.write(width.to_bytes(4, "little"))
                f.write(height.to_bytes(4, "little"))
                f.write(camera["last_rgba"])
            frame_sample_rel = str(sample_path_abs.relative_to(_REPO_ROOT))

    # 3) judge pass / fail
    if args.skip_camera:
        passed = screenshot_ok
    else:
        passed = (
            screenshot_ok and camera_fps is not None and camera_fps >= FPS_THRESHOLD
        )

    report: dict[str, Any] = {
        "fps": camera_fps,
        "frame_count": frame_count,
        "screenshot_path": screenshot_rel,
        "frame_sample_path": frame_sample_rel,
        "mse": None,  # future work; PNG decode に Pillow 等を入れない方針
        "pass": passed,
        "thresholds": {"fps": FPS_THRESHOLD, "mse": None},
        "skip_camera": bool(args.skip_camera),
        "duration_sec": float(args.duration),
        "errors": errors,
    }
    report_path = output_dir_abs / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
