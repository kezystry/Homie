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


if __name__ == "__main__":
    unittest.main()
