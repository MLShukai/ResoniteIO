"""CLI surface tests for ``resoio contact <subcommand>``.

These tests pin the **argument-parsing + dispatch** contract of the
``contact`` command group:

    resoio contact list | get | search | add | accept | remove

Two complementary layers, matching ``cli/test_world.py`` /
``cli/test_session.py``:

1. Pure parser tests build the real parser via ``_build_parser`` and
   assert that each flag lands on the right namespace value and that the
   right leaf subcommand was selected. No I/O.
2. End-to-end dispatch tests stand up an in-process recording
   :class:`ContactBase` server over a real UDS and drive ``_amain`` so the
   *request actually sent on the wire* proves the CLI selected the correct
   RPC and mapped its flags into the request body. This avoids coupling to
   the names of the CLI's internal handler functions (which are not part
   of the spec) while still proving handler selection — and it does NOT
   mock grpclib internals (a real server / real client round-trip).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    AcceptRequestRequest,
    AcceptRequestResponse,
    AddContactRequest,
    AddContactResponse,
    ContactBase,
    ContactFilter as WireContactFilter,
    ContactInfo,
    ContactStatus as WireContactStatus,
    GetContactRequest,
    GetContactResponse,
    ListContactsRequest,
    ListContactsResponse,
    OnlineStatus as WireOnlineStatus,
    RemoveContactRequest,
    RemoveContactResponse,
    SearchUsersRequest,
    SearchUsersResponse,
    UserSearchResult,
)
from resoio.cli import _amain, _build_parser

# ===========================================================================
# Parser-only tests: group/leaf structure + flag -> namespace mapping.
# ===========================================================================


def test_contact_without_subcommand_is_rejected():
    """``contact`` is a command group, not a leaf — bare ``contact`` must error
    out (argparse exit code 2)."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["contact"])
    assert excinfo.value.code == 2


def test_list_collects_search_and_filter_flags():
    parser = _build_parser()
    args = parser.parse_args(
        ["contact", "list", "--search", "alice", "--filter", "requests"]
    )
    assert args.search == "alice"
    assert args.filter == "requests"


def test_list_filter_defaults_to_all():
    parser = _build_parser()
    args = parser.parse_args(["contact", "list"])
    assert args.filter == "all"


def test_list_search_defaults_to_empty_string():
    parser = _build_parser()
    args = parser.parse_args(["contact", "list"])
    assert args.search == ""


def test_list_filter_choices_reject_unknown_value():
    """``--filter`` is constrained to all/accepted/requests; an unknown value
    must be rejected at parse time rather than silently forwarded."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["contact", "list", "--filter", "nope"])
    assert excinfo.value.code == 2


def test_get_requires_positional_user_id():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["contact", "get"])
    assert excinfo.value.code == 2


def test_get_collects_user_id():
    parser = _build_parser()
    args = parser.parse_args(["contact", "get", "U-1"])
    assert args.user_id == "U-1"


def test_search_requires_positional_query():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["contact", "search"])
    assert excinfo.value.code == 2


def test_search_collects_query_and_exact_flag():
    parser = _build_parser()
    args = parser.parse_args(["contact", "search", "alice", "--exact"])
    assert args.query == "alice"
    assert args.exact_match is True


def test_search_exact_defaults_to_false():
    parser = _build_parser()
    args = parser.parse_args(["contact", "search", "alice"])
    assert args.exact_match is False


def test_add_requires_positional_user_id():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["contact", "add"])
    assert excinfo.value.code == 2


def test_add_collects_user_id_and_username():
    parser = _build_parser()
    args = parser.parse_args(["contact", "add", "U-1", "--username", "Alice"])
    assert args.user_id == "U-1"
    assert args.username == "Alice"


def test_add_username_defaults_to_empty_string():
    parser = _build_parser()
    args = parser.parse_args(["contact", "add", "U-1"])
    assert args.username == ""


def test_accept_requires_positional_user_id():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["contact", "accept"])
    assert excinfo.value.code == 2


def test_accept_collects_user_id():
    parser = _build_parser()
    args = parser.parse_args(["contact", "accept", "U-1"])
    assert args.user_id == "U-1"


def test_remove_requires_positional_user_id():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["contact", "remove"])
    assert excinfo.value.code == 2


def test_remove_collects_user_id():
    parser = _build_parser()
    args = parser.parse_args(["contact", "remove", "U-1"])
    assert args.user_id == "U-1"


@pytest.mark.parametrize(
    "argv",
    [
        ["contact", "list"],
        ["contact", "get", "U-1"],
        ["contact", "search", "alice"],
        ["contact", "add", "U-1"],
        ["contact", "accept", "U-1"],
        ["contact", "remove", "U-1"],
    ],
)
def test_socket_flag_accepted_on_each_leaf(argv: list[str], tmp_path: Path):
    """``-s/--socket`` is re-attached on each leaf (argparse does not inherit
    parent-subparser flags)."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    args = parser.parse_args([*argv, "-s", sock])
    assert args.socket == sock


@pytest.mark.parametrize(
    "argv",
    [
        ["contact", "list"],
        ["contact", "get", "U-1"],
        ["contact", "search", "alice"],
        ["contact", "add", "U-1"],
        ["contact", "accept", "U-1"],
        ["contact", "remove", "U-1"],
    ],
)
def test_format_flag_accepted_on_each_leaf(argv: list[str]):
    """Every contact leaf is a result-producing command, so ``--format`` is a
    valid flag on each (none is a side-effect-only carve-out)."""
    parser = _build_parser()
    args = parser.parse_args([*argv, "--format", "json"])
    assert args.format == "json"


def test_unknown_subcommand_is_rejected():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["contact", "bogus"])
    assert excinfo.value.code == 2


# ===========================================================================
# End-to-end dispatch: argv -> _amain -> in-process ContactBase server.
#
# A recording fake proves the CLI selected the right RPC and mapped flags
# into the request. Real UDS + real grpclib round-trip (no mocks).
# ===========================================================================


class _RecordingContact(ContactBase):
    """In-process Contact server capturing each request for assertion."""

    def __init__(self) -> None:
        self.contacts = [
            ContactInfo(
                user_id="U-1",
                username="alice",
                status=WireContactStatus.ACCEPTED,
                is_accepted=True,
                online_status=WireOnlineStatus.ONLINE,
                current_session_name="Hub",
            ),
            ContactInfo(
                user_id="U-2",
                username="bob",
                status=WireContactStatus.REQUESTED,
                is_contact_request=True,
                online_status=WireOnlineStatus.OFFLINE,
            ),
        ]
        self.list_requests: list[ListContactsRequest] = []
        self.get_requests: list[GetContactRequest] = []
        self.search_requests: list[SearchUsersRequest] = []
        self.add_requests: list[AddContactRequest] = []
        self.accept_requests: list[AcceptRequestRequest] = []
        self.remove_requests: list[RemoveContactRequest] = []

    async def list_contacts(self, message: ListContactsRequest) -> ListContactsResponse:
        self.list_requests.append(message)
        return ListContactsResponse(
            contacts=self.contacts,
            contact_count=1,
            request_count=1,
            list_loaded=True,
        )

    async def get_contact(self, message: GetContactRequest) -> GetContactResponse:
        self.get_requests.append(message)
        return GetContactResponse(
            contact=ContactInfo(
                user_id=message.user_id,
                username="alice",
                status=WireContactStatus.ACCEPTED,
                is_accepted=True,
            ),
            found=True,
        )

    async def search_users(self, message: SearchUsersRequest) -> SearchUsersResponse:
        self.search_requests.append(message)
        return SearchUsersResponse(
            results=[
                UserSearchResult(user_id="U-9", username="carol", is_verified=True)
            ]
        )

    async def add_contact(self, message: AddContactRequest) -> AddContactResponse:
        self.add_requests.append(message)
        return AddContactResponse(
            contact=ContactInfo(
                user_id=message.user_id,
                username=message.username or "alice",
                status=WireContactStatus.REQUESTED,
                is_contact_request=True,
            )
        )

    async def accept_request(
        self, message: AcceptRequestRequest
    ) -> AcceptRequestResponse:
        self.accept_requests.append(message)
        return AcceptRequestResponse(
            contact=ContactInfo(
                user_id=message.user_id,
                username="alice",
                status=WireContactStatus.ACCEPTED,
                is_accepted=True,
            )
        )

    async def remove_contact(
        self, message: RemoveContactRequest
    ) -> RemoveContactResponse:
        self.remove_requests.append(message)
        return RemoveContactResponse()


async def _run_contact(
    argv: list[str],
    socket_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
    args = _build_parser().parse_args(argv)
    return await _amain(args)


async def _serve(socket_path: Path) -> tuple[Server, _RecordingContact]:
    fake = _RecordingContact()
    server = Server([fake])
    await server.start(path=str(socket_path))
    return server, fake


# ---------------------------------------------------------------------------
# Dispatch: each leaf hits the right RPC with the mapped request body.
# ---------------------------------------------------------------------------


async def test_list_dispatch_maps_search_and_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "list", "--search", "ali", "--filter", "accepted"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.list_requests) == 1
    req = fake.list_requests[0]
    assert req.search == "ali"
    # CLI 'accepted' -> public ContactFilter.ACCEPTED -> wire ACCEPTED.
    assert req.filter == WireContactFilter.ACCEPTED
    # Other RPCs untouched — proves leaf selection, not a fallthrough.
    assert fake.search_requests == []
    out = capsys.readouterr().out
    assert "alice" in out
    assert "bob" in out


async def test_list_default_filter_dispatches_unspecified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(["contact", "list"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.list_requests) == 1
    # Default 'all' maps to the wire no-filter sentinel.
    assert fake.list_requests[0].filter == WireContactFilter.UNSPECIFIED


async def test_get_dispatch_sends_user_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(["contact", "get", "U-42"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.get_requests) == 1
    assert fake.get_requests[0].user_id == "U-42"
    assert "alice" in capsys.readouterr().out


async def test_search_dispatch_maps_query_and_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "search", "carol", "--exact"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.search_requests) == 1
    req = fake.search_requests[0]
    assert req.query == "carol"
    assert req.exact_match is True
    assert "carol" in capsys.readouterr().out


async def test_search_default_exact_is_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "search", "carol"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert fake.search_requests[0].exact_match is False


async def test_add_dispatch_maps_user_id_and_username(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "add", "U-7", "--username", "dave"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.add_requests) == 1
    req = fake.add_requests[0]
    assert req.user_id == "U-7"
    assert req.username == "dave"


async def test_add_without_username_dispatches_empty_username(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(["contact", "add", "U-7"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert fake.add_requests[0].username == ""


async def test_accept_dispatch_sends_user_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(["contact", "accept", "U-5"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.accept_requests) == 1
    assert fake.accept_requests[0].user_id == "U-5"


async def test_remove_dispatch_sends_user_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-contact.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_contact(["contact", "remove", "U-3"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.remove_requests) == 1
    assert fake.remove_requests[0].user_id == "U-3"


# ===========================================================================
# --format json: structured output on every leaf. betterproto enums emit
# their NAME (status -> "ACCEPTED", online_status -> "ONLINE"), per
# cli/output.to_jsonable.
# ===========================================================================


async def test_list_json_emits_contact_array_with_enum_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--format json`` on list emits a JSON array of the full ContactInfo
    messages; the status / online_status enums serialize to their member
    NAMES (not raw ints)."""
    socket_path = tmp_path / "rio-contact.sock"
    server, _fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "list", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert [c["username"] for c in payload] == ["alice", "bob"]
    # Enum fields surface as their member names, not integers.
    assert payload[0]["status"] == "ACCEPTED"
    assert payload[0]["online_status"] == "ONLINE"
    assert payload[0]["is_accepted"] is True
    assert payload[1]["status"] == "REQUESTED"
    assert payload[1]["online_status"] == "OFFLINE"
    assert payload[1]["is_contact_request"] is True


async def test_get_json_emits_contact_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-contact.sock"
    server, _fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "get", "U-1", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    # The CLI emits the inner ContactInfo object (or null when not found),
    # mirroring `world current` / `session` (inner payload, not the response
    # envelope). `found` is conveyed by object-vs-null, not a wrapper key.
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert payload["user_id"] == "U-1"
    assert payload["status"] == "ACCEPTED"


async def test_search_json_emits_results_array(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-contact.sock"
    server, _fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "search", "carol", "--format", "json"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload[0]["user_id"] == "U-9"
    assert payload[0]["username"] == "carol"
    assert payload[0]["is_verified"] is True


async def test_add_json_emits_contact_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-contact.sock"
    server, _fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "add", "U-7", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert payload["user_id"] == "U-7"
    assert payload["status"] == "REQUESTED"


async def test_accept_json_emits_contact_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-contact.sock"
    server, _fake = await _serve(socket_path)
    try:
        rc = await _run_contact(
            ["contact", "accept", "U-5", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert payload["user_id"] == "U-5"
    assert payload["status"] == "ACCEPTED"
    assert payload["is_accepted"] is True


async def test_list_json_preserves_non_ascii_username_verbatim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``ensure_ascii=False``: a Japanese username survives the json round-trip
    literally (not ``\\uXXXX`` escaped) and parses back to the same string."""
    socket_path = tmp_path / "rio-contact.sock"

    class _JapaneseContact(ContactBase):
        async def list_contacts(
            self, message: ListContactsRequest
        ) -> ListContactsResponse:
            return ListContactsResponse(
                contacts=[ContactInfo(user_id="U-1", username="ともだち")],
                contact_count=1,
            )

    server = Server([_JapaneseContact()])
    await server.start(path=str(socket_path))
    monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
    try:
        args = _build_parser().parse_args(["contact", "list", "--format", "json"])
        rc = await _amain(args)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    out = capsys.readouterr().out
    assert "ともだち" in out
    assert "\\u" not in out
    payload = json.loads(out)
    assert payload[0]["username"] == "ともだち"
