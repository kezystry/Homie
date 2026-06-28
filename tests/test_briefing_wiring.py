"""The morning surface, wired into the real graph (Phase C, slice 6).

Fires time.morning through build_daemon and proves: the briefing reaches the owner as ONE
GOVERNED line (interface.spoken, through the SpeechBudget waist — never a flood), the full
page is published on briefing.ready for the screen, learned routines + the owner's tasks both
appear, and a truly empty day stays silent.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from core.daemon import DaemonConfig, build_daemon
from core.tile import Event


def at(hour: int, day: int = 10) -> float:
    return datetime(2026, 3, day, hour, 0, 0, tzinfo=timezone.utc).timestamp()


class FakeHome:
    def __init__(self) -> None:
        self.driven: list = []

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler


async def _morning(*, with_routine: bool, with_task: bool):
    # An isolated state dir per daemon — tile state must not leak between runs (or into the repo).
    tmp = TemporaryDirectory()
    home = FakeHome()
    daemon = build_daemon(home, None, config=DaemonConfig(housekeep=False, state=Path(tmp.name)))
    await daemon.start()
    spoken, pages = [], []
    daemon.bus.subscribe("interface.spoken", lambda e: spoken.append(e))
    daemon.bus.subscribe("briefing.ready", lambda e: pages.append(e))
    try:
        if with_routine:
            # Teach the model a firm 8am kitchen routine across enough days to be 'firm'.
            for d in range(1, 13):
                daemon.remember.model.observe(Event("presence.arrived", at(8, d), {"zone": "kitchen"}))
        if with_task:
            await daemon.sup.call_function("add_task", text="Pay the electric bill")
        await daemon.bus.publish(Event("time.morning", at(7), {"hour": 7}, source="clock"))
        await daemon.bus.drain()
    finally:
        await daemon.stop()
        tmp.cleanup()
    return spoken, pages


class BriefingWiringTests(unittest.TestCase):
    def test_morning_speaks_one_governed_line_and_publishes_the_page(self) -> None:
        spoken, pages = asyncio.run(_morning(with_routine=True, with_task=True))
        # exactly one owner-facing spoken line, and it went through the governed channel
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0].payload.get("kind"), "proactive")
        # the full page is published for the screen and carries both the routine and the task
        self.assertEqual(len(pages), 1)
        text = pages[0].payload["text"]
        self.assertIn("kitchen", text)
        self.assertIn("Pay the electric bill", text)

    def test_quiet_day_stays_silent_but_still_renders_a_page(self) -> None:
        spoken, pages = asyncio.run(_morning(with_routine=False, with_task=False))
        self.assertEqual(spoken, [])                 # nothing on -> Homie says nothing
        self.assertEqual(len(pages), 1)              # ...but the screen still has an honest line
        self.assertIn("Quiet day", pages[0].payload["text"])


if __name__ == "__main__":
    unittest.main()
