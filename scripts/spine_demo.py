"""Runnable spine demo — the loop end to end on one node, through build_daemon.

    python3 scripts/spine_demo.py

Builds the REAL daemon graph (the same `core.daemon.build_daemon` the production
entrypoint uses), injecting a `FakeHome` and driving a scripted day by hand. Shows:
Personal offering the agenda, Security staying quiet for normal presence but
alerting on a novel 3am visitor, friction teaching Personal to go quiet, and — the
organism coming alive — Lighting driving a (fake) bulb on arrival, the home's echo
suppressed so it isn't mistaken for a human action, and a reversal teaching Lighting
to stay dark. Nothing leaves the process. This is the same graph the tests assert on
(tests/test_golden_loop.py turns these prints into enforced invariants).
"""
import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.act import ActMap  # noqa: E402
from core.daemon import DaemonConfig, build_daemon  # noqa: E402
from core.tile import ActionRef, Event, FrictionSignal  # noqa: E402


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
    home = FakeHome()
    # The same assembler production uses; we differ only by injection: a FakeHome,
    # a test act-map (light.living_room -> the home's light.lr entity), ephemeral state.
    state = Path(tempfile.mkdtemp(prefix="homie-demo-"))
    config = DaemonConfig(
        state=state,
        housekeep=False,  # the demo drives time by hand
        compact_threshold=0,
        act_map=ActMap.from_forward({"light.living_room": "light.lr"}),
    )
    daemon = build_daemon(home, None, config=config)

    # Seed a week of "arrives in the kitchen at 8am, living room at 9pm" so Security
    # treats those as normal. Seed the model directly (prior history) before start();
    # bootstrap won't clobber it (the log is empty).
    for day in range(6, 13):
        daemon.remember.model.observe(Event("presence.arrived", at(8, day), {"zone": "kitchen"}))
        daemon.remember.model.observe(Event("presence.arrived", at(21, day), {"zone": "living"}))

    await daemon.start()

    async def show(e: Event) -> None:
        print(f"   -> {e.topic}: {e.payload}")

    daemon.bus.subscribe("interface.say", show)
    daemon.bus.subscribe("security.alert", show)
    daemon.bus.subscribe("actuator.done", show)

    print("1) Morning, kitchen (normal pattern):")
    await daemon.bus.publish(Event("presence.arrived", at(8), {"zone": "kitchen"}))
    await daemon.bus.drain()

    print("2) 3am, back door, unrecognized (novel):")
    await daemon.bus.publish(Event("presence.unknown", at(3), {"zone": "back_door"}))
    await daemon.bus.drain()

    print('3) You tell Personal "stop" (friction) — it learns to stay quiet:')
    await daemon.sup.deliver_friction(
        FrictionSignal(kind="remark", at=at(8), target_tile="personal", text="stop"))
    await daemon.bus.publish(Event("presence.arrived", at(8, 14), {"zone": "kitchen"}))
    await daemon.bus.drain()
    print("   (silence — Personal no longer offers the agenda unprompted)")

    print("4) Evening arrival in the living room — Lighting turns the bulb on:")
    await daemon.bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
    await daemon.bus.drain()
    print(f"   (home driven: {home.driven[-1] if home.driven else None})")
    if home.driven:
        await home.emit("light.lr", home.driven[-1][1])  # the home echoes our own command...
        await daemon.bus.drain()
    print("   (echo suppressed by the canonicalizer — not mistaken for a human action)")

    print("5) You switch it off (friction) — Lighting learns to stay dark at this hour:")
    ref = ActionRef("demo", "lighting", "light.living_room", {"state": "on"}, at(21))
    await daemon.sup.deliver_friction(
        FrictionSignal(kind="reversal", at=at(21), target_tile="lighting",
                       reverses=ref, zone="living", actor="owner"))
    before = len(home.driven)
    await daemon.bus.publish(Event("presence.arrived", at(21, 14), {"zone": "living"}))
    await daemon.bus.drain()
    drove = len(home.driven) > before
    print(f"   (silence — the light stays off; home driven again? {drove})")

    await daemon.stop()


if __name__ == "__main__":
    asyncio.run(main())
