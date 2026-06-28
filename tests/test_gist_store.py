"""GIST slice 7 — the store + collector + the nightly ritual wiring.

Proves the distill actually RUNS and PERSISTS: a `.ddn` round-trips byte-exact (and survives a
corrupt file as honest-empty), the collector maps the day's bus events to plain tokens and folds
them once a night, an off-limits zone never reaches disk, and `ritual.consolidate` invokes the
fold before it rotates the raw log away.

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.gist import encode_state, fold_day, render_brief
from core.gist_store import GistCollector, GistStore, event_tokens
from core.ritual import RitualGates, consolidate
from core.tile import Event


def ts(hour: int, day: int = 29) -> float:
    return datetime(2026, 6, day, hour, 0, 0, tzinfo=timezone.utc).timestamp()


class StoreTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with TemporaryDirectory() as d:
            store = GistStore(Path(d) / "memory.ddn")
            state = fold_day([], [], daytype="wd")           # empty but valid
            state = fold_day(state, [], daytype="wd")
            store.save(state)
            self.assertEqual(encode_state(store.load()), encode_state(state))

    def test_missing_file_is_empty_not_a_crash(self) -> None:
        self.assertEqual(GistStore("/nonexistent/memory.ddn").load(), [])

    def test_corrupt_file_is_empty_not_a_crash(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "memory.ddn"
            p.write_bytes(b"\xff\xff not valid gist \x00")
            self.assertEqual(GistStore(p).load(), [])         # honest-empty


class MapperTests(unittest.TestCase):
    def test_presence_and_actuator_map(self) -> None:
        self.assertEqual(event_tokens(Event("presence.arrived", 0.0, {"zone": "living"})),
                         ("home", "living"))
        self.assertEqual(event_tokens(Event("actuator.done", 0.0, {"actuator": "light.kitchen"})),
                         ("light", "kitchen"))

    def test_uninteresting_events_are_skipped(self) -> None:
        self.assertIsNone(event_tokens(Event("chat.message", 0.0, {"text": "hi"})))
        self.assertIsNone(event_tokens(Event("presence.arrived", 0.0, {})))   # no zone


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_buffers_and_folds_a_day(self) -> None:
        with TemporaryDirectory() as d:
            bus = Bus()
            store = GistStore(Path(d) / "memory.ddn")
            col = GistCollector(bus, store, tz="UTC")
            await col.start()
            for day in range(20):                              # 20 days of the same morning routine
                await bus.publish(Event("actuator.done", ts(7, 1 + day), {"actuator": "light.kitchen"}))
                await bus.drain()
                col.fold(ts(23, 1 + day))                      # nightly fold
            await col.stop()
            await bus.aclose()
            lines = render_brief(store.load())
            self.assertTrue(any("kitchen" in ln for ln in lines))   # it learned the routine
            self.assertTrue(any("you" in ln.lower() for ln in lines))

    async def test_empty_day_folds_nothing(self) -> None:
        with TemporaryDirectory() as d:
            bus = Bus()
            store = GistStore(Path(d) / "memory.ddn")
            col = GistCollector(bus, store, tz="UTC")
            await col.start()
            self.assertEqual(col.fold(ts(23)), 0)              # nothing buffered → no-op
            await col.stop(); await bus.aclose()

    async def test_off_zone_never_reaches_disk(self) -> None:
        with TemporaryDirectory() as d:
            bus = Bus()
            store = GistStore(Path(d) / "memory.ddn")
            col = GistCollector(bus, store, tz="UTC", off_zones=frozenset({"mum_flat"}))
            await col.start()
            await bus.publish(Event("presence.arrived", ts(9), {"zone": "mum_flat"}))
            await bus.publish(Event("actuator.done", ts(9), {"actuator": "light.living_room"}))
            await bus.drain()
            col.fold(ts(23))
            await col.stop(); await bus.aclose()
            toks = {t for s in store.load() for t in s.tokens}
            self.assertNotIn("mum_flat", toks)                 # OFF-fenced before persistence
            self.assertIn("living_room", toks)


class RitualWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_consolidate_invokes_the_fold(self) -> None:
        # A fake remember/bus so consolidate runs; the gist_fold hook must be called with `now`.
        class _Rem:
            def decay(self, now): pass
            def snapshot(self): return {}
        class _Bus:
            def compact(self, snap): pass
        class _Sup:
            def status(self): return {}
        called: list = []
        report = await consolidate(bus=_Bus(), remember=_Rem(), supervisor=_Sup(), now=123.0,
                                   gist_fold=lambda now: called.append(now) or 4)
        self.assertEqual(called, [123.0])
        self.assertEqual(report.gist_folded, 4)               # recorded on the report

    async def test_fold_failure_does_not_abort_consolidation(self) -> None:
        class _Rem:
            def __init__(self): self.decayed = False
            def decay(self, now): self.decayed = True
            def snapshot(self): return {}
        class _Bus:
            def compact(self, snap): pass
        class _Sup:
            def status(self): return {}
        rem = _Rem()
        def boom(now): raise RuntimeError("distill blew up")
        report = await consolidate(bus=_Bus(), remember=rem, supervisor=_Sup(), now=1.0,
                                   gist_fold=boom)
        self.assertTrue(rem.decayed)                           # consolidation still ran
        self.assertEqual(report.gist_folded, 0)


if __name__ == "__main__":
    unittest.main()
