"""DesktopAdapter — Homie's eyes on the main PC, as facts not frames.

Proves the adapter emits edge-triggered, scalar-only events (focus + media activity), passes
the same privacy guard as every perception source, and never carries a frame/blob.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest

from core.perceive import assert_emittable
from perception.desktop_adapter import FOCUS, MEDIA, DesktopAdapter


class _FakeProbe:
    def __init__(self, snaps):
        self._snaps = list(snaps)
        self._i = 0

    def snapshot(self):
        if self._i >= len(self._snaps):
            return {}
        s = self._snaps[self._i]
        self._i += 1
        return s


def drain(adapter):
    async def go():
        return [e async for e in adapter.events()]
    return asyncio.run(go())


async def _nosleep(_):
    return None


class DesktopAdapterTests(unittest.TestCase):
    def _adapter(self, snaps):
        return DesktopAdapter(_FakeProbe(snaps), sleep=_nosleep, max_polls=len(snaps))

    def test_focus_change_emits_once(self) -> None:
        snaps = [{"ts": 1.0, "app": "stremio"}, {"ts": 2.0, "app": "stremio"}]
        out = drain(self._adapter(snaps))
        focus = [e for e in out if e.topic == FOCUS]
        self.assertEqual(len(focus), 1)               # edge-triggered, not per poll
        self.assertEqual(focus[0].payload, {"app": "stremio"})

    def test_media_activity_with_title_and_kind(self) -> None:
        snaps = [{"ts": 5.0, "app": "stremio", "state": "playing", "kind": "film",
                  "title": "The Matrix"}]
        out = drain(self._adapter(snaps))
        media = [e for e in out if e.topic == MEDIA][0]
        self.assertEqual(media.payload["app"], "stremio")
        self.assertEqual(media.payload["state"], "playing")
        self.assertEqual(media.payload["kind"], "film")
        self.assertEqual(media.payload["title"], "The Matrix")

    def test_pause_then_resume_are_distinct_events(self) -> None:
        snaps = [{"ts": 1.0, "app": "stremio", "state": "playing", "title": "X"},
                 {"ts": 2.0, "app": "stremio", "state": "paused", "title": "X"},
                 {"ts": 3.0, "app": "stremio", "state": "playing", "title": "X"}]
        states = [e.payload["state"] for e in drain(self._adapter(snaps)) if e.topic == MEDIA]
        self.assertEqual(states, ["playing", "paused", "playing"])

    def test_every_event_passes_the_privacy_guard(self) -> None:
        snaps = [{"ts": 1.0, "app": "stremio", "state": "playing", "title": "A Private Film"}]
        for e in drain(self._adapter(snaps)):
            assert_emittable(e.topic, e.payload)      # raises if a frame/blob ever leaked
            self.assertNotIn("frame", e.payload)
            self.assertNotIn("poster", e.payload)

    def test_no_state_no_media_event(self) -> None:
        out = drain(self._adapter([{"ts": 1.0, "app": "firefox"}]))   # just browsing, nothing playing
        self.assertEqual([e for e in out if e.topic == MEDIA], [])

    def test_flaky_probe_does_not_crash(self) -> None:
        class _Boom:
            def snapshot(self): raise RuntimeError("x server gone")
        out = drain(DesktopAdapter(_Boom(), sleep=_nosleep, max_polls=2))
        self.assertEqual(out, [])                       # degraded to silence, no crash


if __name__ == "__main__":
    unittest.main()
