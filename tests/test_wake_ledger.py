"""Wake telemetry — the ledger SEES every gate evaluation, and the counts are a pure,
replay-stable function of the event stream. This is the measured answer to C8's
"~95% asleep, never measured": the asleep-fraction is now a real number.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.bus import Bus
from core.reason import WAKE_DECISION, Reason
from core.remember import Expectation
from core.tile import Event
from core.wake_ledger import SurpriseGate, WakeBudget, WakeDecision, WakeLedger

NOVEL = Expectation(rate=0.0, count=0.0, days=0.0, novel=True)
ROUTINE = Expectation(rate=5.0, count=20.0, days=4.0, novel=False)


class NullLLM:
    async def propose(self, *, system, context, tools):
        from core.reason import Proposal
        return Proposal()  # do nothing — isolate the gate/ledger from model behavior


class Sup:
    def tool_catalog(self):
        return []

    async def call_function(self, fn, **a):
        return None


class ScriptedRemember:
    """Returns an Expectation that is a pure function of the event — novel for any zone
    starting 'new', routine otherwise — so the ledger's inputs depend only on the trace."""

    async def normal(self, topic, zone, when):
        return NOVEL if (zone or "").startswith("new") else ROUTINE


def collect(sink):
    async def h(e):
        sink.append(e)
    return h


# A fixed trace: a mix of novel (waking) and routine (asleep) moments across zones/hours.
TRACE = [
    Event("presence.arrived", 3600.0 * 0 + 100, {"zone": "new_back"}),
    Event("presence.arrived", 3600.0 * 0 + 200, {"zone": "living"}),
    Event("presence.arrived", 3600.0 * 1 + 100, {"zone": "living"}),
    Event("presence.arrived", 3600.0 * 2 + 100, {"zone": "new_loft"}),
    Event("motion.detected", 3600.0 * 2 + 200, {"zone": "kitchen"}),
    Event("occupancy.changed", 3600.0 * 3 + 100, {"zone": "new_den"}),
]


async def _run_trace(trace):
    bus = Bus()
    # Fresh, deterministic governance each run — generous budget so nothing is shed here;
    # this test is purely about SEEING and counting, not capping.
    reason = Reason(bus, NullLLM(), Sup(), ScriptedRemember(),
                    ledger=WakeLedger(), budget=WakeBudget(per_hour=1000, per_day=100000),
                    gate=SurpriseGate())
    await reason.start()
    seen = []
    bus.subscribe(WAKE_DECISION, collect(seen))
    for e in trace:
        await bus.publish(e)
    await bus.drain()
    snap = reason.ledger.snapshot()
    await reason.stop()
    await bus.aclose()
    return snap, list(reason.ledger.recent), seen


class WakeLedgerCountTests(unittest.IsolatedAsyncioTestCase):
    async def test_ledger_counts_are_replay_stable(self) -> None:
        # The audit's requirement: replaying a fixed log yields bit-identical counts.
        snap_a, recent_a, _ = await _run_trace(TRACE)
        snap_b, recent_b, _ = await _run_trace(TRACE)
        self.assertEqual(snap_a, snap_b)
        self.assertEqual(recent_a, recent_b)

    async def test_counts_match_the_trace(self) -> None:
        snap, recent, seen = await _run_trace(TRACE)
        # three 'new*' zones are novel -> surprising -> fired; three routine -> asleep.
        self.assertEqual(snap["evaluations"], 6)
        self.assertEqual(snap["surprising"], 3)
        self.assertEqual(snap["fired"], 3)
        self.assertEqual(snap["deferred"], 0)
        self.assertEqual(snap["asleep_fraction"], round(1 - 3 / 6, 4))
        self.assertEqual(snap["outcomes"], {"fired": 3, "routine": 3})
        # only the surprising tail is surfaced on the bus; routine non-wakes stay silent.
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(e.payload["fired"] for e in seen))

    async def test_asleep_fraction_is_a_real_number(self) -> None:
        snap, _, _ = await _run_trace(TRACE)
        self.assertIsInstance(snap["asleep_fraction"], float)
        self.assertTrue(0.0 <= snap["asleep_fraction"] <= 1.0)


class WakeLedgerUnitTests(unittest.TestCase):
    def _dec(self, **kw):
        base = dict(topic="presence.arrived", zone="living", hour=3, rate=0.0, novel=True,
                    surprising=True, fired=True, deferred=False, outcome="fired")
        base.update(kw)
        return WakeDecision(**base)

    def test_empty_ledger_reports_fully_asleep(self) -> None:
        self.assertEqual(WakeLedger().asleep_fraction(), 1.0)

    def test_record_accumulates(self) -> None:
        led = WakeLedger()
        led.record(self._dec(outcome="fired", fired=True, deferred=False))
        led.record(self._dec(outcome="budget", fired=False, deferred=True))
        led.record(self._dec(surprising=False, fired=False, deferred=False, outcome="routine", novel=False))
        self.assertEqual(led.total, 3)
        self.assertEqual(led.surprising, 2)
        self.assertEqual(led.fired, 1)
        self.assertEqual(led.deferred, 1)
        self.assertEqual(led.outcomes, {"fired": 1, "budget": 1, "routine": 1})
        self.assertAlmostEqual(led.asleep_fraction(), 1 - 1 / 3)


if __name__ == "__main__":
    unittest.main()
