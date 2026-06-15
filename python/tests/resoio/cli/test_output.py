"""Unit tests for the CLI structured-output serializer ``resoio.cli.output``.

These tests pin the *spec* of the shared serializer that backs
``--format json`` (see the CLI structured-output plan), not any particular
implementation. The serializer is pure stdlib (no yaml) and exposes
``is_structured`` / ``to_jsonable`` / ``render`` / ``emit``.

The load-bearing invariants under test:

* enum -> ``.name`` string label (betterproto2 enums are ``IntEnum`` whose
  ``.value`` is a meaningless wire int; a bare ``json.dumps`` would emit that
  int, so the enum branch must run *before* the int branch);
* ``bool`` stays ``bool`` and is never coerced to ``0``/``1`` (bool is an int
  subclass, so its branch must run before the int branch too);
* ``tuple`` collapses to ``list``;
* dataclass / betterproto2 ``Message`` -> ``snake_case`` field names in
  declaration order (a regression guard against ``Message.to_dict()``'s
  camelCase output);
* large ``unix_nanos``-scale ints round-trip exactly;
* ``bytes`` and numpy arrays are rejected with ``TypeError`` (binary payloads
  are an explicit non-goal);
* ``render`` json output is ``indent=2``, ``ensure_ascii=False``, key order
  preserved, trailing newline; ``render`` human raises ``ValueError``.
"""

import dataclasses
import json

import numpy as np
import pytest

from resoio._generated.resonite_io.v1 import ServerInfo, ServerPlatform
from resoio.cli import output
from resoio.cursor import CursorState

# A unix_nanos-scale timestamp (~2023-11-14 in epoch ns). Larger than 2**53 so
# a lossy float round-trip would corrupt it; json must preserve it exactly.
LARGE_UNIX_NANOS = 1_700_000_000_000_000_000

# A non-ASCII world name, used to pin ensure_ascii=False (preserved verbatim).
JAPANESE_TEXT = "ホームワールド"


# --------------------------------------------------------------------------- #
# is_structured
# --------------------------------------------------------------------------- #


def test_is_structured_is_true_for_json():
    assert output.is_structured("json") is True


def test_is_structured_is_false_for_human():
    assert output.is_structured("human") is False


# --------------------------------------------------------------------------- #
# to_jsonable: scalars and the dispatch-order invariants
# --------------------------------------------------------------------------- #


def test_to_jsonable_passes_none_through():
    assert output.to_jsonable(None) is None


def test_to_jsonable_renders_enum_as_its_name_not_its_int_value():
    """Betterproto2 enums are IntEnums; the label is the contract, not the int.

    ``ServerPlatform.LINUX.value`` is ``3`` (a wire number). The serializer
    must emit the *name* ``"LINUX"`` so the int branch never sees the enum.
    """
    result = output.to_jsonable(ServerPlatform.LINUX)

    assert result == "LINUX"
    assert result == ServerPlatform.LINUX.name
    assert result != ServerPlatform.LINUX.value


def test_to_jsonable_keeps_true_as_bool_not_one():
    """Bool is an int subclass; it must survive as a bool, not become ``1``."""
    result = output.to_jsonable(True)

    assert result is True
    assert not isinstance(result, int) or result is True


def test_to_jsonable_keeps_false_as_bool_not_zero():
    result = output.to_jsonable(False)

    assert result is False


def test_to_jsonable_preserves_large_unix_nanos_int_exactly():
    """A ~1.7e18 timestamp must round-trip with no precision loss."""
    result = output.to_jsonable(LARGE_UNIX_NANOS)

    assert result == LARGE_UNIX_NANOS
    assert isinstance(result, int)


def test_to_jsonable_passes_float_through():
    assert output.to_jsonable(0.25) == 0.25


def test_to_jsonable_passes_str_through():
    assert output.to_jsonable(JAPANESE_TEXT) == JAPANESE_TEXT


# --------------------------------------------------------------------------- #
# to_jsonable: containers
# --------------------------------------------------------------------------- #


def test_to_jsonable_recurses_into_nested_dict():
    payload = {"outer": {"inner": ServerPlatform.LINUX, "flag": True}}

    assert output.to_jsonable(payload) == {"outer": {"inner": "LINUX", "flag": True}}


def test_to_jsonable_recurses_into_list():
    payload = [ServerPlatform.WINDOWS, ServerPlatform.OSX]

    assert output.to_jsonable(payload) == ["WINDOWS", "OSX"]


def test_to_jsonable_converts_tuple_to_list():
    result = output.to_jsonable((1, 2, 3))

    assert result == [1, 2, 3]
    assert isinstance(result, list)


def test_to_jsonable_converts_nested_tuple_to_list_and_recurses():
    """A color-style 4-tuple of values collapses to a list, recursively."""
    result = output.to_jsonable({"color": (0.1, 0.2, 0.3, True)})

    assert result == {"color": [0.1, 0.2, 0.3, True]}
    assert isinstance(result, dict)
    assert isinstance(result["color"], list)


def test_to_jsonable_stringifies_non_str_dict_keys():
    result = output.to_jsonable({1: "a"})

    assert result == {"1": "a"}


# --------------------------------------------------------------------------- #
# to_jsonable: wrapper dataclass -> snake_case in declaration order
# --------------------------------------------------------------------------- #


def test_to_jsonable_serializes_wrapper_dataclass_with_declared_field_names():
    """``CursorState`` is a frozen wrapper dataclass; field names are the
    contract, in declaration order, with ``held`` preserved as a bool."""
    state = CursorState(x=0.5, y=0.25, window_width=1920, window_height=1080, held=True)

    result = output.to_jsonable(state)

    assert result == {
        "x": 0.5,
        "y": 0.25,
        "window_width": 1920,
        "window_height": 1080,
        "held": True,
    }
    assert isinstance(result, dict)
    declared = [f.name for f in dataclasses.fields(CursorState)]
    assert list(result.keys()) == declared
    assert result["held"] is True


# --------------------------------------------------------------------------- #
# to_jsonable: betterproto2 Message -> snake_case (camelCase regression guard)
# --------------------------------------------------------------------------- #


def test_to_jsonable_serializes_proto_message_with_snake_case_field_names():
    """Betterproto2 ``Message`` is a ``@dataclass``; it must go through the
    dataclass path and yield snake_case proto field names in declaration order.

    ``Message.to_dict()`` would emit camelCase, which this guards.
    """
    info = ServerInfo(
        mod_version="1.2.3",
        engine_version="2024.1.1",
        platform=ServerPlatform.LINUX,
        is_wine=True,
        resonite_pid=4321,
        renderer_pid=8765,
    )

    result = output.to_jsonable(info)

    assert result == {
        "mod_version": "1.2.3",
        "engine_version": "2024.1.1",
        "platform": "LINUX",
        "is_wine": True,
        "resonite_pid": 4321,
        "renderer_pid": 8765,
    }


def test_to_jsonable_proto_message_does_not_emit_camelcase_keys():
    """Explicit camelCase regression guard: none of the keys are camelCase."""
    info = ServerInfo(
        mod_version="1.2.3",
        engine_version="2024.1.1",
        platform=ServerPlatform.LINUX,
        is_wine=False,
        resonite_pid=1,
        renderer_pid=2,
    )

    result = output.to_jsonable(info)
    assert isinstance(result, dict)

    for camel in ("modVersion", "engineVersion", "isWine", "resonitePid"):
        assert camel not in result


def test_to_jsonable_proto_message_keeps_enum_field_as_name():
    """An enum field inside a Message is rendered as its name, not its int."""
    info = ServerInfo(platform=ServerPlatform.OSX)

    result = output.to_jsonable(info)
    assert isinstance(result, dict)
    assert result["platform"] == "OSX"


# --------------------------------------------------------------------------- #
# to_jsonable: rejected binary types
# --------------------------------------------------------------------------- #


def test_to_jsonable_rejects_bytes_with_type_error():
    """Binary must never be embedded in a structured payload."""
    with pytest.raises(TypeError):
        output.to_jsonable(b"raw frame bytes")


def test_to_jsonable_rejects_bytearray_with_type_error():
    with pytest.raises(TypeError):
        output.to_jsonable(bytearray(b"raw frame bytes"))


def test_to_jsonable_rejects_numpy_array_with_type_error():
    """Numpy arrays fall through to the loud-failure fallback (no
    embedding)."""
    with pytest.raises(TypeError):
        output.to_jsonable(np.array([1, 2, 3]))


def test_to_jsonable_rejects_numpy_scalar_with_type_error():
    with pytest.raises(TypeError):
        output.to_jsonable(np.int64(5))


# --------------------------------------------------------------------------- #
# render: json formatting contract
# --------------------------------------------------------------------------- #


def test_render_json_round_trips_through_json_loads():
    state = CursorState(
        x=0.5, y=0.25, window_width=1920, window_height=1080, held=False
    )

    rendered = output.render(state, "json")

    assert json.loads(rendered) == {
        "x": 0.5,
        "y": 0.25,
        "window_width": 1920,
        "window_height": 1080,
        "held": False,
    }


def test_render_json_ends_with_a_single_trailing_newline():
    rendered = output.render({"a": 1}, "json")

    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")


def test_render_json_uses_two_space_indentation():
    rendered = output.render({"a": 1}, "json")

    # indent=2 puts the first key on its own line indented by two spaces.
    assert '\n  "a": 1' in rendered


def test_render_json_preserves_non_ascii_text_verbatim():
    """ensure_ascii=False keeps Japanese world names readable (not \\uXXXX)."""
    rendered = output.render({"name": JAPANESE_TEXT}, "json")

    assert JAPANESE_TEXT in rendered
    assert "\\u" not in rendered
    assert json.loads(rendered) == {"name": JAPANESE_TEXT}


def test_render_json_preserves_key_order_and_does_not_sort():
    """sort_keys=False: declaration/insertion order is the contract."""
    payload = {"zulu": 1, "alpha": 2, "mike": 3}

    rendered = output.render(payload, "json")

    assert list(json.loads(rendered).keys()) == ["zulu", "alpha", "mike"]


def test_render_json_preserves_large_unix_nanos_int_exactly():
    rendered = output.render({"unix_nanos": LARGE_UNIX_NANOS}, "json")

    assert json.loads(rendered)["unix_nanos"] == LARGE_UNIX_NANOS


def test_render_human_raises_value_error():
    """Human output never flows through render (it uses the legacy print path),
    so requesting it is a programming error."""
    with pytest.raises(ValueError):
        output.render({"a": 1}, "human")


# --------------------------------------------------------------------------- #
# emit: writes one document to stdout, swallows BrokenPipeError
# --------------------------------------------------------------------------- #


def test_emit_writes_rendered_json_to_stdout(
    capsys: pytest.CaptureFixture[str],
):
    payload = {"name": JAPANESE_TEXT, "unix_nanos": LARGE_UNIX_NANOS}

    output.emit(payload, "json")

    captured = capsys.readouterr()
    assert captured.out == output.render(payload, "json")
    assert captured.err == ""
    # Exactly one JSON document on stdout.
    assert json.loads(captured.out) == {
        "name": JAPANESE_TEXT,
        "unix_nanos": LARGE_UNIX_NANOS,
    }


def test_emit_swallows_broken_pipe_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """A closed downstream pipe (e.g. ``| head``) must not crash the CLI."""

    class _BrokenStdout:
        def write(self, _data: str) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            raise BrokenPipeError

    monkeypatch.setattr("sys.stdout", _BrokenStdout())

    # Must not raise.
    output.emit({"a": 1}, "json")
