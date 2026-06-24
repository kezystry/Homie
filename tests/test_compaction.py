"""Durability-log compaction + snapshot tests — stdlib unittest.

The load-bearing guarantee: snapshot + tail reconstructs the SAME pattern of life
as a full replay, and a crash at any step of compaction is recoverable without
loss or double-counting.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus, DurabilityLog
from core.remember import PatternModel, Remember
from core.tile import Event


def at(hour: int, day: int = 13) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


def ev(topic: str, ts: float, zone: str | None = None) -> Event:
    return Event(topic=topic, ts=ts, payload={"zone": zone} if zone is not None else {})


def expectations(r: Remember):
    """Sample the model across known keys/hours for equivalence assertions."""
    out = {}
    for topic, zone in (("presence.arrived", "kitchen"), ("motion.detected", "hall")):
        for h in (8, 22):
            e = r.model.expectation(topic, zone, at(h, 20))
            out[(topic, zone, h)] = (e.count, e.days, round(e.rate, 6), e.novel)
    return out


class PatternModelSnapshotTests(unittest.TestCase):
    def test_snapshot_restore_roundtrip(self) -> None:
        m = PatternModel()
        for d in (10, 11, 12):
            m.observe(ev("presence.arrived", at(8, d), "kitchen"))
        m.observe(ev("motion.detected", at(22, 10), None))  # None-zone key
        snap = m.snapshot()
        # survives a JSON round-trip (must be JSON-safe)
        snap = json.loads(json.dumps(snap))
        m2 = PatternModel()
        m2.restore(snap)
        a = m.expectation("presence.arrived", "kitchen", at(8, 20))
        b = m2.expectation("presence.arrived", "kitchen", at(8, 20))
        self.assertEqual((a.count, a.days, a.rate, a.novel), (b.count, b.days, b.rate, b.novel))
        # None-zone key round-trips
        self.assertFalse(m2.expectation("motion.detected", None, at(22, 20)).novel)


class CompactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_replay_is_tail_only_after_compact(self) -> None:
        with TemporaryDirectory() as d:
            bus = Bus(log_path=Path(d) / "events.jsonl")
            for i in range(3):
                await bus.publish(ev("presence.arrived", at(8), "kitchen"))
            bus.compact({"version": 1, "hours": 24, "keys": []})
            await bus.publish(ev("motion.detected", at(9), "hall"))
            await bus.aclose()
            tail = list(DurabilityLog(Path(d) / "events.jsonl").replay())
            self.assertEqual([e.topic for e in tail], ["motion.detected"])

    async def test_load_snapshot_roundtrip_and_corrupt(self) -> None:
        with TemporaryDirectory() as d:
            bus = Bus(log_path=Path(d) / "events.jsonl")
            await bus.publish(ev("presence.arrived", at(8), "kitchen"))
            bus.compact({"version": 1, "hours": 24, "keys": [{"x": 1}]})
            await bus.aclose()
            self.assertEqual(bus.load_snapshot(), {"version": 1, "hours": 24, "keys": [{"x": 1}]})
            # corrupt snapshot → None (caller falls back to full fold)
            (Path(d) / "events.snapshot.json").write_text("{not json", "utf-8")
            self.assertIsNone(bus.load_snapshot())

    async def test_snapshot_plus_tail_equals_full_replay(self) -> None:
        with TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            # full-replay reference (no compaction)
            ref_bus = Bus(log_path=path)
            events = [
                ev("presence.arrived", at(8, day), "kitchen") for day in (10, 11, 12)
            ] + [ev("motion.detected", at(22, day), "hall") for day in (10, 11)]
            for e in events:
                await ref_bus.publish(e)
            await ref_bus.aclose()
            ref = Remember()
            ref.bootstrap(Bus(log_path=path))
            ref_exp = expectations(ref)

            # now compact midway and keep going on a fresh path
            path2 = Path(d) / "log2" / "events.jsonl"
            live = Remember()
            bus = Bus(log_path=path2)
            live.attach(bus)
            for e in events[:3]:
                await bus.publish(e)
            await bus.drain()
            bus.compact(live.snapshot())  # snapshot covers the first 3
            for e in events[3:]:
                await bus.publish(e)
            await bus.drain()
            await bus.aclose()

            # a fresh boot from snapshot + tail must match the full replay
            booted = Remember()
            booted.bootstrap(Bus(log_path=path2))
            self.assertEqual(expectations(booted), ref_exp)

    async def test_maybe_compact_threshold(self) -> None:
        with TemporaryDirectory() as d:
            live = Remember()
            bus = Bus(log_path=Path(d) / "events.jsonl", compact_threshold=3)
            live.attach(bus)
            await bus.publish(ev("presence.arrived", at(8), "kitchen"))
            await bus.publish(ev("presence.arrived", at(8), "kitchen"))
            await bus.drain()
            self.assertFalse(await bus.maybe_compact(live.snapshot))  # below threshold
            await bus.publish(ev("presence.arrived", at(8), "kitchen"))
            await bus.drain()
            self.assertTrue(await bus.maybe_compact(live.snapshot))  # crossed
            self.assertIsNotNone(bus.load_snapshot())
            await bus.aclose()

    async def test_crash_before_snapshot_commit_no_loss(self) -> None:
        # simulate: live log rotated to segment <gen> but snapshot never committed
        with TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            bus = Bus(log_path=path)
            for day in (10, 11, 12):
                await bus.publish(ev("presence.arrived", at(8, day), "kitchen"))
            await bus.aclose()
            # crash mid-compact: rename live log to seg.1, no snapshot written
            (path.parent / "events.seg.1.jsonl").write_bytes(path.read_bytes())
            path.unlink()
            booted = Remember()
            booted.bootstrap(Bus(log_path=path))  # no snapshot ⇒ folds uncovered seg.1
            exp = booted.model.expectation("presence.arrived", "kitchen", at(8, 20))
            self.assertEqual(exp.count, 3)
            self.assertEqual(exp.days, 3)

    async def test_crash_before_segment_delete_no_double_count(self) -> None:
        # simulate: snapshot committed (gen 1), but the covered segment wasn't deleted
        with TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            live = Remember()
            bus = Bus(log_path=path)
            live.attach(bus)
            for day in (10, 11, 12):
                await bus.publish(ev("presence.arrived", at(8, day), "kitchen"))
            await bus.drain()
            bus.compact(live.snapshot())  # writes snapshot gen 1, deletes its segment
            await bus.aclose()
            # re-create the covered segment as if the delete never happened
            (path.parent / "events.seg.1.jsonl").write_text(
                json.dumps({"topic": "presence.arrived", "ts": at(8, 10), "payload": {"zone": "kitchen"}}) + "\n",
                "utf-8",
            )
            booted = Remember()
            booted.bootstrap(Bus(log_path=path))  # gen 1 covers seg.1 ⇒ must skip it
            exp = booted.model.expectation("presence.arrived", "kitchen", at(8, 20))
            self.assertEqual(exp.count, 3)  # not 4 — no double-count
            # and the stale covered segment was GC'd
            self.assertFalse((path.parent / "events.seg.1.jsonl").exists())


class FlushPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_batched_flush_no_loss_on_close(self) -> None:
        with TemporaryDirectory() as d:
            bus = Bus(log_path=Path(d) / "events.jsonl", flush_every=10)
            for _ in range(5):  # fewer than flush_every — buffered
                await bus.publish(ev("presence.arrived", at(8), "kitchen"))
            await bus.aclose()  # clean close must flush the remainder
            self.assertEqual(len(list(DurabilityLog(Path(d) / "events.jsonl").replay())), 5)


if __name__ == "__main__":
    unittest.main()
