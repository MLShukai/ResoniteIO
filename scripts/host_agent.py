#!/usr/bin/env python3
"""Host-side debug bridge daemon.

container 内 ``scripts/resonite_cli.py`` からの UDS リクエストを受け、host
側で Gale CLI 経由で Resonite を起動 / 停止 / 状態取得し、また desktop
framebuffer を ``mss`` で撮って **PNG bytes を base64 で response に乗せる**。
file system に書かないので bind mount への依存がなく、container 側で任意
path に書ける。Resonite と Gale は host の GUI session でしか動かないため、
本デーモンは GUI session の端末から foreground で起動する。

Protocol: UDS (AF_UNIX) 上で 1 リクエスト / 1 レスポンスの newline-delimited
JSON、接続 close で終端。

Request schema:
    {"action": "start" | "stop" | "status", "profile": str | null}
    {"action": "screenshot",
     "monitor": int (default=1, 0=all monitors),
     "bbox": null | [x, y, w, h]}

Response schema:
    {"ok": true,  "action": str, "data": dict}
    {"ok": false, "action": str, "error": str, "detail": str, "data": dict?}

screenshot response data:
    {"png_b64": str,         # base64 of PNG bytes
     "width": int,
     "height": int,
     "monitor": int,
     "payload_bytes": int}   # len(PNG bytes) (base64 前)、client 側の sanity check 用
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Any

import mss
import mss.tools

LOG = logging.getLogger("host_agent")

DEFAULT_SOCKET_REL = ".resonite-io-debug/host-agent.sock"

ACCEPT_TIMEOUT_SEC = 1.0
CLIENT_TIMEOUT_SEC = 5.0
MAX_REQUEST_BYTES = 8192
TERMINATION_POLL_INTERVAL_SEC = 0.3
TERMINATION_TIMEOUT_SEC = 3.0

# kill 対象プロセス名 (pkill -f に渡す)。Steam reaper が回収するので Proton
# 系プロセス (pressure-vessel-wrap / srt-bwrap / reaper) は触らない。
RESONITE_PATTERN = "Resonite.exe"
RENDERITE_PATTERN = "Renderite.Renderer.exe"


class StartupError(RuntimeError):
    """起動前提条件の不成立。``main`` 側でメッセージ表示 + exit 1。"""


# ===== startup checks =======================================================


def _default_socket_path() -> Path:
    home = os.environ.get("HOME", "")
    if not home:
        raise StartupError(
            "HOME が未設定です。通常の login session で実行してください。"
        )
    return Path(home) / DEFAULT_SOCKET_REL


def _check_display() -> None:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise StartupError(
            "DISPLAY / WAYLAND_DISPLAY が両方未設定です。"
            "gale は --no-gui でもディスプレイを要求するため、GUI session の端末から起動してください。"
        )


def _resolve_gale_bin() -> str:
    """``GaleBin`` env var (or PATH lookup) から gale 実行ファイルの絶対パスを返す。"""
    candidate = os.environ.get("GaleBin", "gale")
    if "/" in candidate:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise StartupError(
            f"GaleBin で指定された実行ファイルが見つからない / 実行権限がありません: {candidate!r}"
        )
    found = shutil.which(candidate)
    if not found:
        raise StartupError(
            f"PATH 上に gale 実行ファイルが見つかりません: {candidate!r}。"
            ".env の GaleBin で絶対パスを指定するか、PATH に gale を入れてください。"
        )
    return found


def _ensure_socket_dir(sock_path: Path) -> None:
    parent = sock_path.parent
    if not parent.is_dir():
        raise StartupError(
            f"{parent} が見当たりません。`just container-up` で host 側 dir を作成してください。"
        )


def _is_listener_alive(sock_path: Path) -> bool:
    """既存 socket file に対して connect 試行。成功 = 別インスタンス稼働中。"""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            probe.connect(str(sock_path))
            return True
    except OSError:
        return False


def _bind_socket(sock_path: Path) -> socket.socket:
    if sock_path.exists():
        if _is_listener_alive(sock_path):
            raise StartupError(
                f"既に host-agent が動作しているようです ({sock_path})。"
                "別インスタンスを Ctrl+C で停止してから再起動してください。"
            )
        sock_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(sock_path))
        os.chmod(sock_path, 0o600)
        server.listen(8)
        server.settimeout(ACCEPT_TIMEOUT_SEC)
    except Exception:
        server.close()
        raise
    return server


# ===== process inspection / control =========================================


def _list_pids_by_pattern(pattern: str) -> list[dict[str, Any]]:
    """``pgrep -af <pattern>`` で一致プロセスを列挙する。空配列 = 該当なし。"""
    proc = subprocess.run(
        ["pgrep", "-af", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 1:
        return []
    if proc.returncode != 0:
        LOG.warning(
            "pgrep -af %r exit=%d stderr=%s",
            pattern,
            proc.returncode,
            proc.stderr.strip(),
        )
        return []
    matches: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, _, cmdline = line.partition(" ")
        try:
            matches.append({"pid": int(pid_str), "cmdline": cmdline})
        except ValueError:
            continue
    return matches


def _pkill(signal_name: str, pattern: str) -> None:
    subprocess.run(
        ["pkill", f"-{signal_name}", "-f", pattern],
        capture_output=True,
        text=True,
        check=False,
    )


# ===== command handlers =====================================================


def _is_safe_profile(profile: str) -> bool:
    return bool(profile) and all(c.isalnum() or c in "._-" for c in profile)


def _ok(action: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "action": action, "data": data}


def _error(
    action: str,
    error: str,
    detail: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resp: dict[str, Any] = {
        "ok": False,
        "action": action,
        "error": error,
        "detail": detail,
    }
    if data is not None:
        resp["data"] = data
    return resp


def cmd_start(profile: str | None, gale_bin: str) -> dict[str, Any]:
    if not profile:
        return _error(
            "start", "missing_profile", "profile is required for the start action"
        )
    if not _is_safe_profile(profile):
        return _error(
            "start",
            "invalid_profile",
            f"profile contains disallowed characters: {profile!r} (allowed: [A-Za-z0-9._-])",
        )
    running = _list_pids_by_pattern(RESONITE_PATTERN)
    if running:
        return _error(
            "start",
            "already_running",
            "Resonite is already running. Stop it first.",
            data={"running": running},
        )
    try:
        gale_proc = subprocess.Popen(
            [gale_bin, "-g", "resonite", "-p", profile, "--launch", "--no-gui"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        return _error("start", "gale_failed", f"gale binary disappeared: {e}")
    except OSError as e:
        return _error("start", "gale_failed", f"failed to launch gale: {e}")
    LOG.info("Launched gale (pid=%d, profile=%s)", gale_proc.pid, profile)
    return _ok("start", {"gale_pid": gale_proc.pid, "profile": profile})


def cmd_stop() -> dict[str, Any]:
    """``Resonite.exe`` と ``Renderite.Renderer.exe`` を SIGTERM→3s→SIGKILL
    する。"""
    patterns = [RESONITE_PATTERN, RENDERITE_PATTERN]
    initial: list[dict[str, Any]] = []
    for pattern in patterns:
        initial.extend(_list_pids_by_pattern(pattern))
    if not initial:
        return _ok("stop", {"terminated": [], "killed": []})

    for pattern in patterns:
        _pkill("TERM", pattern)

    deadline = time.monotonic() + TERMINATION_TIMEOUT_SEC
    while time.monotonic() < deadline:
        time.sleep(TERMINATION_POLL_INTERVAL_SEC)
        survivors_now: list[dict[str, Any]] = []
        for pattern in patterns:
            survivors_now.extend(_list_pids_by_pattern(pattern))
        if not survivors_now:
            break

    killed: list[dict[str, Any]] = []
    for pattern in patterns:
        survivors = _list_pids_by_pattern(pattern)
        if survivors:
            _pkill("KILL", pattern)
            killed.extend(survivors)

    LOG.info("Stop complete. signaled=%d, force_killed=%d", len(initial), len(killed))
    return _ok("stop", {"terminated": initial, "killed": killed})


def cmd_status() -> dict[str, Any]:
    resonite = _list_pids_by_pattern(RESONITE_PATTERN)
    renderite = _list_pids_by_pattern(RENDERITE_PATTERN)
    return _ok(
        "status",
        {"resonite": resonite, "renderite": renderite, "running": bool(resonite)},
    )


# ===== screenshot ===========================================================


def _parse_bbox(bbox: Any) -> tuple[int, int, int, int] | None:
    """``bbox`` をパースし ``(left, top, width, height)`` を返す。

    None なら None を返す (full monitor を意味する)。
    """
    if bbox is None:
        return None
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError(f"bbox must be a list of 4 integers, got: {bbox!r}")
    coerced: list[int] = []
    for i, v in enumerate(bbox):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"bbox[{i}] must be an integer, got: {type(v).__name__}")
        coerced.append(v)
    left, top, width, height = coerced
    if width <= 0 or height <= 0:
        raise ValueError(f"bbox width/height must be positive, got: {bbox!r}")
    return left, top, width, height


def cmd_screenshot(monitor: Any, bbox: Any) -> dict[str, Any]:
    """``mss`` で desktop framebuffer を撮影し PNG bytes を base64 で返す。

    host-local 書き出しはせず in-memory PNG を base64 で response に乗せる (client が
    container 側で書き出す)。
    """
    if monitor is None:
        monitor_idx = 1
    elif isinstance(monitor, bool) or not isinstance(monitor, int):
        return _error(
            "screenshot",
            "bad_request",
            f"monitor must be an integer, got: {type(monitor).__name__}",
        )
    else:
        monitor_idx = monitor

    try:
        bbox_tuple = _parse_bbox(bbox)
    except ValueError as e:
        return _error("screenshot", "bad_request", str(e))

    try:
        sct = mss.MSS()
        monitors = sct.monitors
        if not (0 <= monitor_idx < len(monitors)):
            return _error(
                "screenshot",
                "invalid_monitor",
                f"monitor index {monitor_idx} out of range "
                f"(available: 0..{len(monitors) - 1})",
            )
        if bbox_tuple is not None:
            left, top, width, height = bbox_tuple
            region = {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
            img = sct.grab(region)
        else:
            img = sct.grab(monitors[monitor_idx])
        png_bytes = mss.tools.to_png(img.rgb, img.size, output=None)
    except Exception as e:
        return _error(
            "screenshot",
            "capture_failed",
            f"mss capture failed: {type(e).__name__}: {e}",
        )

    if not isinstance(png_bytes, (bytes, bytearray)):
        return _error(
            "screenshot",
            "capture_failed",
            f"mss.tools.to_png did not return bytes: got {type(png_bytes).__name__}",
        )

    width, height = img.size
    png_b64 = base64.b64encode(bytes(png_bytes)).decode("ascii")
    LOG.info(
        "Captured screenshot (%dx%d, monitor=%d, payload=%d bytes)",
        width,
        height,
        monitor_idx,
        len(png_bytes),
    )
    return _ok(
        "screenshot",
        {
            "png_b64": png_b64,
            "width": int(width),
            "height": int(height),
            "monitor": monitor_idx,
            "payload_bytes": len(png_bytes),
        },
    )


# ===== request dispatch =====================================================


def handle_request(raw: bytes, gale_bin: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _error("?", "bad_request", "request is not valid UTF-8")
    try:
        msg = json.loads(text)
    except json.JSONDecodeError as e:
        return _error("?", "bad_request", f"invalid JSON: {e}")
    if not isinstance(msg, dict):
        return _error("?", "bad_request", "request must be a JSON object")

    action = msg.get("action")
    if action == "start":
        profile = msg.get("profile")
        if profile is not None and not isinstance(profile, str):
            return _error("start", "bad_request", "profile must be a string")
        return cmd_start(profile, gale_bin)
    if action == "stop":
        return cmd_stop()
    if action == "status":
        return cmd_status()
    if action == "screenshot":
        # 旧 protocol の ``output`` field は無視 (PNG bytes を返す network 経路に移行済み)。
        return cmd_screenshot(
            msg.get("monitor"),
            msg.get("bbox"),
        )
    label = str(action) if isinstance(action, str) else "?"
    return _error(label, "bad_request", f"unknown action: {action!r}")


def _serve_one(conn: socket.socket, gale_bin: str) -> None:
    conn.settimeout(CLIENT_TIMEOUT_SEC)
    buf = bytearray()
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\n" in chunk or len(buf) >= MAX_REQUEST_BYTES:
                break
        line, _, _ = bytes(buf).partition(b"\n")
        if len(line) > MAX_REQUEST_BYTES:
            response = _error("?", "bad_request", "request line too large")
        else:
            response = handle_request(line, gale_bin)
        conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
    except TimeoutError:
        LOG.warning("client read/write timed out")
    except Exception:
        LOG.exception("handler error")
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        conn.close()


# ===== main loop ============================================================


class _Shutdown:
    """Ctrl+C / SIGTERM 受信フラグ。accept_loop が break するためだけに使う。"""

    def __init__(self) -> None:
        self.flag = False

    def trip(self, _signum: int, _frame: FrameType | None) -> None:
        self.flag = True


def _accept_loop(server: socket.socket, gale_bin: str, shutdown: _Shutdown) -> None:
    while not shutdown.flag:
        try:
            conn, _addr = server.accept()
        except TimeoutError:
            continue
        except OSError as e:
            if shutdown.flag:
                break
            LOG.error("accept() failed: %s", e)
            time.sleep(0.1)
            continue
        _serve_one(conn, gale_bin)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Host-side debug bridge daemon for Resonite IO."
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=None,
        help="override UDS path (default: $HOME/.resonite-io-debug/host-agent.sock)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=getattr(logging, args.log_level),
    )

    try:
        sock_path: Path = (
            args.socket if args.socket is not None else _default_socket_path()
        )
        _check_display()
        gale_bin = _resolve_gale_bin()
        _ensure_socket_dir(sock_path)
        server = _bind_socket(sock_path)
    except StartupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    shutdown = _Shutdown()
    signal.signal(signal.SIGINT, shutdown.trip)
    signal.signal(signal.SIGTERM, shutdown.trip)

    LOG.info("host-agent listening on %s (gale_bin=%s)", sock_path, gale_bin)
    try:
        _accept_loop(server, gale_bin, shutdown)
    finally:
        try:
            server.close()
        except OSError:
            pass
        try:
            sock_path.unlink()
        except FileNotFoundError:
            pass
        LOG.info("host-agent stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
