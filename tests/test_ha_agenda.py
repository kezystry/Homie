"""The live calendar/weather feed — HA → agenda.external → the morning briefing.

Proves the seam the owner asked be BUILT (not faked): a real HA query becomes a normalized
snapshot on the bus, a flaky source degrades instead of crashing, and the Personal tile folds
the snapshot's calendar events / to-dos / weather into the one capped briefing.

Run: python3 -m unittest discover -s tests
"""
import shutil
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.ha_agenda import EXTERNAL, HAAgendaSource, HAWsQuery, _calendar_event, _weather_state
from core.tile import Event, Supervisor

ROOT = Path(__file__).resolve().parents[1]


def at(hour: int, day: int = 20) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


class _FakeQuery:
    def __init__(self, *, events=None, todos=None, weather=None, boom=()):
        self._events, self._todos, self._weather, self._boom = events or [], todos or [], weather, boom

    async def calendar_events(self, start, end):
        if "calendar" in self._boom:
            raise RuntimeError("calendar down")
        return self._events

    async def todos(self):
        if "todos" in self._boom:
            raise RuntimeError("todo down")
        return self._todos

    async def weather(self):
        if "weather" in self._boom:
            raise RuntimeError("weather down")
        return self._weather


class SourceTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, query, topic="tick.hour"):
        bus = Bus()
        snaps: list = []
        bus.subscribe(EXTERNAL, lambda e: snaps.append(e))
        src = HAAgendaSource(bus, query)
        await src.start()
        await bus.publish(Event(topic, at(7), {}, source="clock"))
        await bus.drain()
        await src.stop()
        await bus.aclose()
        return snaps

    async def test_publishes_a_snapshot_on_the_hour(self) -> None:
        q = _FakeQuery(events=[{"start": at(9), "summary": "dentist"}],
                       todos=[{"summary": "pay rent", "due": at(12)}],
                       weather={"condition": "rain"})
        snaps = await self._run(q)
        self.assertEqual(len(snaps), 1)
        p = snaps[0].payload
        self.assertEqual(p["events"][0]["summary"], "dentist")
        self.assertEqual(p["todos"][0]["summary"], "pay rent")
        self.assertEqual(p["weather"], {"condition": "rain"})

    async def test_also_refreshes_on_morning(self) -> None:
        snaps = await self._run(_FakeQuery(weather={"condition": "sun"}), topic="time.morning")
        self.assertEqual(len(snaps), 1)

    async def test_one_flaky_source_does_not_sink_the_rest(self) -> None:
        q = _FakeQuery(events=[{"start": at(9), "summary": "dentist"}],
                       weather={"condition": "rain"}, boom=("calendar",))
        snaps = await self._run(q)
        self.assertEqual(snaps[0].payload["events"], [])          # calendar degraded to empty
        self.assertEqual(snaps[0].payload["weather"], {"condition": "rain"})  # weather survived

    async def test_total_outage_publishes_an_honest_empty_snapshot(self) -> None:
        snaps = await self._run(_FakeQuery(boom=("calendar", "todos", "weather")))
        self.assertEqual(snaps[0].payload, {"events": [], "todos": [], "weather": None})


class MapperTests(unittest.TestCase):
    def test_calendar_event_timed(self) -> None:
        ev = _calendar_event("calendar.work", {
            "start": {"dateTime": "2026-06-20T09:00:00"}, "end": {"dateTime": "2026-06-20T10:00:00"},
            "summary": "standup", "uid": "u1"})
        self.assertFalse(ev["all_day"])
        self.assertEqual(ev["summary"], "standup")
        self.assertEqual(ev["entity"], "calendar.work")
        self.assertIsNotNone(ev["start"])

    def test_calendar_event_all_day(self) -> None:
        ev = _calendar_event("calendar.home", {"start": {"date": "2026-06-20"}, "summary": "trip"})
        self.assertTrue(ev["all_day"])

    def test_weather_state_maps_attributes(self) -> None:
        w = _weather_state({"state": "cloudy", "attributes": {"temperature": 18, "templow": 9}})
        self.assertEqual(w, {"condition": "cloudy", "high": 18, "low": 9})


class WsQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_calendar_query_maps_results(self) -> None:
        # drive HAWsQuery against a stubbed client.request
        calls = []

        class StubClient:
            async def request(self, payload, timeout=None):
                calls.append(payload)
                if payload["type"] == "calendar/event/list":
                    return [{"start": {"dateTime": "2026-06-20T09:00:00"}, "summary": "x", "uid": "1"}]
                return []

        q = HAWsQuery(StubClient(), calendars=["calendar.work"])
        out = await q.calendar_events(at(0), at(0) + 86400)
        self.assertEqual(out[0]["summary"], "x")
        self.assertEqual(calls[0]["entity_id"], "calendar.work")


class TileFoldTests(unittest.IsolatedAsyncioTestCase):
    async def _personal(self, root: Path):
        shutil.copytree(ROOT / "tiles" / "personal", root / "personal")
        bus = Bus()
        sup = Supervisor(root, bus)
        await sup.start("personal")
        pages: list = []
        bus.subscribe("briefing.ready", lambda e: pages.append(e))
        return bus, sup, pages

    async def test_external_snapshot_folds_into_the_briefing(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, pages = await self._personal(root)
            # the live feed lands first (cached by the tile)...
            await bus.publish(Event(EXTERNAL, at(7), {
                "events": [{"start": at(9), "summary": "dentist", "uid": "e1", "entity": "calendar.work"}],
                "todos": [{"summary": "pay rent", "due": at(12), "uid": "t1", "entity": "todo.home"}],
                "weather": {"rain_onset_hour": 11},
            }, source="ha"))
            await bus.drain()
            # ...then the morning render folds it
            await bus.publish(Event("time.morning", at(7), {"hour": 7}, source="clock"))
            await bus.drain()
            self.assertTrue(pages)
            text = pages[-1].payload["text"]
            self.assertIn("dentist", text)        # calendar event on the timeline
            self.assertIn("pay rent", text)       # to-do in the due lane
            self.assertIn("rain from 11", text)   # weather woven as a clause
            await bus.aclose()

    async def test_briefing_without_a_feed_is_unchanged(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, pages = await self._personal(root)
            await bus.publish(Event("time.morning", at(7), {"hour": 7}, source="clock"))
            await bus.drain()
            self.assertTrue(pages)                 # still renders (routines/list only), no crash
            await bus.aclose()


if __name__ == "__main__":
    unittest.main()
