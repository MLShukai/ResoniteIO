"""Tests for the ``screenshot`` action of ``scripts/host_agent.py``.

host (Resonite を動かす GUI session) 専用の ``mss`` は container 内には
入っていないため、``sys.modules`` に fake mss を注入してから ``host_agent``
を import する。テスト範囲:

- 正常系: PNG が書かれ、response が ``{"path", "width", "height", "monitor"}``
  を返す
- パス検証: ``..`` セグメント / 絶対パス / 許容外文字 / 拡張子 / repo root
  脱出 を拒否する
- monitor index 範囲外 / 不正型 / bbox 不正型 を拒否する
- mss が未 install のケース (ImportError) を ``mss_unavailable`` で返す
- UDS round-trip: 実 socket 経由で正常 response が得られる
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import types
from pathlib import Path
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
        # mss.tools.to_png は zlib エンコードしか要求しないが、テストでは
        # to_png を mock するので中身は touch されない。
        self.rgb = b"\x00" * (width * height * 3)


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
    to_png_capture: dict[str, Any] | None = None,
) -> None:
    """``import mss`` / ``import mss.tools`` で fake が返るよう sys.modules を上書き。"""
    mss_mod = types.ModuleType("mss")

    def _mss_factory() -> _FakeMss:
        return fake

    mss_mod.mss = _mss_factory  # type: ignore[attr-defined]

    tools_mod = types.ModuleType("mss.tools")

    def _to_png(rgb: bytes, size: tuple[int, int], output: str) -> None:
        # 本物の zlib エンコードは不要 (テストではファイルの存在のみ確認)。
        Path(output).write_bytes(b"\x89PNG\r\n\x1a\n" + rgb[:8])
        if to_png_capture is not None:
            to_png_capture["rgb_len"] = len(rgb)
            to_png_capture["size"] = size
            to_png_capture["output"] = output

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


@pytest.fixture
def repo_root(tmp_path: Path):
    """``_REPO_ROOT`` を tmp_path に差し替えて、テスト終了時に元に戻す。"""
    original = host_agent._REPO_ROOT
    host_agent._set_repo_root(tmp_path)
    try:
        yield tmp_path.resolve()
    finally:
        host_agent._set_repo_root(original)


def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    return host_agent.handle_request(
        json.dumps(payload).encode("utf-8"),
        gale_bin="/nonexistent/gale",  # screenshot は gale を呼ばないので無害
    )


# ----- tests: success path --------------------------------------------------


def test_screenshot_writes_png_to_repo_relative_path(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeMss(grab_image=_FakeImage(640, 480))
    capture: dict[str, Any] = {}
    _install_fake_mss(monkeypatch, fake, to_png_capture=capture)

    response = _dispatch(
        {"action": "screenshot", "output": "tmp/e2e/desktop.png", "monitor": 1}
    )

    assert response["ok"] is True, response
    assert response["action"] == "screenshot"
    assert response["data"] == {
        "path": "tmp/e2e/desktop.png",
        "width": 640,
        "height": 480,
        "monitor": 1,
    }
    written = repo_root / "tmp" / "e2e" / "desktop.png"
    assert written.is_file()
    assert capture["output"] == str(written)
    # full monitor を grab したことの確認 (bbox 未指定)。
    assert fake.grab_calls == [fake.monitors[1]]


def test_screenshot_bbox_passes_region_to_mss(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeMss(grab_image=_FakeImage(100, 50))
    _install_fake_mss(monkeypatch, fake)

    response = _dispatch(
        {
            "action": "screenshot",
            "output": "shot.png",
            "monitor": 1,
            "bbox": [10, 20, 100, 50],
        }
    )

    assert response["ok"] is True, response
    assert fake.grab_calls == [{"left": 10, "top": 20, "width": 100, "height": 50}]
    assert response["data"]["width"] == 100
    assert response["data"]["height"] == 50


def test_screenshot_default_monitor_is_primary(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeMss()
    _install_fake_mss(monkeypatch, fake)

    response = _dispatch({"action": "screenshot", "output": "a.png"})

    assert response["ok"] is True, response
    assert response["data"]["monitor"] == 1


def test_screenshot_creates_parent_directories(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "output": "a/b/c/d/desktop.png"})

    assert response["ok"] is True, response
    assert (repo_root / "a" / "b" / "c" / "d" / "desktop.png").is_file()


# ----- tests: path validation ----------------------------------------------


@pytest.mark.parametrize(
    "bad_output",
    [
        "../outside.png",
        "tmp/../../escape.png",
        "/abs/path.png",
        "",
        "no_extension",
        "not_png.jpg",
        "has space.png",
        "weird*char.png",
    ],
)
def test_screenshot_rejects_invalid_output_paths(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch, bad_output: str
) -> None:
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "output": bad_output})

    assert response["ok"] is False, response
    assert response["error"] in {"invalid_output", "bad_request"}


def test_screenshot_rejects_non_string_output(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "output": 12345})

    assert response["ok"] is False
    assert response["error"] == "bad_request"


# ----- tests: monitor / bbox validation ------------------------------------


def test_screenshot_rejects_monitor_out_of_range(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # mss.monitors は [合成, primary] の 2 件を返す fake。 index 5 は範囲外。
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "output": "a.png", "monitor": 5})

    assert response["ok"] is False
    assert response["error"] == "invalid_monitor"


def test_screenshot_rejects_negative_monitor(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "output": "a.png", "monitor": -1})

    assert response["ok"] is False
    assert response["error"] == "invalid_monitor"


def test_screenshot_rejects_non_int_monitor(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch(
        {"action": "screenshot", "output": "a.png", "monitor": "primary"}
    )

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
    repo_root: Path, monkeypatch: pytest.MonkeyPatch, bbox: Any
) -> None:
    _install_fake_mss(monkeypatch, _FakeMss())

    response = _dispatch({"action": "screenshot", "output": "a.png", "bbox": bbox})

    assert response["ok"] is False
    assert response["error"] == "bad_request"


def test_screenshot_capture_failure_returns_error(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeMss(grab_raises=RuntimeError("X server unreachable"))
    _install_fake_mss(monkeypatch, fake)

    response = _dispatch({"action": "screenshot", "output": "a.png"})

    assert response["ok"] is False
    assert response["error"] == "capture_failed"
    assert "X server unreachable" in response["detail"]


def test_screenshot_returns_error_when_mss_not_installed(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _uninstall_mss(monkeypatch)

    response = _dispatch({"action": "screenshot", "output": "a.png"})

    assert response["ok"] is False
    assert response["error"] == "mss_unavailable"


# ----- tests: UDS round-trip -----------------------------------------------


def test_screenshot_via_uds_roundtrip(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """実 UDS server を立てて end-to-end で 1 リクエスト交換する。"""
    fake = _FakeMss(grab_image=_FakeImage(320, 240))
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
                json.dumps(
                    {
                        "action": "screenshot",
                        "output": "snap.png",
                        "monitor": 1,
                    }
                )
                + "\n"
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
    assert response["data"]["path"] == "snap.png"
    assert response["data"]["width"] == 320
    assert response["data"]["height"] == 240
    assert (repo_root / "snap.png").is_file()


# ----- tests: unrelated actions still work ---------------------------------


def test_unknown_action_returns_bad_request(repo_root: Path) -> None:
    response = _dispatch({"action": "nope"})
    assert response["ok"] is False
    assert response["error"] == "bad_request"
