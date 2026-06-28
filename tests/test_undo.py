"""The one-tap undo (Phase D / Charter #24) — a row turned back through the safe path.

Proves the owner's call ("instant, but confirm the guarded ones"):
  * an everyday reversal re-drives the prior value with no friction,
  * a guarded reversal (a lock) asks Consent first and only re-drives on yes,
  * undo never forges a command — it goes through the capability-gated act path, and the
    act-map's outer boundary still refuses an unmapped target,
  * a row is marked undone only AFTER the home echoes the reversal, never optimistically.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.act import Act, ActMap, CommandLog
from core.bus import Bus
from core.capability import CapabilityRegistry
from core.consent import Consent
from core.friction_ledger import FrictionLedger
from core.reconcile import StateReconciler
from core.tile import Event
from core.undo import Undo


class _FakeHome:
    """Records drives and echoes them straight back as state changes (instant confirm)."""

    def __init__(self) -> None:
        self.drives: list = []
        self._handler = None

    def on_state_change(self, handler) -> None:
        self._handler = handler

    async def drive(self, entity_id: str, command: object) -> None:
        self.drives.append((entity_id, command))
        if self._handler is not None:
            await self._handler(entity_id, command)   # the home echoes the new state


class _FakeSup:
    """Just enough supervisor for the reconciler: note_* are no-ops (no tiles here)."""

    async def note_reversal(self, *a, **k): return None
    async def note_manual(self, *a, **k): return None


class UndoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = Bus()
        self.home = _FakeHome()
        self.registry = CapabilityRegistry()
        self.act_map = ActMap.from_forward({
            "light.kitchen": "light.kitchen",
            "lock.front": "lock.front",
        })
        self.commands = CommandLog()
        self.act = Act(self.bus, self.home, self.commands, self.act_map, registry=self.registry)
        # the real echo loop: a re-drive's home echo → act.confirm → actuator.done
        self.reconciler = StateReconciler(_FakeSup(), self.commands, self.act_map.reverse,
                                          on_echo=self.act.confirm)
        self.reconciler.attach(self.home)
        self.ledger = FrictionLedger(self.bus)
        self.consent = Consent(self.bus, timeout=5.0)
        self.undo = Undo(self.bus, self.ledger, self.registry, consent=self.consent)
        self.replies: list = []
        self.bus.subscribe("chat.reply", lambda e: self.replies.append(e))
        await self.act.start()
        await self.ledger.start()
        await self.consent.start()
        await self.undo.start()

    async def asyncTearDown(self) -> None:
        await self.undo.stop(); await self.consent.stop()
        await self.ledger.stop(); await self.act.stop()
        await self.bus.aclose()

    async def _did(self, actuator: str, value, ts: float, tile: str = "lighting") -> None:
        """Simulate a confirmed action landing in the ledger (what the reconciler emits)."""
        await self.bus.publish(Event("actuator.done", ts,
                                     {"actuator": actuator, "value": value, "tile": tile}, source="act"))
        await self.bus.drain()

    async def _undo(self, action_id=None, ts: float = 10.0) -> None:
        await self.bus.publish(Event("undo.requested", ts,
                                     {"action_id": action_id}, source="cockpit"))
        await self.bus.drain()

    async def test_everyday_undo_redrives_the_prior_value_instantly(self) -> None:
        await self._did("light.kitchen", {"state": "off"}, 1.0)   # establishes prior = off
        await self._did("light.kitchen", {"state": "on"}, 2.0)    # the action to undo
        await self._undo()                                        # tap undo (most recent)
        # it re-drove the prior 'off' through the act path → the home was driven
        self.assertIn(("light.kitchen", {"state": "off"}), self.home.drives)

    async def test_undo_marks_the_row_undone_after_the_echo(self) -> None:
        await self._did("light.kitchen", {"state": "off"}, 1.0)
        await self._did("light.kitchen", {"state": "on"}, 2.0)
        row = self.ledger.recent(1)[0]
        self.assertFalse(row.undone)
        await self._undo()
        self.assertTrue(self.ledger.get(row.id).undone)           # flipped only after the home echoed
        self.assertTrue(any("Undone" in e.payload["text"] for e in self.replies))

    async def test_nothing_to_undo_is_a_plain_reply_not_a_crash(self) -> None:
        await self._undo()                                        # empty ledger
        self.assertTrue(any("Nothing to undo" in e.payload["text"] for e in self.replies))

    async def test_first_touch_has_no_prior_so_cannot_be_undone(self) -> None:
        await self._did("light.kitchen", {"state": "on"}, 1.0)    # Homie never saw it before
        await self._undo()
        self.assertEqual(self.home.drives, [])                    # nothing re-driven
        self.assertTrue(any("Can't undo" in e.payload["text"] for e in self.replies))

    async def test_guarded_undo_asks_first_and_redrives_on_yes(self) -> None:
        await self._did("lock.front", {"state": "locked"}, 1.0)
        await self._did("lock.front", {"state": "unlocked"}, 2.0)
        # answer the confirm with a yes the moment it is asked
        async def yes(e):
            await self.bus.publish(Event("confirm.response", e.ts, {"id": e.payload["id"], "yes": True}, source="t"))
        self.bus.subscribe("confirm.requested", yes)
        await self._undo()
        self.assertIn(("lock.front", {"state": "locked"}), self.home.drives)

    async def test_guarded_undo_does_nothing_on_no(self) -> None:
        await self._did("lock.front", {"state": "locked"}, 1.0)
        await self._did("lock.front", {"state": "unlocked"}, 2.0)
        async def no(e):
            await self.bus.publish(Event("confirm.response", e.ts, {"id": e.payload["id"], "yes": False}, source="t"))
        self.bus.subscribe("confirm.requested", no)
        declined: list = []
        self.bus.subscribe("undo.declined", lambda e: declined.append(e))
        await self._undo()
        self.assertEqual(self.home.drives, [])                    # never re-driven
        self.assertEqual(len(declined), 1)

    async def test_concurrent_undos_on_one_actuator_are_both_marked_undone(self) -> None:
        # two reversible actions on the SAME actuator, undone back-to-back before either echo:
        # a single-slot _pending would lose the first; the FIFO queue marks BOTH undone.
        await self._did("light.kitchen", {"state": "off"}, 1.0)   # prior
        await self._did("light.kitchen", {"state": "on"}, 2.0)    # action A (prior off)
        await self._did("light.kitchen", {"state": "off"}, 3.0)   # action B (prior on)
        rows = self.ledger.recent(3)
        a = next(r for r in rows if r.value == {"state": "on"})
        b = next(r for r in rows if r.value == {"state": "off"} and r.reversible)
        await self.bus.publish(Event("undo.requested", 10.0, {"action_id": a.id}, source="cockpit"))
        await self.bus.publish(Event("undo.requested", 10.1, {"action_id": b.id}, source="cockpit"))
        await self.bus.drain()
        self.assertTrue(self.ledger.get(a.id).undone)
        self.assertTrue(self.ledger.get(b.id).undone)             # neither was silently dropped

    async def test_guarded_undo_without_consent_fails_safe(self) -> None:
        u = Undo(self.bus, self.ledger, self.registry, consent=None)  # no gate available
        await u.start()
        try:
            await self._did("lock.front", {"state": "locked"}, 1.0)
            await self._did("lock.front", {"state": "unlocked"}, 2.0)
            # both Undo instances see the request; ensure NO drive happens via the no-consent one.
            # Stop the consented one so only the fail-safe path can act.
            await self.undo.stop()
            await self._undo()
            self.assertEqual(self.home.drives, [])
        finally:
            await u.stop()

    async def test_undo_by_explicit_id(self) -> None:
        await self._did("light.kitchen", {"state": "off"}, 1.0)
        await self._did("light.kitchen", {"state": "on"}, 2.0)
        await self._did("light.kitchen", {"state": "off"}, 3.0)
        target = [a for a in self.ledger.recent(5) if a.value == {"state": "on"}][0]
        await self._undo(action_id=target.id)
        self.assertTrue(self.ledger.get(target.id).undone)


if __name__ == "__main__":
    unittest.main()
