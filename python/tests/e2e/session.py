"""E2E: drive the Session modality against a live Resonite client.

Exercises the full Session surface end to end through the real
``FrooxEngineSessionBridge``: read the session settings, apply a
reversible partial patch and confirm it lands (string / int / enum /
bool — the proto3 ``optional`` presence + access-level enum offset are
only truly validated against the engine), list users / roles / role
overrides, and respawn the local user. Every settings mutation is
restored to the snapshot captured at the start, so the world is left as
it was found.

The settings/respawn run against the local home world where the local
user is the host, so the host-gated writes (ApplySettings / Respawn) are
permitted. Like every file under ``tests/e2e/`` this requires the
host-side ``just host-agent`` daemon plus a live Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import grpclib
from grpclib.const import Status

from resoio.session import SessionAccessLevel, SessionClient, SessionSettings
from tests.helpers import mark_e2e

# UDS bind precedes FocusedWorld readiness: the bridge returns
# FAILED_PRECONDITION (SessionNotReadyException) while the engine is still
# booting into the home world. Mirrors the readiness waits in sibling e2e
# files; one duplication is below the bar for a shared helper.
_SESSION_READY_TIMEOUT_S = 120.0
_SESSION_READY_RETRY_INTERVAL_S = 2.0


async def _wait_for_session_ready() -> SessionSettings:
    """Block until GetSettings stops returning FAILED_PRECONDITION.

    Returns the first successful snapshot so the caller can capture the
    pre-test settings to restore later.
    """
    deadline = time.monotonic() + _SESSION_READY_TIMEOUT_S
    while True:
        try:
            async with SessionClient() as client:
                return await client.get_settings()
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Session bridge did not become ready in "
                    f"{_SESSION_READY_TIMEOUT_S:.0f}s (last reason: {e.message})"
                ) from e
            await asyncio.sleep(_SESSION_READY_RETRY_INTERVAL_S)


def _other_access_level(current: SessionAccessLevel) -> SessionAccessLevel:
    """Pick an access level different from ``current`` for a round-trip
    check."""
    return (
        SessionAccessLevel.LAN
        if current is SessionAccessLevel.PRIVATE
        else SessionAccessLevel.PRIVATE
    )


class TestSession:
    @mark_e2e
    def test_session_roundtrip(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        async def run() -> None:
            original = await _wait_for_session_ready()
            assert original.is_host, (
                "expected to be host of the local home world for write tests"
            )

            new_name = f"{original.world_name} (e2e)"
            new_max = min(original.max_users + 1, 255)
            new_access = _other_access_level(original.access_level)
            new_hide = not original.hide_from_listing

            async with SessionClient() as client:
                try:
                    await client.apply_settings(
                        world_name=new_name,
                        max_users=new_max,
                        access_level=new_access,
                        hide_from_listing=new_hide,
                    )
                    changed = await client.get_settings()
                    # proto3 optional presence + enum offset land on the engine.
                    assert changed.world_name == new_name
                    assert changed.max_users == new_max
                    assert changed.access_level is new_access
                    assert changed.hide_from_listing is new_hide
                finally:
                    # Restore the exact pre-test snapshot (captured above), not
                    # hardcoded defaults, so the world is left as it was found.
                    await client.apply_settings(
                        world_name=original.world_name,
                        max_users=original.max_users,
                        access_level=original.access_level,
                        hide_from_listing=original.hide_from_listing,
                    )
                    restored = await client.get_settings()
                    assert restored.world_name == original.world_name
                    assert restored.access_level is original.access_level

                # Users: the local user must be present, flagged self + host.
                users = await client.list_users()
                me = [u for u in users if u.is_local_user]
                assert len(me) == 1, f"expected exactly one local user, got {users}"
                assert me[0].is_host

                # Roles: a session always has a role list with one highest and
                # one lowest entry; default roles resolve to role names.
                roles = await client.list_roles()
                assert roles.roles, "expected a non-empty role list"
                assert sum(r.is_highest for r in roles.roles) == 1
                assert sum(r.is_lowest for r in roles.roles) == 1

                # Overrides read path (may legitimately be empty).
                await client.get_user_role_overrides()

                # Respawn self (target omitted == self). Host of the local
                # world can always respawn; assert it does not raise.
                await client.respawn_self()

        asyncio.run(run())
