"""Client for the Resonite IO ``Contact`` modality (friends / contacts).

Unary RPCs covering the in-game Contacts panel: listing contacts with
presence, fetching a single contact, searching the cloud for users,
adding / accepting / removing contacts.

The request-side :class:`ContactFilter` carries an extra ``ALL`` head the
wire enum spells ``UNSPECIFIED``; it is mapped by meaning. The response
enums :class:`ContactStatus` / :class:`OnlineStatus` are re-exported
straight from the generated wire types, since :class:`ContactInfo` (also
re-exported) populates its ``status`` / ``online_status`` fields with
them.
"""

from __future__ import annotations

import enum
import logging
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    AcceptRequestRequest,
    AcceptRequestResponse,
    AddContactRequest,
    AddContactResponse,
    ContactFilter as _WireContactFilter,
    ContactInfo,
    ContactStatus,
    ContactStub,
    GetContactRequest,
    GetContactResponse,
    ListContactsRequest,
    ListContactsResponse,
    OnlineStatus,
    RemoveContactRequest,
    SearchUsersRequest,
    SearchUsersResponse,
    UserSearchResult,
)

__all__ = [
    "AcceptRequestResponse",
    "AddContactResponse",
    "ContactClient",
    "ContactFilter",
    "ContactInfo",
    "ContactStatus",
    "GetContactResponse",
    "ListContactsResponse",
    "OnlineStatus",
    "SearchUsersResponse",
    "UserSearchResult",
]

_logger = logging.getLogger(__name__)


class ContactFilter(enum.Enum):
    """Contact-list filter for :meth:`ContactClient.list_contacts`.

    ``ALL`` = no filter (aliases the wire ``UNSPECIFIED`` head).
    """

    ALL = 0
    ACCEPTED = 1
    REQUESTS = 2


# ---------------------------------------------------------------------------
# Public <-> wire enum mapping
#
# The wire enum carries a ``UNSPECIFIED = 0`` slot the public enum spells
# ``ALL``; the members are mapped by meaning (name), aliasing the public
# head ALL -> UNSPECIFIED.
# ---------------------------------------------------------------------------

_CONTACT_FILTER_TO_WIRE: dict[ContactFilter, _WireContactFilter] = {
    ContactFilter.ALL: _WireContactFilter.UNSPECIFIED,
    ContactFilter.ACCEPTED: _WireContactFilter.ACCEPTED,
    ContactFilter.REQUESTS: _WireContactFilter.REQUESTS,
}


class ContactClient(_BaseClient[ContactStub]):
    """Async client for the Resonite IO ``Contact`` service over a UDS.

    Use as an async context manager so the gRPC channel closes
    deterministically.
    """

    _logger = _logger
    _log_label = "Contact"

    @override
    def _make_stub(self, channel: Channel) -> ContactStub:
        return ContactStub(channel)

    async def list_contacts(
        self,
        *,
        search: str = "",
        filter: ContactFilter = ContactFilter.ALL,
        include_hidden: bool = False,
    ) -> ListContactsResponse:
        """List contacts with presence (search / filter applied mod-side).

        By default this hides the same contacts the in-game dash Contacts
        tab hides (ignored / blocked); pass ``include_hidden=True`` to
        return every contact regardless.
        """
        stub = self._require_stub()
        request = ListContactsRequest(
            search=search,
            filter=_CONTACT_FILTER_TO_WIRE[filter],
            include_hidden=include_hidden,
        )
        return await stub.list_contacts(request)

    async def get_contact(self, user_id: str) -> GetContactResponse:
        """Fetch a single contact by ``user_id`` (``found=false`` if
        absent)."""
        stub = self._require_stub()
        return await stub.get_contact(GetContactRequest(user_id=user_id))

    async def search_users(
        self,
        query: str,
        *,
        exact_match: bool = False,
    ) -> SearchUsersResponse:
        """Search the cloud for users (no side effects; precedes ``add``).

        ``exact_match`` restricts to an exact username match.
        """
        stub = self._require_stub()
        request = SearchUsersRequest(query=query, exact_match=exact_match)
        return await stub.search_users(request)

    async def add_contact(
        self,
        user_id: str,
        *,
        username: str = "",
    ) -> AddContactResponse:
        """Add a user as a contact (``username`` resolved mod-side if
        empty)."""
        stub = self._require_stub()
        request = AddContactRequest(user_id=user_id, username=username)
        return await stub.add_contact(request)

    async def accept_request(self, user_id: str) -> AcceptRequestResponse:
        """Accept an incoming contact request from ``user_id``."""
        stub = self._require_stub()
        return await stub.accept_request(AcceptRequestRequest(user_id=user_id))

    async def remove_contact(self, user_id: str) -> None:
        """Remove a contact / reject a request from ``user_id``."""
        stub = self._require_stub()
        await stub.remove_contact(RemoveContactRequest(user_id=user_id))
