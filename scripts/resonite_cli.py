#!/usr/bin/env python3
"""Container-side client for the host debug bridge.

container 内 shell から ``just resonite-{start,stop,status,screenshot}``
経由で呼ばれ、host 常駐の ``scripts/host_agent.py`` に UDS で 1 リクエスト
送って 1 レスポンスを受け取って表示する薄い CLI。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import string
import sys
from pathlib import Path
from typing import Any

DEFAULT_SOCKET_REL = ".resonite-io-debug/host-agent.sock"
CONNECT_TIMEOUT_SEC = 5.0
READ_TIMEOUT_SEC = 30.0  # stop は最大 3 秒待ち + α
MAX_RESPONSE_BYTES = 65536

# プロファイル名に許す文字 (host_agent と同じ規約)。
_PROFILE_ALLOWED = set(string.ascii_letters + string.digits + "._-")

# Screenshot output path に許す文字 (host_agent と同じ規約)。
_SCREENSHOT_PATH_ALLOWED = set(string.ascii_letters + string.digits + "._-/")

# Exit codes
EXIT_OK = 0
EXIT_ACTION_FAILED = 1
EXIT_USAGE = 2
EXIT_NO_SOCKET = 3


def _default_socket_path() -> Path:
    home = os.environ.get("HOME", "")
    if not home:
        print(
            "ERROR: HOME が未設定です。通常の login session で実行してください。",
            file=sys.stderr,
        )
        sys.exit(EXIT_NO_SOCKET)
    return Path(home) / DEFAULT_SOCKET_REL


def _resolve_profile(arg: str | None) -> str:
    """``--profile`` 引数 → ``$GaleProfile`` env → 失敗時 exit 2 で fail-fast。"""
    profile = arg or os.environ.get("GaleProfile", "")
    profile = profile.strip()
    if not profile:
        print(
            "ERROR: profile が未指定です。`--profile <name>` または .env の GaleProfile を設定してください。",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    if not all(c in _PROFILE_ALLOWED for c in profile):
        print(
            f"ERROR: profile に許可外文字が含まれています: {profile!r} (許容: [A-Za-z0-9._-])",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    return profile


def _validate_screenshot_output(output: str) -> str:
    """``--output`` を client 側で軽く checkout する (重複検証は host_agent に委ねる)。

    fail-fast のために絶対パス / ``..`` / 許容外文字を弾く。最終的な
    repo-root 内側判定は host_agent.py 側で再実施される。
    """
    if not output:
        print("ERROR: --output が空です。", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if output.startswith("/"):
        print(
            f"ERROR: --output は repo-relative path で指定してください (got: {output!r})",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    if any(part == ".." for part in output.split("/")):
        print(
            f"ERROR: --output に '..' セグメントは使えません (got: {output!r})",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    if not all(c in _SCREENSHOT_PATH_ALLOWED for c in output):
        print(
            f"ERROR: --output に許可外文字が含まれています: {output!r} "
            "(許容: [A-Za-z0-9._-/])",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    return output


def _parse_bbox_arg(value: str | None) -> list[int] | None:
    """``--bbox x,y,w,h`` を ``[x, y, w, h]`` に変換する。None なら None。"""
    if value is None:
        return None
    parts = value.split(",")
    if len(parts) != 4:
        print(
            f"ERROR: --bbox は 'x,y,w,h' 形式の 4 整数で指定してください (got: {value!r})",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    try:
        ints = [int(p.strip()) for p in parts]
    except ValueError:
        print(
            f"ERROR: --bbox の要素は整数である必要があります (got: {value!r})",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    return ints


def _send_request(sock_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    if not sock_path.exists():
        print(
            f"ERROR: host-agent socket が見当たりません ({sock_path})。"
            "host 側 GUI session の端末で `just host-agent` を起動してください。",
            file=sys.stderr,
        )
        sys.exit(EXIT_NO_SOCKET)
    payload = (json.dumps(request) + "\n").encode("utf-8")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(CONNECT_TIMEOUT_SEC)
            sock.connect(str(sock_path))
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)
            sock.settimeout(READ_TIMEOUT_SEC)
            buf = bytearray()
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) >= MAX_RESPONSE_BYTES:
                    break
    except (ConnectionRefusedError, FileNotFoundError):
        print(
            f"ERROR: host-agent に接続できません ({sock_path})。"
            "host 側で `just host-agent` が動作しているか確認してください。",
            file=sys.stderr,
        )
        sys.exit(EXIT_NO_SOCKET)
    except TimeoutError:
        print("ERROR: host-agent の応答が timeout しました。", file=sys.stderr)
        sys.exit(EXIT_ACTION_FAILED)
    except OSError as e:
        print(f"ERROR: UDS 通信エラー: {e}", file=sys.stderr)
        sys.exit(EXIT_ACTION_FAILED)

    line, _, _ = bytes(buf).partition(b"\n")
    try:
        parsed = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"ERROR: host-agent から不正な応答: {e}", file=sys.stderr)
        sys.exit(EXIT_ACTION_FAILED)
    if not isinstance(parsed, dict):
        print(
            "ERROR: host-agent から JSON オブジェクト以外が返されました。",
            file=sys.stderr,
        )
        sys.exit(EXIT_ACTION_FAILED)
    return parsed


def _print_response(response: dict[str, Any]) -> int:
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return EXIT_OK if response.get("ok") else EXIT_ACTION_FAILED


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Container-side client for the host debug bridge."
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=None,
        help="override UDS path (default: $HOME/.resonite-io-debug/host-agent.sock)",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    start = sub.add_parser("start", help="Resonite を Gale 経由で起動する")
    start.add_argument(
        "--profile",
        default=None,
        help="Gale profile 名 (省略時は .env の GaleProfile を使用)",
    )

    sub.add_parser("stop", help="Resonite / Renderite を SIGTERM→SIGKILL で停止する")
    sub.add_parser("status", help="Resonite / Renderite の実行状態を表示する")

    screenshot = sub.add_parser(
        "screenshot",
        help="host の desktop framebuffer を repo-relative path に PNG で書き出す",
    )
    screenshot.add_argument(
        "--output",
        required=True,
        help="出力先 (repo-relative path、`.png` 必須、`..` / 絶対パス禁止)",
    )
    screenshot.add_argument(
        "--monitor",
        type=int,
        default=1,
        help="mss の monitor index (0=合成、1=primary、default=1)",
    )
    screenshot.add_argument(
        "--bbox",
        default=None,
        help="部分領域を 'x,y,w,h' (整数) で指定。未指定なら full monitor",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    sock_path: Path = args.socket if args.socket is not None else _default_socket_path()

    request: dict[str, Any]
    if args.action == "start":
        request = {"action": "start", "profile": _resolve_profile(args.profile)}
    elif args.action == "stop":
        request = {"action": "stop"}
    elif args.action == "status":
        request = {"action": "status"}
    elif args.action == "screenshot":
        request = {
            "action": "screenshot",
            "output": _validate_screenshot_output(args.output),
            "monitor": int(args.monitor),
            "bbox": _parse_bbox_arg(args.bbox),
        }
    else:
        print(f"ERROR: unknown action: {args.action!r}", file=sys.stderr)
        return EXIT_USAGE

    response = _send_request(sock_path, request)
    return _print_response(response)


if __name__ == "__main__":
    sys.exit(main())
