"""Nightly consolidation tests — the in-process half of the 23:59 ritual.

Run: python3 -m unittest discover -s tests
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.remember import Remember
from core.ritual import RitualGates, consolidate
from core.tile import Event


class SpySupervisor:
    def __init__(self, states: dict) -> None:
        self._states = dict(states)
        self.reloaded: list = []

    def status(self) -> dict:
        return dict(self._states)

    async def reload(self, name: str) -> None:
        self.reloaded.append(name)
        self._states[name] = "READY"  # a successful recovery


async def seeded_bus(root: Path):
    bus = Bus(log_path=root / "events.jsonl")
    remember = Remember()
    remember.attach(bus)
    for h in range(5):
        await bus.publish(Event("presence.arrived", 1000.0 + h, {"zone": "kitchen"}))
    await bus.drain()
    return bus, remember


class RitualTests(unittest.IsolatedAsyncioTestCase):
    async def test_consolidate_compacts_and_decays(self) -> None:
        with TemporaryDirectory() as d:
            bus, remember = await seeded_bus(Path(d))
            sup = SpySupervisor({"personal": "READY", "security": "READY"})
            report = await consolidate(bus=bus, remember=remember, supervisor=sup, now=2000.0)
            self.assertTrue(report.compacted)
            self.assertTrue(report.decayed)
            self.assertIsNotNone(bus.load_snapshot())  # the pattern of life was persisted
            await bus.aclose()

    async def test_l4_sweep_invoked(self) -> None:
        with TemporaryDirectory() as d:
            bus, remember = await seeded_bus(Path(d))
            sup = SpySupervisor({"security": "READY"})
            seen = []

            def sweep(now):
                seen.append(now)
                return 7

            report = await consolidate(bus=bus, remember=remember, supervisor=sup, now=2000.0, l4_sweep=sweep)
            self.assertEqual(seen, [2000.0])
            self.assertEqual(report.l4_swept, 7)
            await bus.aclose()

    async def test_abort_when_someone_home_skips_disruptive(self) -> None:
        with TemporaryDirectory() as d:
            bus, remember = await seeded_bus(Path(d))
            sup = SpySupervisor({"broken": "QUARANTINED"})
            report = await consolidate(
                bus=bus, remember=remember, supervisor=sup, now=2000.0,
                gates=RitualGates(is_someone_home=lambda: True),
            )
            self.assertTrue(report.aborted_disruptive)
            self.assertIn("home", report.abort_reasons)
            self.assertEqual(sup.reloaded, [])  # no self-heal while someone is home
            self.assertTrue(report.compacted)  # ...but the invisible consolidation still ran
            self.assertEqual(report.restart_decision, "none")
            await bus.aclose()

    async def test_each_gate_fences_independently(self) -> None:
        for gate in ("security_live", "gaming", "media_live"):
            with TemporaryDirectory() as d:
                bus, remember = await seeded_bus(Path(d))
                sup = SpySupervisor({"broken": "QUARANTINED"})
                report = await consolidate(
                    bus=bus, remember=remember, supervisor=sup, now=2000.0,
                    gates=RitualGates(**{gate: lambda: True}),
                )
                self.assertTrue(report.aborted_disruptive)
                self.assertEqual(sup.reloaded, [])
                await bus.aclose()

    async def test_self_heal_reloads_quarantined(self) -> None:
        with TemporaryDirectory() as d:
            bus, remember = await seeded_bus(Path(d))
            sup = SpySupervisor({"ok": "READY", "broken": "QUARANTINED"})
            report = await consolidate(bus=bus, remember=remember, supervisor=sup, now=2000.0)
            self.assertEqual(sup.reloaded, ["broken"])
            self.assertEqual(report.healed, ["broken"])
            await bus.aclose()

    async def test_restart_decision(self) -> None:
        with TemporaryDirectory() as d:
            bus, remember = await seeded_bus(Path(d))
            sup = SpySupervisor({"ok": "READY"})
            healthy = await consolidate(bus=bus, remember=remember, supervisor=sup, now=2000.0)
            self.assertEqual(healthy.restart_decision, "none")
            changed = await consolidate(bus=bus, remember=remember, supervisor=sup, now=2001.0, changed=True)
            self.assertEqual(changed.restart_decision, "soft")
            await bus.aclose()

    async def test_raising_gate_fences_tail_without_aborting(self) -> None:
        # a gate that raises must not crash the pass — it fences the disruptive tail
        with TemporaryDirectory() as d:
            bus, remember = await seeded_bus(Path(d))
            sup = SpySupervisor({"broken": "QUARANTINED"})

            def boom() -> bool:
                raise RuntimeError("gate boom")

            report = await consolidate(
                bus=bus, remember=remember, supervisor=sup, now=2000.0,
                gates=RitualGates(security_live=boom),
            )
            self.assertTrue(report.compacted)  # invisible consolidation still committed
            self.assertTrue(report.aborted_disruptive)
            self.assertIn("security", report.abort_reasons)  # raising gate counts as "disrupt-not"
            self.assertEqual(sup.reloaded, [])  # tail fenced — no self-heal
            await bus.aclose()

    async def test_raising_status_degrades_gracefully(self) -> None:
        with TemporaryDirectory() as d:
            bus, remember = await seeded_bus(Path(d))

            class BadSup:
                def status(self):
                    raise RuntimeError("status boom")

                async def reload(self, name):
                    pass

            report = await consolidate(bus=bus, remember=remember, supervisor=BadSup(), now=2000.0)
            self.assertTrue(report.compacted)  # the pass completed despite status() failing
            self.assertEqual(report.health, {})
            await bus.aclose()

    async def test_idempotent_at_same_now(self) -> None:
        with TemporaryDirectory() as d:
            bus, remember = await seeded_bus(Path(d))
            sup = SpySupervisor({"ok": "READY"})
            a = await consolidate(bus=bus, remember=remember, supervisor=sup, now=2000.0)
            b = await consolidate(bus=bus, remember=remember, supervisor=sup, now=2000.0)
            self.assertTrue(a.compacted and b.compacted)  # re-entrant, no crash, no double-fault
            await bus.aclose()


if __name__ == "__main__":
    unittest.main()
