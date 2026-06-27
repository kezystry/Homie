"""Capability — the registry handle that makes least-privilege real on the act path.

The problem (audit C2): `Act` read the actuator and the priority straight from the
event payload, so any tile could publish `actuator.requested` with `priority="safety"`
on any mapped actuator and Act would honour it. The only check was the act-map.

The fix the panel chose is a *registry handle*, deliberately NOT a signed token in the
payload. A signed token is data on a fan-out bus that also writes a durability log, so any
tile that ever sees one valid event can capture and replay it — and handing a signing key
to a subprocess child hands the forger the key. A handle puts NOTHING trustworthy on the
wire: it is a 128-bit opaque key into an in-process dict with no structure to forge and no
oracle to probe. The trusted core mints one handle per `(tile, actuator)` (binding the
manifest-derived priority); `ctx.act` stamps only the handle; `Act` resolves it back to the
authoritative `(tile, actuator, priority)` and ignores whatever the payload claims.

Honest scope (do not oversell): this eliminates accidental escalation via raw emit and
genuinely hardens the subprocess boundary (where memory is not shared and the handle is
never serialized). It is NOT unforgeable against a *malicious in-process* tile, which
shares the daemon heap and could walk `gc` to the registry — that is a process-isolation
problem a token cannot solve; the answer there is running the tile as a subprocess. The
act-map + never_touch remains the hard outer boundary, checked AFTER resolution.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    """What a handle resolves to: the authoritative identity of an authorized act."""

    tile: str
    actuator: str
    priority: str  # lowercase manifest level name, captured at mint time


class CapabilityRegistry:
    """In-process minter/resolver of act handles. One instance per daemon (built in
    `build_daemon`, shared by reference with Act and the Supervisor). Ephemeral: it is
    rebuilt every start, so a handle captured from a prior run's log is dead on restart."""

    def __init__(self) -> None:
        self._by_id: dict[str, Capability] = {}
        self._by_key: dict[tuple[str, str], str] = {}  # (tile, actuator) -> handle (idempotent re-mint)

    def mint(self, tile: str, actuator: str, priority: str) -> str:
        """Return the stable handle for this (tile, actuator), creating it once. Idempotent:
        the same pair always gets the same handle, so re-acting does not grow the registry."""
        key = (tile, actuator)
        handle = self._by_key.get(key)
        if handle is None:
            handle = secrets.token_hex(16)  # 128-bit, opaque, unstructured
            self._by_id[handle] = Capability(tile, actuator, priority)
            self._by_key[key] = handle
        return handle

    def resolve(self, handle: object) -> Capability | None:
        """The authoritative lookup. Returns None for anything that is not a live handle
        (a forged/guessed/absent value), which Act treats as 'no capability — refuse'."""
        if not isinstance(handle, str):
            return None
        return self._by_id.get(handle)

    def revoke_tile(self, tile: str) -> None:
        """Drop every handle a tile holds — called when a tile is stopped or quarantined so
        a dead tile's capabilities cannot linger."""
        for handle in [h for h, c in self._by_id.items() if c.tile == tile]:
            del self._by_id[handle]
        for key in [k for k in self._by_key if k[0] == tile]:
            del self._by_key[key]
