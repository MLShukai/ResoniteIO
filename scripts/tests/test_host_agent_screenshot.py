"""Tests for the ``screenshot`` action of ``scripts/host_agent.py``.

host (Resonite を動かす GUI session) 専用の ``mss`` は container 内には
入っていないため、``sys.modules`` に fake mss を注入してから ``host_agent``
を import する。

新 protocol (S3): host_agent は file system に書かず、PNG bytes を base64
にして response data に乗せる。output フィールドは廃止 (旧 client 互換の
ため request に存在しても silently ignore)。

テスト範囲:
- 正常系: response の ``png_b64`` を decode した bytes が fake to_png の
  返した bytes と一致し、``payload_bytes`` が len(bytes) と一致する
- bbox / monitor 指定が mss.grab に正しく渡される
- monitor index 範囲外 / 不正型 / bbox 不正型 を拒否する
- mss が未 install のケース (ImportError) を ``mss_unavailable`` で返す
- 旧 protocol の ``output`` フィールドが request にあっても成功する
  (silently ignored、後方互換)
- to_png が bytes でないものを返した場合は ``capture_failed`` で返す
- UDS round-trip: 実 socket 経由で base64 PNG bytes が往復する
"""

from __future__ import annotations

import base64
import json
import socket
import sys
import threading
import types
from typing import Any

import pytest

# host_agent は scripts/tests/conftest.py の sys.path 注入で import 可能。
# fake mss は host_agent より先に inject する必要はない (lazy import なので
# cmd_screenshot 呼び出し時に sys.modules から拾われる)。
import host_agent  # noqa: E402  # pyright: ignore[reportMissingImports]


# ----- fake mss -------------------------------------------------------------


class _FakeImage:
    def __init__(self, width: int, height: int) -> None:
        self.size = (width, height)
        # rgb は payload 検証用。長さが (W*H*3) に一致することだけ確認する
        # 用途で、内容は固定パターンで埋めてもよい。
        self.rgb = bytes((i * 37) & 0xFF for i in range(width * height * 3))


_FAKE_PNG_PREFIX = b"\x89PNG\r\n\x1a\n"

# Sentinel for "use default" — distinct from any legal user-supplied value.
_DEFAULT = object()


class _FakeMss:
    """``with mss.mss() as sct: sct.grab(...)`` を最小限再現する。"""

    def __init__(
        self,
        monitors: list[dict[str, int]] | None = None,
        grab_image: _FakeImage | None = None,
        grab_raises: Exception | None = None,
    ) -> None:
        # mss の monitors[0] は全モニタ合成、[1] が primary。
        self.monitors: list[dict[str, int]] = monitors or [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]
        self._grab_image = grab_image or _FakeImage(1920, 1080)
        self._grab_raises = grab_raises
        self.grab_calls: list[Any] = []

    def __enter__(self) -> _FakeMss:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def grab(self, region: Any) -> _FakeImage:
        self.grab_calls.append(region)
        if self._grab_raises is not None:
            raise self._grab_raises
        return self._grab_image


def _install_fake_mss(
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakeMss,
    *,
    to_png_return: Any = _DEFAULT,
) -> None:
    """``import mss`` / ``import mss.tools`` で fake が返るよう sys.modules を上書き。

    ``to_png_return`` を指定しなければ ``_FAKE_PNG_PREFIX + rgb[:32]`` を返す。
    None / 非 bytes など特定の戻り値を試したいときは明示的に渡す。
    """
    mss_mod = types.ModuleType("mss")

    def _mss_factory() -> _FakeMss:
        return fake

    mss_mod.mss = _mss_factory  # type: ignore[attr-defined]

    tools_mod = types.ModuleType("mss.tools")

    def _to_png(rgb: bytes, size: tuple[int, int], output: Any = None, **_: Any) -> Any:
        if to_png_return is _DEFAULT:
            # mss 10.2.0 と同じく ``output=None`` で bytes 返却を模す。
            return _FAKE_PNG_PREFIX + bytes(rgb[:32])
        return to_png_return

    tools_mod.to_png = _to_png  # type: ignore[attr-defined]
    mss_mod.tools = tools_mod  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "mss", mss_mod)
    monkeypatch.setitem(sys.modules, "mss.tools", tools_mod)


def _uninstall_mss(monkeypatch: pytest.MonkeyPatch) -> None:
    """``import mss`` が ImportError になるよう sys.modules を覆す。

    ``sys.modules`` に ``None`` を入れると ``import`` 側で ImportError になる
    (CPython の import システム仕様)。
    """
    monkeypatch.setitem(sys.modules, "mss", None)
    monkeypatch.setitem(sys.modules, "mss.tools", None)


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
    fake = _FakeMss(grab_image=_FakeImage(640, 480))
    _install_fake_mss(monkeypatch, fake)

    response = _dispatch({"action": "screenshot", "monitor": 1})

    assert response["ok"] is True, response
    assert response["action"] == "screenshot"
    data = response["data"]
    assert set(data.keys()) == {
        "png_b64",
        "width",
        "height",
        "monitor",
        "payload_bytes",
    }
    assert data["width"] == 640
    assert data["height"] == 480
    assert data["monitor"] == 1

    decoded = base64.b64decode(data["png_b64"])
    assert decoded.startswith(_FAKE_PNG_PREFIX)
    assert len(decoded) == data["payload_bytes"]
    # full monitor を grab したことの確認 (bbox 未指定)。
    assert fake.grab_calls == [fake.monitors[1]]


def test_screenshot_bbox_passes_region_to_mss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeMss(grab_image=_FakeImage(100, 50))
    _install_fake_mss(monkeypatch, fake)

    response = _dispatch(
        {
            "action": "screenshot",
            "monitor": 1,
            "bbox": [10, 20, 100, 50],
        }
    )

    assert response["ok"] is True, response
    assert fake.grab_calls == [{"left": 10, "top": 20, "width": 100, "height": 50}]
    assert response["data"]["width"] == 100
    assert response["data"]["height"] == 50


def test_screenshot_default_monitor_is_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeMss()
    _install_fake_mss(monkeypatch, fake)

    response = _dispatch({"action": "screenshot"})

    assert response["ok"] is True, response
    assert response["data"]["monitor"] == 1


def test_screenshot_ignores_legacy_output_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧 client は ``output`` を送ってくるが新 protocol では silently ignore。"""
    fake = _FakeMss(grab_image=_FakeImage(320, 240))
    _install_fake_mss(monkeypatch, fake)

    # ``output`` が validation を引き起こす絶対 path / `..` 形式でも、
    # 新 protocol では一切参照されないので成功して PNG が返るべき。
    response = _dispatch(
        {
            "action": "screenshot",
            "output": "/absolute/garbage/path.png",
            "monitor": 1,
        }
    )

    assert response["ok"] is True, response
    assert "png_b64" in response["data"]
    # response の data に旧 ``path`` フィールドは無いこと。
    assert "path" not in response["data"]


# ----- tests: monitor / bbox validation ------------------------------------


def test_screenshot_rejects_monitor_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # mss.monitors は [合成, primary] の 2 件を返す fake。 index 5 は範囲外。
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "monitor": 5})

    assert response["ok"] is False
    assert response["error"] == "invalid_monitor"


def test_screenshot_rejects_negative_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "monitor": -1})

    assert response["ok"] is False
    assert response["error"] == "invalid_monitor"


def test_screenshot_rejects_non_int_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "monitor": "primary"})

    assert response["ok"] is False
    assert response["error"] == "bad_request"


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
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "bbox": bbox})

    assert response["ok"] is False
    assert response["error"] == "bad_request"


def test_screenshot_capture_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeMss(grab_raises=RuntimeError("X server unreachable"))
    _install_fake_mss(monkeypatch, fake)

    response = _dispatch({"action": "screenshot"})

    assert response["ok"] is False
    assert response["error"] == "capture_failed"
    assert "X server unreachable" in response["detail"]


def test_screenshot_to_png_returning_non_bytes_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mss.tools.to_png が None (file write 経路) を返してきた場合は failure 扱い。"""
    _install_fake_mss(monkeypatch, _FakeMss(), to_png_return=None)

    response = _dispatch({"action": "screenshot"})

    assert response["ok"] is False
    assert response["error"] == "capture_failed"


def test_screenshot_returns_error_when_mss_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _uninstall_mss(monkeypatch)

    response = _dispatch({"action": "screenshot"})

    assert response["ok"] is False
    assert response["error"] == "mss_unavailable"


# ----- tests: UDS round-trip -----------------------------------------------


def test_screenshot_via_uds_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """実 UDS server を立てて end-to-end で base64 PNG bytes を往復させる。"""
    fake_img = _FakeImage(320, 240)
    fake = _FakeMss(grab_image=fake_img)
    _install_fake_mss(monkeypatch, fake)

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
            request = (
                json.dumps({"action": "screenshot", "monitor": 1}) + "\n"
            ).encode("utf-8")
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
    assert data["monitor"] == 1
    decoded = base64.b64decode(data["png_b64"])
    assert decoded.startswith(_FAKE_PNG_PREFIX)
    assert len(decoded) == data["payload_bytes"]


# ----- tests: unrelated actions still work ---------------------------------


def test_unknown_action_returns_bad_request() -> None:
    response = _dispatch({"action": "nope"})
    assert response["ok"] is False
    assert response["error"] == "bad_request"
