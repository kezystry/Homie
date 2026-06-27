"""Runnable spine demo — the loop end to end on one node.

    python3 scripts/spine_demo.py

Boots the bus, Behavioral Analysis (Remember), and the Supervisor with the real
Personal, Security, and Lighting tiles. Seeds a week of normal morning kitchen
presence, then shows: Personal offering the agenda, Security staying quiet for
normal presence but alerting on a novel 3am visitor, friction teaching Personal to
go quiet, and — the organism coming alive — Lighting driving a (fake) bulb on
arrival, the home's echo suppressed so it isn't mistaken for a human action, and a
reversal teaching Lighting to stay dark. Nothing leaves the process.
"""
import asyncio
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.act import Act, ActMap, CommandLog  # noqa: E402
from core.bus import Bus  # noqa: E402
from core.canonical import ha_canonical  # noqa: E402
from core.reconcile import StateReconciler  # noqa: E402
from core.remember import Remember  # noqa: E402
from core.tile import ActionRef, Event, FrictionSignal, Supervisor  # noqa: E402


class FakeHome:
    """Stands in for the Home Assistant/MQTT client: records drives and lets the
    demo replay the home's state echoes and a human's manual change."""

    def __init__(self) -> None:
        self.driven: list = []
        self._handler = None

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler

    async def emit(self, entity_id, value) -> None:
        if self._handler:
            await self._handler(entity_id, value)


def at(hour: int, day: int = 13) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


async def main() -> None:
    bus = Bus()
    remember = Remember()
    for day in range(6, 13):  # a week of "arrives in the kitchen at 8am, living room at 9pm"
        remember.model.observe(Event("presence.arrived", at(8, day), {"zone": "kitchen"}))
        remember.model.observe(Event("presence.arrived", at(21, day), {"zone": "living"}))
    # Security evaluates each event against this prior history (evaluate-then-learn);
    # we don't attach live recording here so the demo shows true novelty detection.

    # Run against a fresh copy of the tiles so the demo is idempotent and never
    # writes tile state back into the repo.
    workdir = Path(tempfile.mkdtemp(prefix="homie-demo-"))
    tiles = workdir / "tiles"
    tiles.mkdir()
    for name in ("personal", "security", "lighting"):
        shutil.copytree(ROOT / "tiles" / name, tiles / name)

    sup = Supervisor(tiles, bus, remember=remember)
    await sup.start("personal")
    await sup.start("security")
    await sup.start("lighting")
    await sup.call_function("add_reminder", text="dentist at 3pm")

    # The home gateway + the friction producer, wired with the value canonicalizer
    # so the home's echo of Homie's own command is suppressed (not read as a human
    # reversal). light.living -> the home's light.lr entity.
    home = FakeHome()
    commands = CommandLog(canonical=ha_canonical)
    act = Act(bus, home, commands, ActMap.from_forward({"light.living": "light.lr"}))
    await act.start()
    rec = StateReconciler(sup, commands, {"light.lr": "light.living"}, on_echo=act.confirm)
    rec.attach(home)

    async def show(e: Event) -> None:
        print(f"   -> {e.topic}: {e.payload}")

    bus.subscribe("interface.say", show)
    bus.subscribe("security.alert", show)
    bus.subscribe("actuator.done", show)

    print("1) Morning, kitchen (normal pattern):")
    await bus.publish(Event("presence.arrived", at(8), {"zone": "kitchen"}))
    await bus.drain()

    print("2) 3am, back door, unrecognized (novel):")
    await bus.publish(Event("presence.unknown", at(3), {"zone": "back_door"}))
    await bus.drain()

    print('3) You tell Personal "stop" (friction) — it learns to stay quiet:')
    await sup.deliver_friction(FrictionSignal(kind="remark", at=at(8), target_tile="personal", text="stop"))
    await bus.publish(Event("presence.arrived", at(8, 14), {"zone": "kitchen"}))
    await bus.drain()
    print("   (silence — Personal no longer offers the agenda unprompted)")

    print("4) Evening arrival in the living room — Lighting turns the bulb on:")
    await bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
    await bus.drain()
    print(f"   (home driven: {home.driven[-1]})")
    await home.emit("light.lr", {"state": "on"})  # the home echoes our own command...
    await bus.drain()
    print("   (echo suppressed by the canonicalizer — not mistaken for a human action)")

    print("5) You switch it off (friction) — Lighting learns to stay dark at this hour:")
    ref = ActionRef("demo", "lighting", "light.living", {"state": "on"}, at(21))
    await sup.deliver_friction(
        FrictionSignal(kind="reversal", at=at(21), target_tile="lighting",
                       reverses=ref, zone="living", actor="owner")
    )
    before = len(home.driven)
    await bus.publish(Event("presence.arrived", at(21, 14), {"zone": "living"}))
    await bus.drain()
    drove = len(home.driven) > before
    print(f"   (silence — the light stays off; home driven again? {drove})")

    await act.stop()
    await bus.aclose()
    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
