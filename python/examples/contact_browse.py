"""Minimal read-only Contact browse example: list -> search -> get.

Lists the local contacts with presence, searches the cloud for users by
a query, and fetches a single contact by id. All three are read-only.

The mutating operations (add / accept / remove) are intentionally NOT
shown here: they send real, externally-visible friend requests /
approvals / removals to the cloud and cannot be cleanly undone. Drive
them deliberately, never from an unattended example.

The contact list is environment-dependent: when it is empty (signed out
or no contacts) the script prints a notice and exits cleanly.

Requires a logged-in Resonite client.

Run from inside the dev container:

    uv run python python/examples/contact_browse.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import ContactClient, ContactFilter

SOCKET_PATH: str | None = None
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until Contact.ListContacts stops returning FAILED_PRECONDITION.

    The bridge replies FAILED_PRECONDITION while the engine is booting
    or the cloud session has not finished authenticating. Retry until
    ready.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with ContactClient(SOCKET_PATH) as client:
                await client.list_contacts()
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Contact did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    async with ContactClient(SOCKET_PATH) as client:
        listing = await client.list_contacts()
        print(
            f"contacts: count={listing.contact_count} "
            f"requests={listing.request_count} loaded={listing.list_loaded}"
        )
        for c in listing.contacts:
            print(
                f"  {c.username!r} ({c.user_id}) status={c.status.name} "
                f"online={c.online_status.name} session={c.current_session_name!r}"
            )

        # Incoming friend requests are a filtered view of the same list.
        requests = await client.list_contacts(filter=ContactFilter.REQUESTS)
        print(f"incoming requests: {len(requests.contacts)}")

        if not listing.contacts:
            print("no contacts visible (empty list / signed out); done")
            return

        # Read-only cloud user search, seeded from an existing contact's name.
        first = listing.contacts[0]
        found = await client.search_users(first.username)
        print(f"search {first.username!r}: {len(found.results)} cloud user(s)")

        # Fetch that same contact back by id.
        got = await client.get_contact(first.user_id)
        print(f"get {first.user_id}: found={got.found}")


if __name__ == "__main__":
    asyncio.run(main())
