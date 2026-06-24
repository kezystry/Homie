"""Personal and Security tile tests — exercise the real tiles end to end.

Run: python3 -m unittest discover -s tests
"""
import shutil
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.remember import Remember
from core.tile import Event, FrictionSignal, Supervisor

ROOT = Path(__file__).resolve().parents[1]


def copy_tile(name: str, root: Path) -> None:
    """Copy a real tile into an isolated dir so its state/ never touches the repo."""
    shutil.copytree(ROOT / "tiles" / name, root / name)
    state = root / name / "state"
    if state.exists():
        shutil.rmtree(state)


def at(hour: int, day: int = 13) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


def collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


class PersonalTests(unittest.IsolatedAsyncioTestCase):
    async def test_offers_agenda_then_learns_silence(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            copy_tile("personal", root)
            bus = Bus()
            said: list[Event] = []
            bus.subscribe("interface.say", collect(said))
            sup = Supervisor(root, bus)
            await sup.start("personal")
            await sup.call_function("add_reminder", text="dentist at 3pm")

            await bus.publish(Event("presence.arrived", at(8), {"zone": "kitchen"}))
            await bus.drain()
            self.assertEqual(len(said), 1)
            self.assertIn("dentist", said[0].payload["text"])

            # push back -> friction -> Personal goes quiet
            await sup.deliver_friction(
                FrictionSignal(kind="remark", at=at(8), target_tile="personal", text="stop")
            )
            said.clear()
            await bus.publish(Event("presence.arrived", at(8, 14), {"zone": "kitchen"}))
            await bus.drain()
            self.assertEqual(said, [])
            await bus.aclose()


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.remember = Remember()
        for day in range(6, 13):  # normal: kitchen at 08:00 all week
            self.remember.model.observe(Event("presence.arrived", at(8, day), {"zone": "kitchen"}))

    async def test_normal_presence_no_alert(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            copy_tile("security", root)
            bus = Bus()
            alerts: list[Event] = []
            bus.subscribe("security.alert", collect(alerts))
            sup = Supervisor(root, bus, remember=self.remember)
            await sup.start("security")
            await bus.publish(Event("presence.arrived", at(8), {"zone": "kitchen"}))
            await bus.drain()
            self.assertEqual(alerts, [])
            await bus.aclose()

    async def test_novel_presence_alerts(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            copy_tile("security", root)
            bus = Bus()
            alerts: list[Event] = []
            bus.subscribe("security.alert", collect(alerts))
            sup = Supervisor(root, bus, remember=self.remember)
            await sup.start("security")
            await bus.publish(Event("presence.unknown", at(3), {"zone": "back_door"}))
            await bus.drain()
            self.assertEqual(len(alerts), 1)
            self.assertTrue(alerts[0].payload["novel"])
            self.assertEqual(alerts[0].payload["zone"], "back_door")
            await bus.aclose()


if __name__ == "__main__":
    unittest.main()
