"""Wake budget — C8's cold-start wake-storm is now BOUNDED and the bound is enforced
without ever silently dropping a moment. Safety and chat wakes are never shed; a corner
the model keeps shrugging at backs off; over-budget wakes are recorded as deferred.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.bus import Bus
from core.reason import Proposal, Reason, ToolCall
from core.remember import Expectation
from core.tile import Event
from core.wake_ledger import WakeBudget, WakeLedger, SurpriseGate

NOVEL = Expectation(rate=0.0, count=0.0, days=0.0, novel=True)


class AlwaysNovel:
    async def normal(self, topic, zone, when):
        return NOVEL  # every moment is a first sighting — the cold-start worst case


class Sup:
    def __init__(self, catalog=None):
        self._c = catalog or []
        self.called = []

    def tool_catalog(self):
        return self._c

    async def call_function(self, fn, **a):
        self.called.append((fn, a))


class NullLLM:
    async def propose(self, *, system, context, tools):
        return Proposal()  # do nothing


class SayLLM:
    async def propose(self, *, system, context, tools):
        return Proposal(say="noticed")  # always does something -> resets backoff


def collect(sink):
    async def h(e):
        sink.append(e)
    return h


async def _reason(llm, *, per_hour, per_day=100000, remember=None, catalog=None):
    bus = Bus()
    reason = Reason(bus, llm, Sup(catalog), remember or AlwaysNovel(),
                    ledger=WakeLedger(), budget=WakeBudget(per_hour=per_hour, per_day=per_day),
                    gate=SurpriseGate())
    await reason.start()
    return bus, reason


class ColdStartFloodTests(unittest.IsolatedAsyncioTestCase):
    async def test_cold_start_flood_is_bounded(self) -> None:
        # 50 novel arrivals in DISTINCT zones at the SAME instant (the worst case: no
        # refill, no backoff sharing). With a 5/hour bucket, at most 5 may wake.
        N, CAP = 50, 5
        bus, reason = await _reason(NullLLM(), per_hour=CAP)
        ts = 1000.0
        for i in range(N):
            await bus.publish(Event("presence.arrived", ts, {"zone": f"z{i}"}))
        await bus.drain()
        snap = reason.ledger.snapshot()

        self.assertEqual(snap["evaluations"], N)
        self.assertEqual(snap["surprising"], N)            # all novel
        self.assertEqual(snap["fired"], CAP)               # the bucket bounds it
        self.assertLessEqual(snap["fired"], CAP)           # ...never exceeds the budget
        # ZERO silent drops: every surprising moment is either fired or recorded deferred.
        self.assertEqual(snap["fired"] + snap["deferred"], N)
        self.assertEqual(snap["deferred"], N - CAP)
        self.assertEqual(snap["outcomes"].get("budget"), N - CAP)
        # the real measured asleep-fraction is reported as a number.
        self.assertIsInstance(snap["asleep_fraction"], float)
        self.assertAlmostEqual(snap["asleep_fraction"], 1 - CAP / N)
        await reason.stop()
        await bus.aclose()

    async def test_budget_refills_over_event_time(self) -> None:
        # Spread the same flood across hours and the bucket refills — more wakes get
        # through, but still bounded per hour. Drives home it's event-clocked.
        bus, reason = await _reason(NullLLM(), per_hour=2)
        for hour in range(4):
            for i in range(10):
                await bus.publish(Event("presence.arrived", 3600.0 * hour + i, {"zone": f"h{hour}z{i}"}))
        await bus.drain()
        snap = reason.ledger.snapshot()
        # 2 to start + ~2 refilled each subsequent hour -> well under the 40 evaluations.
        self.assertGreater(snap["fired"], 2)
        self.assertLess(snap["fired"], 40)
        self.assertEqual(snap["fired"] + snap["deferred"], 40)  # still zero silent drops
        await reason.stop()
        await bus.aclose()


class ExemptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_safety_wake_is_never_shed(self) -> None:
        # Exhaust a 1/hour budget on a presence flood, then a safety event still wakes.
        bus, reason = await _reason(SayLLM(), per_hour=1)
        says = []
        bus.subscribe("interface.say", collect(says))
        ts = 5000.0
        for i in range(10):
            await bus.publish(Event("presence.arrived", ts, {"zone": f"z{i}"}))
        await bus.drain()
        self.assertEqual(reason.ledger.outcomes.get("budget"), 9)  # 1 fired, 9 deferred
        # now a safety moment at the same instant — budget is empty, but it is exempt.
        await bus.publish(Event("safety.smoke", ts, {"zone": "kitchen"}))
        await bus.drain()
        self.assertEqual(reason.ledger.outcomes.get("exempt"), 1)
        self.assertTrue(any(s.payload["text"] == "noticed" for s in says))
        await reason.stop()
        await bus.aclose()

    async def test_chat_is_answered_even_with_an_empty_budget(self) -> None:
        catalog = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object", "properties": {}}}}]
        bus, reason = await _reason(SayLLM(), per_hour=1, catalog=catalog)
        replies = []
        bus.subscribe("chat.reply", collect(replies))
        for i in range(5):  # drain the budget
            await bus.publish(Event("presence.arrived", 7000.0, {"zone": f"z{i}"}))
        await bus.drain()
        await bus.publish(Event("chat.message", 7000.0, {"text": "are you there?"}))
        await bus.drain()
        self.assertEqual(len(replies), 1)  # chat runs on its own path, never budgeted
        self.assertEqual(replies[0].payload["text"], "noticed")
        await reason.stop()
        await bus.aclose()


class BackoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_do_nothing_backs_off_then_reprobes(self) -> None:
        # Same (zone, topic), plenty of budget: the FIRST wake fires; because the model
        # does nothing, the second (soon after) is muted as backoff; long enough later it
        # re-probes.
        bus, reason = await _reason(NullLLM(), per_hour=1000)
        await bus.publish(Event("presence.arrived", 0.0, {"zone": "loft"}))
        await bus.drain()
        await bus.publish(Event("presence.arrived", 60.0, {"zone": "loft"}))  # within backoff window
        await bus.drain()
        await bus.publish(Event("presence.arrived", 100000.0, {"zone": "loft"}))  # past the cap -> reprobe
        await bus.drain()
        outs = [d.outcome for d in reason.ledger.recent]
        self.assertEqual(outs, ["fired", "backoff", "fired"])
        self.assertEqual(reason.ledger.deferred, 1)  # the backoff is deferred, not dropped
        await reason.stop()
        await bus.aclose()

    async def test_action_resets_backoff(self) -> None:
        # A model that acts each time never gets muted — backoff is for the idle corners.
        bus, reason = await _reason(SayLLM(), per_hour=1000)
        for ts in (0.0, 60.0, 120.0):
            await bus.publish(Event("presence.arrived", ts, {"zone": "hall"}))
        await bus.drain()
        outs = [d.outcome for d in reason.ledger.recent]
        self.assertEqual(outs, ["fired", "fired", "fired"])
        await reason.stop()
        await bus.aclose()


class WakeBudgetUnitTests(unittest.TestCase):
    def test_starts_full_then_empties(self) -> None:
        b = WakeBudget(per_hour=3, per_day=1000)
        self.assertTrue(b.allow(0.0))
        self.assertTrue(b.allow(0.0))
        self.assertTrue(b.allow(0.0))
        self.assertFalse(b.allow(0.0))  # bucket empty, no time passed

    def test_refills_with_event_time(self) -> None:
        b = WakeBudget(per_hour=3600, per_day=10**9)  # 1 token/sec
        for _ in range(3600):
            b.allow(0.0)
        self.assertFalse(b.allow(0.0))
        self.assertTrue(b.allow(1.0))   # one second -> one token

    def test_daily_cap_is_hard(self) -> None:
        b = WakeBudget(per_hour=10**6, per_day=2)
        self.assertTrue(b.allow(0.0))
        self.assertTrue(b.allow(0.0))
        self.assertFalse(b.allow(0.0))           # daily ceiling, even with tokens to spare
        self.assertTrue(b.allow(86400.0))        # next day resets the count

    def test_backoff_grows_and_resets(self) -> None:
        b = WakeBudget(per_hour=10, backoff_base=100.0, backoff_cap=1000.0)
        b.note_outcome("z", "t", 0.0, did_something=False)
        self.assertTrue(b.muted("z", "t", 50.0))     # within 100s window
        self.assertFalse(b.muted("z", "t", 150.0))   # window passed
        b.note_outcome("z", "t", 150.0, did_something=False)  # second strike -> 200s
        self.assertTrue(b.muted("z", "t", 300.0))
        b.note_outcome("z", "t", 300.0, did_something=True)   # acted -> cleared
        self.assertFalse(b.muted("z", "t", 301.0))


if __name__ == "__main__":
    unittest.main()
