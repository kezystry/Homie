"""Runnable spine demo — the loop end to end on one node.

    python3 scripts/spine_demo.py

Boots the bus, Behavioral Analysis (Remember), and the Supervisor with the real
Personal and Security tiles. Seeds a week of normal morning kitchen presence,
then shows: Personal offering the agenda, Security staying quiet for normal
presence but alerting on a novel 3am visitor, and friction teaching Personal to
go quiet. Nothing leaves the process; this is the whole spine in ~40 lines.
"""
import asyncio
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.bus import Bus  # noqa: E402
from core.remember import Remember  # noqa: E402
from core.tile import Event, FrictionSignal, Supervisor  # noqa: E402


def at(hour: int, day: int = 13) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


async def main() -> None:
    bus = Bus()
    remember = Remember()
    for day in range(6, 13):  # a week of "arrives in the kitchen around 8am"
        remember.model.observe(Event("presence.arrived", at(8, day), {"zone": "kitchen"}))
    # Security evaluates each event against this prior history (evaluate-then-learn);
    # we don't attach live recording here so the demo shows true novelty detection.

    # Run against a fresh copy of the tiles so the demo is idempotent and never
    # writes tile state back into the repo.
    workdir = Path(tempfile.mkdtemp(prefix="homie-demo-"))
    tiles = workdir / "tiles"
    tiles.mkdir()
    for name in ("personal", "security"):
        shutil.copytree(ROOT / "tiles" / name, tiles / name)

    sup = Supervisor(tiles, bus, remember=remember)
    await sup.start("personal")
    await sup.start("security")
    await sup.call_function("add_reminder", text="dentist at 3pm")

    async def show(e: Event) -> None:
        print(f"   -> {e.topic}: {e.payload}")

    bus.subscribe("interface.say", show)
    bus.subscribe("security.alert", show)

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

    await bus.aclose()
    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
