"""E2E: drive the Contact modality against a live Resonite client.

READ-ONLY scenario. This exercises the real ``ContactClient`` over the live
UDS through ``FrooxEngineContactBridge``: list the signed-in account's
contacts, look one up by id (``get_contact``), and run a user search
(``search_users``). It pins the read surface end to end (presence /
status enums riding back from the engine, the ``ContactFilter`` request
mapping reaching the cloud, ``found`` true/false).

IRREVERSIBLE WRITE RPCs ARE DELIBERATELY NEVER CALLED HERE.
``add_contact`` / ``accept_request`` / ``remove_contact`` mutate the real
cloud social graph of the signed-in account (sending / accepting / deleting
friend relationships with real other users). There is no safe, reversible
fixture for that against a live account, so this e2e covers the read path
only; the mutation RPCs are validated by the unit round-trip tests
(``tests/resoio/test_contact.py``) against an in-process fake.

When the account has no contacts (a fresh / empty cloud) the list/get steps
``pytest.skip`` rather than fail, since a non-empty contact list is an
account-state precondition the test cannot create without a write.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live, signed-in Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import grpclib
import pytest
from grpclib.const import Status

from resoio.contact import ContactClient, ContactFilter
from tests.helpers import mark_e2e

# UDS bind precedes contact-manager readiness: the bridge returns
# FAILED_PRECONDITION while the engine is still booting / signing in. Mirrors
# the readiness waits in sibling e2e files.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0
# The contact list (Cloud Friends) loads asynchronously after sign-in; give
# it a settle window before asserting on its contents.
_CONTACTS_SETTLE_S = 10.0

# A username almost certainly present in the public Resonite user directory,
# so the search read path returns at least one row on any signed-in account.
# Content varies, so only the call's success + row shape is asserted.
_SEARCH_QUERY = "Resonite"


async def _wait_for_ready() -> None:
    """Block until ``list_contacts`` stops returning FAILED_PRECONDITION."""
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while True:
        try:
            async with ContactClient() as client:
                await client.list_contacts()
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "Contact bridge never became ready within "
                    f"{_READY_TIMEOUT_S:.0f}s (is the client signed in?)"
                ) from e
            await asyncio.sleep(_READY_RETRY_INTERVAL_S)


class TestContact:
    @mark_e2e
    def test_read_only_list_get_search(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        async def run() -> None:
            await _wait_for_ready()
            await asyncio.sleep(_CONTACTS_SETTLE_S)

            async with ContactClient() as client:
                # 1. list contacts: the full (ALL) list must come back loaded;
                #    counts are non-negative and consistent with the rows.
                listing = await client.list_contacts()
                assert listing.list_loaded, (
                    "the contact list must finish loading on a signed-in account"
                )
                assert listing.contact_count >= 0
                assert listing.request_count >= 0
                # Every returned contact must carry a user id and a resolved
                # presence enum (never the UNSPECIFIED=0 default — the engine
                # always reports a concrete OnlineStatus).
                for c in listing.contacts:
                    assert c.user_id, "a contact must carry a user_id"
                    assert c.online_status.value != 0, (
                        f"contact {c.username!r} reported UNSPECIFIED online "
                        "status; the engine should resolve a concrete presence"
                    )

                # 2. the ACCEPTED filter must return a subset whose rows are all
                #    accepted contacts (never a pending request).
                accepted = await client.list_contacts(filter=ContactFilter.ACCEPTED)
                for c in accepted.contacts:
                    assert c.is_accepted, (
                        f"ACCEPTED filter returned non-accepted contact {c.username!r}"
                    )
                    assert not c.is_contact_request

                # 3. get_contact round-trip on a real contact, if any exists.
                #    found must be True and the looked-up id must match.
                if not listing.contacts:
                    pytest.skip(
                        "account has no contacts; cannot drive the get_contact "
                        "read path (needs a non-empty contact list, which this "
                        "read-only test must not create)."
                    )
                first = listing.contacts[0]
                got = await client.get_contact(first.user_id)
                assert got.found, (
                    f"get_contact for a known contact {first.user_id!r} must "
                    "report found=True"
                )
                assert got.contact is not None
                assert got.contact.user_id == first.user_id

                # 4. get_contact for a definitely-not-a-contact id must report
                #    found=False (distinguishable from a populated contact).
                missing = await client.get_contact("U-resoio-e2e-nonexistent")
                assert not missing.found, (
                    "get_contact for a non-existent user must report found=False"
                )

                # 5. user search read path: every returned row must carry an id
                #    and a username (content varies, so only shape is asserted).
                results = await client.search_users(_SEARCH_QUERY)
                for r in results.results:
                    assert r.user_id, "a search result must carry a user_id"
                    assert r.username, "a search result must carry a username"

        asyncio.run(run())
