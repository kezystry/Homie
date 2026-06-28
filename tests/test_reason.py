"""Reason — the structural tool-call gate AND the cortex decide loop (fake LLM).

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest

from core.bus import Bus
from core.reason import Proposal, Reason, ToolCall, build_context, should_wake, validate_tool_call
from core.remember import Expectation
from core.tile import Event

CATALOG = [
    {"type": "function", "function": {"name": "agenda", "parameters": {"type": "object", "properties": {}}}},
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "priority": {"type": "integer"}},
                "required": ["text"],
            },
        },
    },
]


class ValidateToolCallTests(unittest.TestCase):
    def test_valid_call_no_errors(self) -> None:
        self.assertEqual(validate_tool_call(CATALOG, "add_reminder", {"text": "dentist"}), [])

    def test_no_param_function(self) -> None:
        self.assertEqual(validate_tool_call(CATALOG, "agenda", {}), [])

    def test_unknown_function_rejected(self) -> None:
        errs = validate_tool_call(CATALOG, "launch_missiles", {})
        self.assertEqual(len(errs), 1)
        self.assertIn("unknown function", errs[0])

    def test_missing_required_arg(self) -> None:
        errs = validate_tool_call(CATALOG, "add_reminder", {})
        self.assertTrue(any("missing required arg 'text'" in e for e in errs))

    def test_unexpected_arg_rejected(self) -> None:
        errs = validate_tool_call(CATALOG, "add_reminder", {"text": "x", "ctx": "sneaky"})
        self.assertTrue(any("unexpected arg 'ctx'" in e for e in errs))

    def test_type_mismatch(self) -> None:
        errs = validate_tool_call(CATALOG, "add_reminder", {"text": 123})
        self.assertTrue(any("must be string" in e for e in errs))

    def test_integer_not_bool(self) -> None:
        # a bool must not satisfy integer (Python bool is an int subclass)
        errs = validate_tool_call(CATALOG, "add_reminder", {"text": "x", "priority": True})
        self.assertTrue(any("priority" in e for e in errs))
        self.assertEqual(validate_tool_call(CATALOG, "add_reminder", {"text": "x", "priority": 2}), [])


# --------------------------------------------------------------------------- #
# The cortex decide loop, against a fake LLM (no GPU, no model, deterministic)
# --------------------------------------------------------------------------- #
class FakeLLM:
    def __init__(self, proposals=None, *, gate: asyncio.Event | None = None) -> None:
        self.proposals = list(proposals or [])
        self.calls: list[dict] = []  # every propose() — assertable
        self.gate = gate

    async def propose(self, *, system, context, tools) -> Proposal:
        self.calls.append({"context": context, "tools": tools})
        if self.gate is not None:
            await self.gate.wait()
        return self.proposals.pop(0) if self.proposals else Proposal()


class SpySupervisor:
    def __init__(self, catalog) -> None:
        self._catalog = catalog
        self.called: list = []

    def tool_catalog(self) -> list[dict]:
        return self._catalog

    async def call_function(self, fn, **args):
        self.called.append((fn, args))
        return None


class FakeRemember:
    def __init__(self, exp: Expectation) -> None:
        self.exp = exp

    async def normal(self, topic, zone, when) -> Expectation:
        return self.exp


def collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


NOVEL = Expectation(rate=0.0, count=0.0, days=0.0, novel=True)
ROUTINE = Expectation(rate=5.0, count=20.0, days=4.0, novel=False)
PRES = Event("presence.arrived", 1000.0, {"zone": "living"})


class NoveltyGateTests(unittest.TestCase):
    def test_should_wake(self) -> None:
        self.assertTrue(should_wake(NOVEL))
        self.assertTrue(should_wake(Expectation(rate=0.05, count=1.0, days=1.0, novel=False)))
        self.assertFalse(should_wake(ROUTINE))

    def test_build_context_carries_event_and_expectation(self) -> None:
        ctx = build_context(PRES, NOVEL)
        self.assertEqual(ctx["topic"], "presence.arrived")
        self.assertEqual(ctx["zone"], "living")
        self.assertTrue(ctx["expectation"]["novel"])


class CortexTests(unittest.IsolatedAsyncioTestCase):
    async def _reason(self, llm, exp=NOVEL, catalog=CATALOG):
        bus = Bus()
        reason = Reason(bus, llm, SpySupervisor(catalog), FakeRemember(exp))
        await reason.start()
        return bus, reason

    async def test_chat_context_carries_what_homie_knows(self) -> None:
        # Active memory (M7): a chat answer is informed by the learned brief.
        llm = FakeLLM()
        bus = Bus()
        reason = Reason(bus, llm, SpySupervisor(CATALOG), FakeRemember(NOVEL),
                        memory_brief=lambda: ["You usually leave around 8.", "Friday is film night."])
        await reason.start()
        await reason.answer_chat("what do you know about me?", 1.0)
        await bus.drain()
        self.assertIn("knows", llm.calls[-1]["context"])
        self.assertIn("Friday is film night.", llm.calls[-1]["context"]["knows"])
        await bus.aclose()

    async def test_chat_without_a_memory_provider_omits_knows(self) -> None:
        llm = FakeLLM()
        bus, reason = await self._reason(llm)
        await reason.answer_chat("hi", 1.0)
        await bus.drain()
        self.assertNotIn("knows", llm.calls[-1]["context"])     # no provider → no key, cortex unaffected
        await bus.aclose()

    async def test_novel_event_wakes_llm(self) -> None:
        llm = FakeLLM()
        bus, reason = await self._reason(llm, NOVEL)
        await bus.publish(PRES)
        await bus.drain()
        self.assertEqual(len(llm.calls), 1)
        await reason.stop()
        await bus.aclose()

    async def test_routine_event_does_not_wake_llm(self) -> None:
        llm = FakeLLM()
        bus, reason = await self._reason(llm, ROUTINE)
        await bus.publish(PRES)
        await bus.drain()
        self.assertEqual(llm.calls, [])  # the cheap path: GPU stays asleep
        await reason.stop()
        await bus.aclose()

    async def test_valid_tool_call_routes_to_tile_and_drives_nothing(self) -> None:
        llm = FakeLLM([Proposal(tool_call=ToolCall("add_reminder", {"text": "milk"}))])
        bus, reason = await self._reason(llm)
        acts: list = []
        bus.subscribe("actuator.requested", collect(acts))
        await bus.publish(PRES)
        await bus.drain()
        self.assertEqual(reason.sup.called, [("add_reminder", {"text": "milk"})])
        self.assertEqual(acts, [])  # Reason never drives an actuator directly
        await reason.stop()
        await bus.aclose()

    async def test_invalid_tool_call_rejected(self) -> None:
        for bad in (ToolCall("launch_missiles", {}), ToolCall("add_reminder", {})):
            llm = FakeLLM([Proposal(tool_call=bad)])
            bus, reason = await self._reason(llm)
            await bus.publish(PRES)
            await bus.drain()
            self.assertEqual(reason.sup.called, [])  # validation blocked it
            await reason.stop()
            await bus.aclose()

    async def test_say_emits_interface_say_only(self) -> None:
        llm = FakeLLM([Proposal(say="Welcome home.")])
        bus, reason = await self._reason(llm)
        said, acts = [], []
        bus.subscribe("interface.say", collect(said))
        bus.subscribe("actuator.requested", collect(acts))
        await bus.publish(PRES)
        await bus.drain()
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0].payload["text"], "Welcome home.")
        self.assertEqual(acts, [])
        await reason.stop()
        await bus.aclose()

    async def test_one_inflight_decision_per_zone(self) -> None:
        gate = asyncio.Event()
        llm = FakeLLM([Proposal(), Proposal()], gate=gate)
        bus, reason = await self._reason(llm)
        try:
            living1 = asyncio.ensure_future(reason._on_event(Event("presence.arrived", 1.0, {"zone": "living"})))
            await asyncio.sleep(0)  # let it reach the gated propose and mark living in-flight
            # a second living event while the first is mid-decision is coalesced away
            await reason._on_event(Event("presence.arrived", 2.0, {"zone": "living"}))
            self.assertEqual(len(llm.calls), 1)
            # a different zone is independent and wakes its own decision
            kitchen = asyncio.ensure_future(reason._on_event(Event("presence.arrived", 3.0, {"zone": "kitchen"})))
            await asyncio.sleep(0)
            self.assertEqual(len(llm.calls), 2)
            gate.set()
            await asyncio.gather(living1, kitchen)
        finally:
            await reason.stop()
            await bus.aclose()


class FailLLM:
    async def propose(self, *, system, context, tools) -> Proposal:
        raise RuntimeError("serving down")


class CortexChatTests(unittest.IsolatedAsyncioTestCase):
    async def _reason(self, llm, catalog=CATALOG):
        bus = Bus()
        reason = Reason(bus, llm, SpySupervisor(catalog), FakeRemember(NOVEL))
        await reason.start()
        return bus, reason

    async def test_chat_reply_is_published_and_drives_nothing(self) -> None:
        llm = FakeLLM([Proposal(say="The doors are locked.")])
        bus, reason = await self._reason(llm)
        replies, acts = [], []
        bus.subscribe("chat.reply", collect(replies))
        bus.subscribe("actuator.requested", collect(acts))
        await bus.publish(Event("chat.message", 5.0, {"text": "are the doors locked?"}))
        await bus.drain()
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].payload["text"], "The doors are locked.")
        self.assertEqual(replies[0].source, "reason")
        self.assertEqual(acts, [])
        # the chat prompt was used, not the ambient one
        self.assertEqual(llm.calls[0]["context"], {"chat": "are the doors locked?"})
        await reason.stop()
        await bus.aclose()

    async def test_chat_tool_call_acts_and_acknowledges(self) -> None:
        llm = FakeLLM([Proposal(tool_call=ToolCall("add_reminder", {"text": "milk"}))])
        bus, reason = await self._reason(llm)
        replies, acts = [], []
        bus.subscribe("chat.reply", collect(replies))
        bus.subscribe("actuator.requested", collect(acts))
        await bus.publish(Event("chat.message", 6.0, {"text": "remind me to buy milk"}))
        await bus.drain()
        self.assertEqual(reason.sup.called, [("add_reminder", {"text": "milk"})])
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].payload["text"], "Done.")
        self.assertEqual(acts, [])  # never a direct actuator path
        await reason.stop()
        await bus.aclose()

    async def test_chat_invalid_tool_call_is_blocked(self) -> None:
        llm = FakeLLM([Proposal(tool_call=ToolCall("launch_missiles", {}))])
        bus, reason = await self._reason(llm)
        await bus.publish(Event("chat.message", 7.0, {"text": "do the thing"}))
        await bus.drain()
        self.assertEqual(reason.sup.called, [])  # validation blocked it
        await reason.stop()
        await bus.aclose()

    async def test_chat_serving_failure_apologises(self) -> None:
        bus, reason = await self._reason(FailLLM())
        replies: list = []
        bus.subscribe("chat.reply", collect(replies))
        await bus.publish(Event("chat.message", 8.0, {"text": "hello?"}))
        await bus.drain()
        self.assertEqual(len(replies), 1)
        self.assertIn("Sorry", replies[0].payload["text"])
        await reason.stop()
        await bus.aclose()

    async def test_blank_chat_is_ignored(self) -> None:
        llm = FakeLLM([Proposal(say="should not happen")])
        bus, reason = await self._reason(llm)
        await bus.publish(Event("chat.message", 9.0, {"text": "   "}))
        await bus.drain()
        self.assertEqual(llm.calls, [])  # never woke the model
        await reason.stop()
        await bus.aclose()


# --------------------------------------------------------------------------- #
# Serving discipline (M6): the cortex times each call, records the SLO, and emits
# `reason.served` telemetry with latency + warm state. No GPU; an injected clock
# advances during propose() to simulate a real round-trip.
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class SlowLLM:
    """A fake model that 'takes' `ms` by advancing the injected clock during propose."""

    def __init__(self, clk: _Clock, ms: float, proposal=None) -> None:
        self.clk = clk
        self.ms = ms
        self.proposal = proposal if proposal is not None else Proposal(say="hi")

    async def propose(self, *, system, context, tools) -> Proposal:
        self.clk.t += self.ms / 1000.0
        return self.proposal


class CortexServingTests(unittest.IsolatedAsyncioTestCase):
    async def test_served_telemetry_records_latency_and_warm(self) -> None:
        from core.serving import LatencySLO, WarmPolicy
        clk = _Clock()
        slo = LatencySLO(budget_ms=4000.0)
        llm = SlowLLM(clk, 1500.0)
        bus = Bus()
        reason = Reason(bus, llm, SpySupervisor(CATALOG), FakeRemember(NOVEL),
                        slo=slo, warm=WarmPolicy(now=clk), now=clk)
        served: list = []
        bus.subscribe("reason.served", collect(served))
        await reason.start()
        await bus.publish(PRES)
        await bus.drain()
        self.assertEqual(len(served), 1)
        p = served[0].payload
        self.assertEqual(p["kind"], "wake")
        self.assertAlmostEqual(p["latency_ms"], 1500.0)
        self.assertTrue(p["slo_met"])     # 1500ms < 4000ms budget
        self.assertTrue(p["warm"])        # the GPU just woke
        self.assertIn("reject_rate", p)   # rolling tool-call rejection rate is surfaced
        self.assertEqual(slo.total, 1)
        self.assertEqual(slo.breaches, 0)
        await reason.stop()
        await bus.aclose()

    async def test_slo_breach_is_flagged(self) -> None:
        from core.serving import LatencySLO, WarmPolicy
        clk = _Clock()
        slo = LatencySLO(budget_ms=1000.0)
        bus = Bus()
        reason = Reason(bus, SlowLLM(clk, 1500.0), SpySupervisor(CATALOG), FakeRemember(NOVEL),
                        slo=slo, warm=WarmPolicy(now=clk), now=clk)
        served: list = []
        bus.subscribe("reason.served", collect(served))
        await reason.start()
        await bus.publish(PRES)
        await bus.drain()
        self.assertFalse(served[0].payload["slo_met"])  # 1500ms > 1000ms budget
        self.assertEqual(slo.breaches, 1)
        await reason.stop()
        await bus.aclose()


if __name__ == "__main__":
    unittest.main()
