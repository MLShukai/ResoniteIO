"""Contact client tests — real grpclib round-trip over a tmp_path UDS.

A real ``grpclib.server.Server`` is started on a real Unix Domain Socket with
an in-process fake ``ContactBase`` servicer; ``ContactClient`` is pointed at
it via ``RESONITE_IO_SOCKET``. These tests assert the contracts of
``ContactClient``:

  1. the read methods return the GENERATED proto types directly (no
     hand-written mirror dataclasses), so ``list_contacts`` surfaces the
     generated ``ListContactsResponse`` with its ``contacts`` list of
     ``ContactInfo`` (presence / status enums riding back verbatim) plus the
     ``contact_count`` / ``request_count`` / ``list_loaded`` scalars, and
     ``get_contact`` / ``search_users`` / ``add_contact`` / ``accept_request``
     return their generated responses; and
  2. public request args -> wire request mapping, especially the
     public-enum to wire-enum translation (public ``ContactFilter.ALL`` is
     sent as wire ``ContactFilter.UNSPECIFIED``), asserted on the request the
     fake captures over the real socket.

Per testing-strategy: no mocking of grpclib / asyncio / betterproto internals
— the only fake is the self-owned ``ContactBase`` servicer surface. The output
types (``ContactInfo`` / ``UserSearchResult`` and the response messages) are
the generated proto types, re-exported from ``resoio.contact``; field values
are asserted via their generated field names.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import grpclib
import pytest
from grpclib.const import Status

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
from resoio.contact import (
    ContactClient,
    ContactFilter,
    ContactStatus,
    OnlineStatus,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


# ---------------------------------------------------------------------------
# In-process fake (self-owned ContactBase ABC).
# ---------------------------------------------------------------------------


class _FakeContact(ContactBase):
    """In-process fake servicer.

    Records every request it receives so the test can assert the wire
    request the client built, and returns canned responses configured
    per-test.
    """

    def __init__(
        self,
        *,
        list_response: ListContactsResponse | None = None,
        get_response: GetContactResponse | None = None,
        search_response: SearchUsersResponse | None = None,
        add_contact: ContactInfo | None = None,
        accept_contact: ContactInfo | None = None,
        error: grpclib.GRPCError | None = None,
    ) -> None:
        self.list_requests: list[ListContactsRequest] = []
        self.get_requests: list[GetContactRequest] = []
        self.search_requests: list[SearchUsersRequest] = []
        self.add_requests: list[AddContactRequest] = []
        self.accept_requests: list[AcceptRequestRequest] = []
        self.remove_requests: list[RemoveContactRequest] = []

        self._list_response = list_response or ListContactsResponse()
        self._get_response = get_response or GetContactResponse()
        self._search_response = search_response or SearchUsersResponse()
        self._add_contact = add_contact
        self._accept_contact = accept_contact
        self._error = error

    async def list_contacts(self, message: ListContactsRequest) -> ListContactsResponse:
        self.list_requests.append(message)
        if self._error is not None:
            raise self._error
        return self._list_response

    async def get_contact(self, message: GetContactRequest) -> GetContactResponse:
        self.get_requests.append(message)
        return self._get_response

    async def search_users(self, message: SearchUsersRequest) -> SearchUsersResponse:
        self.search_requests.append(message)
        return self._search_response

    async def add_contact(self, message: AddContactRequest) -> AddContactResponse:
        self.add_requests.append(message)
        return AddContactResponse(contact=self._add_contact)

    async def accept_request(
        self, message: AcceptRequestRequest
    ) -> AcceptRequestResponse:
        self.accept_requests.append(message)
        return AcceptRequestResponse(contact=self._accept_contact)

    async def remove_contact(
        self, message: RemoveContactRequest
    ) -> RemoveContactResponse:
        self.remove_requests.append(message)
        return RemoveContactResponse()


# ===========================================================================
# list_contacts: returns the generated ListContactsResponse; request mapping.
# ===========================================================================


class TestListContacts:
    async def test_returns_generated_response_with_contacts_and_counts(
        self, uds_server: UdsServer
    ):
        contact = ContactInfo(
            user_id="U-friend",
            username="Friend",
            alternate_usernames=["FriendOld", "FriendAlt"],
            status=WireContactStatus.ACCEPTED,
            is_accepted=True,
            is_contact_request=False,
            online_status=WireOnlineStatus.ONLINE,
            current_session_name="Hub",
            current_session_access_level="Anyone",
        )
        fake = _FakeContact(
            list_response=ListContactsResponse(
                contacts=[contact],
                contact_count=12,
                request_count=3,
                list_loaded=True,
            )
        )
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.list_contacts()

        # The method returns the generated ListContactsResponse directly.
        assert isinstance(response, ListContactsResponse)
        assert response.contact_count == 12
        assert response.request_count == 3
        assert response.list_loaded is True
        # Repeated fields surface as list (generated proto type), not tuple.
        assert isinstance(response.contacts, list)
        assert len(response.contacts) == 1

        got = response.contacts[0]
        assert isinstance(got, ContactInfo)
        assert got.user_id == "U-friend"
        assert got.username == "Friend"
        assert got.alternate_usernames == ["FriendOld", "FriendAlt"]
        # Status / presence enums ride back as the wire enum values verbatim.
        assert got.status == WireContactStatus.ACCEPTED
        assert got.is_accepted is True
        assert got.is_contact_request is False
        assert got.online_status == WireOnlineStatus.ONLINE
        assert got.current_session_name == "Hub"
        assert got.current_session_access_level == "Anyone"

    async def test_presence_offline_contact_carries_offline_status(
        self, uds_server: UdsServer
    ):
        """A contact that is offline reports ``OnlineStatus.OFFLINE`` (a
        distinct non-default member) and an empty current-session name."""
        fake = _FakeContact(
            list_response=ListContactsResponse(
                contacts=[
                    ContactInfo(
                        user_id="U-away",
                        username="Away",
                        online_status=WireOnlineStatus.OFFLINE,
                    )
                ],
                contact_count=1,
            )
        )
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.list_contacts()

        assert response.contacts[0].online_status == WireOnlineStatus.OFFLINE
        assert response.contacts[0].current_session_name == ""

    async def test_pending_request_contact_carries_requested_status(
        self, uds_server: UdsServer
    ):
        """An incoming friend request is a ContactInfo with
        ``is_contact_request=True`` and ``ContactStatus.REQUESTED``, not yet
        accepted."""
        fake = _FakeContact(
            list_response=ListContactsResponse(
                contacts=[
                    ContactInfo(
                        user_id="U-pending",
                        username="Pending",
                        status=WireContactStatus.REQUESTED,
                        is_accepted=False,
                        is_contact_request=True,
                    )
                ],
                request_count=1,
            )
        )
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.list_contacts()

        got = response.contacts[0]
        assert got.status == WireContactStatus.REQUESTED
        assert got.is_contact_request is True
        assert got.is_accepted is False

    async def test_empty_contact_list_yields_empty_list_and_zero_counts(
        self, uds_server: UdsServer
    ):
        fake = _FakeContact(list_response=ListContactsResponse())
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.list_contacts()

        assert response.contacts == []
        assert response.contact_count == 0
        assert response.request_count == 0
        assert response.list_loaded is False

    async def test_request_defaults_carry_empty_search_and_unspecified_filter(
        self, uds_server: UdsServer
    ):
        """No args: an empty search and the ALL filter (= no filter) ride on the
        wire as ``search=""`` and wire ``ContactFilter.UNSPECIFIED``."""
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts()

        assert len(fake.list_requests) == 1
        wire = fake.list_requests[0]
        assert wire.search == ""
        # Public ALL is the "no filter" head; it must travel as wire
        # UNSPECIFIED, NOT collide with ACCEPTED/REQUESTS (which share the
        # numeric 1/2 slots publicly).
        assert wire.filter == WireContactFilter.UNSPECIFIED

    async def test_request_carries_search_verbatim(self, uds_server: UdsServer):
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts(search="alice")

        assert len(fake.list_requests) == 1
        assert fake.list_requests[0].search == "alice"

    async def test_request_defaults_include_hidden_false(self, uds_server: UdsServer):
        """No ``include_hidden`` arg: the request rides with
        ``include_hidden=False`` so the mod applies its default dash-hidden
        (None/Ignored/Blocked) exclusion."""
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts()

        assert len(fake.list_requests) == 1
        assert fake.list_requests[0].include_hidden is False

    async def test_request_carries_include_hidden_true_when_requested(
        self, uds_server: UdsServer
    ):
        """``include_hidden=True`` rides on the wire so the mod returns every
        contact, including the dash-hidden (ignored / blocked) ones."""
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts(include_hidden=True)

        assert fake.list_requests[0].include_hidden is True

    async def test_response_surfaces_is_hidden_flag(self, uds_server: UdsServer):
        """``ContactInfo.is_hidden`` reflects whether the dash Contacts tab
        hides this contact (engine ``Contact.ShouldBeHidden``); it rides back
        verbatim so the caller can tell a blocked/ignored contact apart from a
        visible one."""
        fake = _FakeContact(
            list_response=ListContactsResponse(
                contacts=[
                    ContactInfo(user_id="U-visible", username="Visible"),
                    ContactInfo(
                        user_id="U-blocked", username="Blocked", is_hidden=True
                    ),
                ],
            )
        )
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.list_contacts(include_hidden=True)

        visible = next(c for c in response.contacts if c.user_id == "U-visible")
        blocked = next(c for c in response.contacts if c.user_id == "U-blocked")
        assert visible.is_hidden is False
        assert blocked.is_hidden is True

    async def test_request_maps_accepted_filter(self, uds_server: UdsServer):
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts(filter=ContactFilter.ACCEPTED)

        assert fake.list_requests[0].filter == WireContactFilter.ACCEPTED

    async def test_request_maps_requests_filter(self, uds_server: UdsServer):
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts(filter=ContactFilter.REQUESTS)

        assert fake.list_requests[0].filter == WireContactFilter.REQUESTS

    async def test_propagates_grpc_error_from_server(self, uds_server: UdsServer):
        """A server-side ``GRPCError`` (e.g. the bridge not ready) propagates
        to the caller rather than being swallowed into an empty response."""
        fake = _FakeContact(
            error=grpclib.GRPCError(Status.FAILED_PRECONDITION, "contacts not ready")
        )
        await uds_server(fake)
        async with ContactClient() as client:
            with pytest.raises(grpclib.GRPCError) as excinfo:
                await client.list_contacts()
        assert excinfo.value.status is Status.FAILED_PRECONDITION

    async def test_raises_when_not_connected(self):
        client = ContactClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_contacts()


# ===========================================================================
# Public ContactFilter -> wire mapping (direct unit check).
# ===========================================================================


class TestContactFilterMapping:
    """The public ``ContactFilter`` is offset from the wire enum by the
    ``UNSPECIFIED = 0`` slot, so the mapping is by meaning (name), not numeric
    value.

    Pin every member's translation directly so a future renumber that
    happened to keep numbers aligned still surfaces here.
    """

    async def test_all_maps_to_unspecified(self, uds_server: UdsServer):
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts(filter=ContactFilter.ALL)
        assert fake.list_requests[0].filter == WireContactFilter.UNSPECIFIED

    async def test_accepted_maps_to_accepted(self, uds_server: UdsServer):
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts(filter=ContactFilter.ACCEPTED)
        assert fake.list_requests[0].filter == WireContactFilter.ACCEPTED

    async def test_requests_maps_to_requests(self, uds_server: UdsServer):
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.list_contacts(filter=ContactFilter.REQUESTS)
        assert fake.list_requests[0].filter == WireContactFilter.REQUESTS

    def test_public_status_enum_is_the_wire_status_enum(self):
        """``ContactStatus`` re-exported from ``resoio.contact`` is the
        generated wire enum (response statuses surface untranslated), so the
        public symbol is the same object as the wire one."""
        assert ContactStatus is WireContactStatus

    def test_public_online_status_enum_is_the_wire_online_status_enum(self):
        assert OnlineStatus is WireOnlineStatus


# ===========================================================================
# get_contact: found true / false.
# ===========================================================================


class TestGetContact:
    async def test_found_returns_response_with_contact(self, uds_server: UdsServer):
        fake = _FakeContact(
            get_response=GetContactResponse(
                contact=ContactInfo(
                    user_id="U-1",
                    username="Alice",
                    status=WireContactStatus.ACCEPTED,
                    is_accepted=True,
                ),
                found=True,
            )
        )
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.get_contact("U-1")

        assert isinstance(response, GetContactResponse)
        assert response.found is True
        assert response.contact is not None
        assert response.contact.user_id == "U-1"
        assert response.contact.username == "Alice"
        # The looked-up user id rode on the wire verbatim.
        assert len(fake.get_requests) == 1
        assert fake.get_requests[0].user_id == "U-1"

    async def test_not_found_returns_found_false(self, uds_server: UdsServer):
        """A user that is not a contact reports ``found=False``; the caller
        must be able to distinguish "no such contact" from a populated
        default."""
        fake = _FakeContact(get_response=GetContactResponse(found=False))
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.get_contact("U-missing")

        assert response.found is False
        assert fake.get_requests[0].user_id == "U-missing"

    async def test_raises_when_not_connected(self):
        client = ContactClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_contact("U-1")


# ===========================================================================
# search_users: results + is_verified; exact_match request mapping.
# ===========================================================================


class TestSearchUsers:
    async def test_returns_response_with_results_and_verified_flag(
        self, uds_server: UdsServer
    ):
        fake = _FakeContact(
            search_response=SearchUsersResponse(
                results=[
                    UserSearchResult(
                        user_id="U-verified", username="Verified", is_verified=True
                    ),
                    UserSearchResult(
                        user_id="U-plain", username="Plain", is_verified=False
                    ),
                ]
            )
        )
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.search_users("ver")

        assert isinstance(response, SearchUsersResponse)
        assert isinstance(response.results, list)
        assert len(response.results) == 2
        first = response.results[0]
        assert isinstance(first, UserSearchResult)
        assert first.user_id == "U-verified"
        assert first.username == "Verified"
        assert first.is_verified is True
        assert response.results[1].is_verified is False

    async def test_request_carries_query_and_defaults_exact_match_false(
        self, uds_server: UdsServer
    ):
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.search_users("alice")

        assert len(fake.search_requests) == 1
        wire = fake.search_requests[0]
        assert wire.query == "alice"
        # Default is a fuzzy search: exact_match stays False unless requested.
        assert wire.exact_match is False

    async def test_request_carries_exact_match_true_when_requested(
        self, uds_server: UdsServer
    ):
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            await client.search_users("alice", exact_match=True)

        assert fake.search_requests[0].exact_match is True

    async def test_empty_results_yield_empty_list(self, uds_server: UdsServer):
        fake = _FakeContact(search_response=SearchUsersResponse(results=[]))
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.search_users("nobody")

        assert response.results == []

    async def test_raises_when_not_connected(self):
        client = ContactClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.search_users("alice")


# ===========================================================================
# add_contact: user_id always rides; username optional.
# ===========================================================================


class TestAddContact:
    async def test_request_carries_user_id_and_empty_username_by_default(
        self, uds_server: UdsServer
    ):
        fake = _FakeContact(add_contact=ContactInfo(user_id="U-1", username="Alice"))
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.add_contact("U-1")

        assert isinstance(response, AddContactResponse)
        assert len(fake.add_requests) == 1
        wire = fake.add_requests[0]
        assert wire.user_id == "U-1"
        # No username given: an empty string rides (the server resolves by id).
        assert wire.username == ""

    async def test_request_carries_username_when_given(self, uds_server: UdsServer):
        fake = _FakeContact(add_contact=ContactInfo(user_id="U-1", username="Alice"))
        await uds_server(fake)
        async with ContactClient() as client:
            await client.add_contact("U-1", username="Alice")

        wire = fake.add_requests[0]
        assert wire.user_id == "U-1"
        assert wire.username == "Alice"

    async def test_returns_response_with_resulting_contact(self, uds_server: UdsServer):
        fake = _FakeContact(
            add_contact=ContactInfo(
                user_id="U-1",
                username="Alice",
                status=WireContactStatus.REQUESTED,
                is_contact_request=True,
            )
        )
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.add_contact("U-1")

        assert response.contact is not None
        assert response.contact.user_id == "U-1"
        assert response.contact.status == WireContactStatus.REQUESTED

    async def test_raises_when_not_connected(self):
        client = ContactClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.add_contact("U-1")


# ===========================================================================
# accept_request / remove_contact: round-trip + request mapping.
# ===========================================================================


class TestAcceptRequest:
    async def test_request_carries_user_id_and_returns_accepted_contact(
        self, uds_server: UdsServer
    ):
        fake = _FakeContact(
            accept_contact=ContactInfo(
                user_id="U-1",
                username="Alice",
                status=WireContactStatus.ACCEPTED,
                is_accepted=True,
            )
        )
        await uds_server(fake)
        async with ContactClient() as client:
            response = await client.accept_request("U-1")

        assert isinstance(response, AcceptRequestResponse)
        assert len(fake.accept_requests) == 1
        assert fake.accept_requests[0].user_id == "U-1"
        assert response.contact is not None
        assert response.contact.is_accepted is True
        assert response.contact.status == WireContactStatus.ACCEPTED

    async def test_raises_when_not_connected(self):
        client = ContactClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.accept_request("U-1")


class TestRemoveContact:
    async def test_request_carries_user_id_and_returns_none(
        self, uds_server: UdsServer
    ):
        """``remove_contact`` is a side-effect RPC with an empty wire response;
        the client returns None (no value object to surface)."""
        fake = _FakeContact()
        await uds_server(fake)
        async with ContactClient() as client:
            result = await client.remove_contact("U-1")

        assert result is None
        assert len(fake.remove_requests) == 1
        assert fake.remove_requests[0].user_id == "U-1"

    async def test_raises_when_not_connected(self):
        client = ContactClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.remove_contact("U-1")
