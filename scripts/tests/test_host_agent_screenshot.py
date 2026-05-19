"""Tests for the ``screenshot`` action of ``scripts/host_agent.py``.

host (Resonite を動かす GUI session) では ``pyscreenshot`` が
``scripts/requirements.txt`` 経由で venv に入っている。テストでは
``host_agent.pyscreenshot.grab`` を fake に差し替える。

新 protocol: host_agent は file system に書かず、PNG bytes を base64
にして response data に乗せる。``monitor`` フィールドは廃止済み、
``output`` フィールドは旧 client 互換のため silently ignore する。

テスト範囲:
- 正常系: response の ``png_b64`` を decode した bytes が fake grab+save
  が書いた bytes と一致し、``payload_bytes`` が len(bytes) と一致する
- ``bbox`` 指定が ``pyscreenshot.grab(bbox=...)`` に (x1, y1, x2, y2) 形式で
  正しく渡される
- ``bbox`` 不正型を拒否する
- 旧 protocol の ``output`` フィールドが request にあっても成功する
  (silently ignored、後方互換)
- capture (grab / save) が例外を投げた場合は ``capture_failed`` で返す
- UDS round-trip: 実 socket 経由で base64 PNG bytes が往復する
"""

from __future__ import annotations

import base64
import io
import json
import socket
import threading
from typing import Any

import pytest

# host_agent は scripts/tests/conftest.py の sys.path 注入で import 可能。
import host_agent  # noqa: E402  # pyright: ignore[reportMissingImports]


# ----- fake pyscreenshot ----------------------------------------------------

_FAKE_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class _FakeImage:
    """``pyscreenshot.grab(...)`` の戻り値を最小再現する。

    host_agent が触る surface は ``.size`` (tuple) と ``.save(buf, format)``
    のみ。``.save`` は任意の non-empty bytes を ``buf`` に書く。
    """

    def __init__(self, width: int, height: int) -> None:
        self.size: tuple[int, int] = (width, height)

    def save(self, buf: io.BytesIO, format: str) -> None:  # noqa: A002
        assert format == "PNG"
        # PNG magic + size を含む dummy payload。base64 round-trip 検証用に
        # bytes であれば十分。
        w, h = self.size
        buf.write(_FAKE_PNG_MAGIC)
        buf.write(w.to_bytes(4, "little"))
        buf.write(h.to_bytes(4, "little"))


def _install_fake_grab(
    monkeypatch: pytest.MonkeyPatch,
    *,
    image: _FakeImage | None = None,
    raises: Exception | None = None,
) -> dict[str, Any]:
    """``host_agent.pyscreenshot.grab`` を fake に差し替え、呼び出しを記録する。

    戻り値の dict の ``calls`` には ``grab`` に渡された ``bbox`` (or None)
    の列が積まれる。
    """
    captured: dict[str, Any] = {"calls": []}
    img = image if image is not None else _FakeImage(1920, 1080)

    def _fake_grab(bbox: Any = None) -> _FakeImage:
        captured["calls"].append(bbox)
        if raises is not None:
            raise raises
        return img

    monkeypatch.setattr(host_agent.pyscreenshot, "grab", _fake_grab)
    return captured


# ----- helpers --------------------------------------------------------------


def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    return host_agent.handle_request(
        json.dumps(payload).encode("utf-8"),
        gale_bin="/nonexistent/gale",  # screenshot は gale を呼ばないので無害
    )


# ----- tests: success path --------------------------------------------------


def test_screenshot_returns_base64_png_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_grab(monkeypatch, image=_FakeImage(640, 480))

    response = _dispatch({"action": "screenshot"})

    assert response["ok"] is True, response
    assert response["action"] == "screenshot"
    data = response["data"]
    assert set(data.keys()) == {"png_b64", "width", "height", "payload_bytes"}
    assert data["width"] == 640
    assert data["height"] == 480

    decoded = base64.b64decode(data["png_b64"])
    assert decoded.startswith(_FAKE_PNG_MAGIC)
    assert len(decoded) == data["payload_bytes"]
    # bbox 未指定なら full desktop (bbox=None で grab 呼び出し)。
    assert captured["calls"] == [None]


def test_screenshot_bbox_passes_xyxy_to_pyscreenshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bbox=[x, y, w, h]`` が pyscreenshot 互換 ``(x1, y1, x2, y2)``
    に変換されること。"""
    captured = _install_fake_grab(monkeypatch, image=_FakeImage(100, 50))

    response = _dispatch(
        {
            "action": "screenshot",
            "bbox": [10, 20, 100, 50],
        }
    )

    assert response["ok"] is True, response
    # (left, top, left+width, top+height) = (10, 20, 110, 70)
    assert captured["calls"] == [(10, 20, 110, 70)]
    assert response["data"]["width"] == 100
    assert response["data"]["height"] == 50


def test_screenshot_ignores_legacy_output_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧 client が ``output`` を送ってきても新 protocol では silently ignore。"""
    _install_fake_grab(monkeypatch, image=_FakeImage(320, 240))

    response = _dispatch(
        {
            "action": "screenshot",
            "output": "/absolute/garbage/path.png",
        }
    )

    assert response["ok"] is True, response
    assert "png_b64" in response["data"]
    # response の data に旧 ``path`` フィールドは無いこと。
    assert "path" not in response["data"]


# ----- tests: bbox validation ----------------------------------------------


@pytest.mark.parametrize(
    "bbox",
    [
        [1, 2, 3],
        "10,20,100,50",
        [1, 2, 3, "x"],
        [0, 0, 0, 100],
        [0, 0, 100, -1],
    ],
)
def test_screenshot_rejects_invalid_bbox(
    monkeypatch: pytest.MonkeyPatch, bbox: Any
) -> None:
    _install_fake_grab(monkeypatch)

    response = _dispatch({"action": "screenshot", "bbox": bbox})

    assert response["ok"] is False
    assert response["error"] == "bad_request"


def test_screenshot_capture_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_grab(monkeypatch, raises=RuntimeError("X server unreachable"))

    response = _dispatch({"action": "screenshot"})

    assert response["ok"] is False
    assert response["error"] == "capture_failed"
    assert "X server unreachable" in response["detail"]


# ----- tests: UDS round-trip -----------------------------------------------


def test_screenshot_via_uds_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """実 UDS server を立てて end-to-end で base64 PNG bytes を往復させる。"""
    _install_fake_grab(monkeypatch, image=_FakeImage(320, 240))

    sock_path = tmp_path / "agent.sock"
    server = host_agent._bind_socket(sock_path)
    shutdown = host_agent._Shutdown()
    server_thread = threading.Thread(
        target=host_agent._accept_loop,
        args=(server, "/nonexistent/gale", shutdown),
        daemon=True,
    )
    server_thread.start()

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5.0)
            client.connect(str(sock_path))
            request = (json.dumps({"action": "screenshot"}) + "\n").encode("utf-8")
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            buf = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
        line, _, _ = bytes(buf).partition(b"\n")
        response = json.loads(line.decode("utf-8"))
    finally:
        shutdown.flag = True
        server.close()
        try:
            sock_path.unlink()
        except FileNotFoundError:
            pass
        server_thread.join(timeout=2.0)

    assert response["ok"] is True, response
    data = response["data"]
    assert data["width"] == 320
    assert data["height"] == 240
    decoded = base64.b64decode(data["png_b64"])
    assert decoded.startswith(_FAKE_PNG_MAGIC)
    assert len(decoded) == data["payload_bytes"]


# ----- tests: unrelated actions still work ---------------------------------


def test_unknown_action_returns_bad_request() -> None:
    response = _dispatch({"action": "nope"})
    assert response["ok"] is False
    assert response["error"] == "bad_request"
