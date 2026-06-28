"""Undo — the one-tap reversal (Charter #24, the felt "undo button").

The Friction Ledger records every confirmed action as a reversible row. This is the other
half: turning a row back. The owner taps undo (the cockpit publishes `undo.requested` with
the row id, or none for "the last thing"); Undo re-drives the recorded PRIOR value and the
home returns to where it was.

Two rails, both the owner's explicit call ("instant, but confirm the guarded ones"):

  * **Instant for everyday things.** A light, a scene — undo just re-drives the prior value,
    no friction. Change your mind, tap, it's back.
  * **Confirm for guarded things.** Anything that locks, opens, or secures (a door lock, the
    garage, an alarm) asks a yes/no first, through the same Consent gate as any consequential
    act. A guarded undo with no consent gate available fails safe (refuses), never re-drives
    blind.

Undo never forges a command. It re-drives through the SAME capability-gated act path as a
tile (Charter: undo is not a side-door around the safety rails) — but as trusted core it
mints its OWN handle for the `("undo", actuator)` pair, so the act-map + never-touch outer
boundary still applies. The row is marked undone only once the home actually echoes the
reversal back (`actuator.done`), so a failed re-drive never lies that it worked.
"""
from __future__ import annotations

import logging

from core.friction_ledger import FrictionLedger, describe
from core.tile import Event

log = logging.getLogger("homie.undo")

UNDO_REQUESTED = "undo.requested"        # in:  {action_id?: int}  (absent → most recent reversible)
ACTUATOR_REQUESTED = "actuator.requested"
ACTUATOR_DONE = "actuator.done"
REPLY = "chat.reply"                      # out: a plain confirmation line back to the owner

# Domains whose undo must be confirmed first. Everything else (lights, scenes, climate) is
# instant. These are the things a thoughtless re-drive could unlock or expose — so they ask.
GUARDED_DOMAINS = frozenset({"lock", "garage", "cover", "alarm", "switch_safety"})

# The priority an undo drives at. Convenience: high enough to take the actuator in normal
# use, low enough that a live safety/security decision still outranks it.
UNDO_PRIORITY = "convenience"


class Undo:
    """The reversal coordinator. Wire in `build_daemon`, `start()` after the ledger (so the
    rows exist) and after Act (so the re-drive lands). Holds the ledger + capability registry
    by reference and, optionally, the Consent gate for guarded reversals."""

    def __init__(self, bus, ledger: FrictionLedger, registry, *, consent=None,
                 guarded_domains=GUARDED_DOMAINS, priority: str = UNDO_PRIORITY,
                 scan: int = 50) -> None:
        self.bus = bus
        self.ledger = ledger
        self.registry = registry
        self.consent = consent
        self.guarded = frozenset(guarded_domains)
        self.priority = priority
        self._scan = scan                       # how far back "undo the last thing" looks
        # actuator -> FIFO queue of row ids awaiting their echo. A QUEUE (not a single slot) so
        # two undos racing on the SAME actuator both get marked undone, in order, rather than the
        # second silently overwriting the first (which left the home and the ledger disagreeing).
        self._pending: dict[str, list[int]] = {}
        self._subs: list = []

    async def start(self) -> None:
        self._subs = [
            self.bus.subscribe(UNDO_REQUESTED, self._on_request, owner="undo"),
            self.bus.subscribe(ACTUATOR_DONE, self._on_done, owner="undo"),
        ]

    async def stop(self) -> None:
        for s in self._subs:
            self.bus.unsubscribe(s)
        self._subs = []

    # ----------------------------------------------------------------- helpers
    def _is_guarded(self, actuator: str) -> bool:
        return actuator.split(".", 1)[0] in self.guarded

    def _latest(self):
        """The single most recent action — reversible or not. 'Undo the last thing' targets
        exactly this; it never silently reaches past an un-undoable action to an older one
        (that would revert something the owner didn't mean)."""
        rows = self.ledger.recent(1)
        return rows[0] if rows else None

    async def _reply(self, ts: float, text: str) -> None:
        await self.bus.publish(Event(REPLY, ts, {"text": text}, source="undo"))

    # ----------------------------------------------------------------- handlers
    async def _on_request(self, event: Event) -> None:
        aid = event.payload.get("action_id")
        action = self.ledger.get(aid) if aid is not None else self._latest()

        if action is None:
            await self._reply(event.ts, "Nothing to undo.")
            await self.bus.publish(Event("undo.failed", event.ts,
                                         {"action_id": aid, "reason": "nothing_to_undo"}, source="undo"))
            return
        if not action.reversible:
            why = "already undone" if action.undone else "I don't know what it was before"
            await self._reply(event.ts, f"Can't undo {describe(action)} — {why}.")
            await self.bus.publish(Event("undo.failed", event.ts,
                                         {"action_id": action.id, "reason": "not_reversible"}, source="undo"))
            return

        actuator, prior = action.actuator, action.prior
        if self._is_guarded(actuator):
            if self.consent is None:
                await self._reply(event.ts, f"Won't undo {describe(action)} without a confirmation step.")
                await self.bus.publish(Event("undo.failed", event.ts,
                                             {"action_id": action.id, "reason": "guarded_no_consent"}, source="undo"))
                return
            ok = await self.consent.request(f"Undo {describe(action)}?", actuator=actuator, risk="high")
            if not ok:
                await self.bus.publish(Event("undo.declined", event.ts,
                                             {"action_id": action.id}, source="undo"))
                return

        # Re-drive the prior value through the capability-gated act path. Mint our own handle
        # (trusted core) — never a forged payload actuator. The act-map still has final say.
        cap = self.registry.mint("undo", actuator, self.priority)
        self._pending.setdefault(actuator, []).append(action.id)
        await self.bus.publish(Event(ACTUATOR_REQUESTED, event.ts,
                                     {"cap": cap, "value": prior}, source="undo"))

    async def _on_done(self, event: Event) -> None:
        actuator = event.payload.get("actuator")
        queue = self._pending.get(actuator) if actuator else None
        aid = queue.pop(0) if queue else None   # FIFO: oldest pending re-drive on this actuator
        if not queue:
            self._pending.pop(actuator, None)   # tidy up an emptied queue
        if aid is None:
            return                              # not one of our re-drives
        action = self.ledger.get(aid)
        line = describe(action) if action else "that"
        self.ledger.mark_undone(aid)            # flip the row only now the home really changed
        await self._reply(event.ts, f"Undone — {line}")
        await self.bus.publish(Event("undo.done", event.ts, {"action_id": aid}, source="undo"))
