"""WatchLog — the full media history (titles + everything), taste, and recommendations.

Proves: every watch session is stored with its title; the tracker turns media events into
sessions; taste/prediction/recommendation are honest functions of the history; one-tap forget
and the private pause work.

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.tile import Event
from core.watchlog import (
    WatchLog, WatchSession, WatchTracker, predict, recommend, render_page, top_titles,
    understanding,
)

_BASE = datetime(2026, 6, 5, 0, 0, 0, tzinfo=timezone.utc)   # a Friday


def ts(day: int, hour: int) -> float:
    # `day` is an offset in days from the base Friday, `hour` the local hour
    return (_BASE + timedelta(days=day, hours=hour)).timestamp()


def sess(title, kind, day, hour, mins=90) -> WatchSession:
    return WatchSession.of(title, kind, "stremio", ts(day, hour), ts(day, hour) + mins * 60, tz=timezone.utc)


class StoreTests(unittest.TestCase):
    def test_records_with_title_and_persists(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "watch.json"
            wl = WatchLog(p)
            wl.record(sess("The Matrix", "film", 26, 21))
            self.assertEqual(WatchLog(p).sessions()[0].title, "The Matrix")   # title IS stored

    def test_forget_title_wipes_everywhere(self) -> None:
        with TemporaryDirectory() as d:
            wl = WatchLog(Path(d) / "watch.json")
            wl.record(sess("X", "film", 26, 21))
            wl.record(sess("Y", "series", 27, 20))
            self.assertEqual(wl.forget_title("X"), 1)
            self.assertEqual([s.title for s in wl.sessions()], ["Y"])

    def test_bounded(self) -> None:
        with TemporaryDirectory() as d:
            wl = WatchLog(Path(d) / "watch.json", keep=3)
            for i in range(6):
                wl.record(sess(f"t{i}", "film", 26, 21))
            self.assertEqual(len(wl.sessions()), 3)


class AnalysisTests(unittest.TestCase):
    def _history(self):
        s = []
        for wk in range(4):                              # 4 Fridays of films, comfort rewatch
            s.append(sess("Blade Runner", "film", 26 + wk * 7, 21))
        s.append(sess("Some Doc", "film", 28, 14))
        for wk in range(3):                              # weeknight series
            s.append(sess("The Wire", "series", 29 + wk, 20))
        return s

    def test_top_titles(self) -> None:
        top = top_titles(self._history())
        self.assertEqual(top[0][0], "Blade Runner")
        self.assertEqual(top[0][1], 4)                   # watched 4×

    def test_predict_for_a_slot(self) -> None:
        # a Friday evening → it expects a film, likely Blade Runner
        p = predict(self._history(), ts(26 + 28, 21), tz=timezone.utc)
        self.assertIsNotNone(p)
        self.assertEqual(p["kind"], "film")
        self.assertEqual(p["title"], "Blade Runner")

    def test_recommend_carries_why(self) -> None:
        recs = recommend(self._history(), ts(26 + 28, 21), tz=timezone.utc)
        self.assertTrue(recs)
        self.assertIn("why", recs[0])

    def test_understanding_is_honest_and_nonempty(self) -> None:
        lines = understanding(self._history())
        self.assertTrue(any("Blade Runner" in ln for ln in lines))   # the rewatch insight

    def test_render_page(self) -> None:
        page = render_page(self._history(), ts(26 + 28, 21), tz=timezone.utc)
        self.assertTrue(any("Picks for you" in ln for ln in page))


class TrackerTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self, d):
        bus = Bus()
        wl = WatchLog(Path(d) / "watch.json")
        tr = WatchTracker(bus, wl, tz="UTC")
        await tr.start()
        return bus, wl, tr

    async def _watch(self, bus, title, start, end, kind="film"):
        await bus.publish(Event("media.activity", start, {"app": "stremio", "state": "playing",
                                                          "kind": kind, "title": title}))
        await bus.publish(Event("media.activity", end, {"app": "stremio", "state": "playing",
                                                        "kind": kind, "title": title}))
        await bus.drain()

    async def test_sessionizes_and_records(self) -> None:
        with TemporaryDirectory() as d:
            bus, wl, tr = await self._setup(d)
            await self._watch(bus, "Dune", ts(26, 21), ts(26, 21) + 5400)   # ~90 min
            await bus.publish(Event("media.activity", ts(26, 23), {"app": "stremio",
                              "state": "stopped", "title": "Dune"}))
            await bus.drain()
            await tr.stop(); await bus.aclose()
            self.assertEqual(wl.sessions()[0].title, "Dune")

    async def test_private_pause_stores_nothing(self) -> None:
        with TemporaryDirectory() as d:
            bus, wl, tr = await self._setup(d)
            await bus.publish(Event("media.private", ts(26, 20), {"on": True}))
            await bus.drain()
            await self._watch(bus, "Secret Film", ts(26, 21), ts(26, 21) + 5400)
            await tr.stop(); await bus.aclose()
            self.assertEqual(wl.sessions(), [])          # nothing recorded while private

    async def test_a_blip_is_ignored(self) -> None:
        with TemporaryDirectory() as d:
            bus, wl, tr = await self._setup(d)
            await self._watch(bus, "Trailer", ts(26, 21), ts(26, 21) + 20)   # 20s — channel surf
            await tr.stop(); await bus.aclose()
            self.assertEqual(wl.sessions(), [])


if __name__ == "__main__":
    unittest.main()
