"""Homie reasoning-node daemon entrypoint.

Boots the bus, Behavioral Analysis, and the tile Supervisor, then runs until
stopped. This is what the OS `homie.service` launches. Edge perception and the
mesh transport attach to the same bus as they come online.

    python3 scripts/run.py            # state in $HOMIE_STATE (default /var/lib/homie)
    HOMIE_STATE=./.state python3 scripts/run.py
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.bus import Bus  # noqa: E402
from core.remember import Remember  # noqa: E402
from core.tile import Supervisor  # noqa: E402

STATE = Path(os.environ.get("HOMIE_STATE", "/var/lib/homie"))


async def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    bus = Bus(log_path=STATE / "events.jsonl")
    remember = Remember()
    remember.bootstrap(bus)  # rebuild the pattern of life from the durability log
    remember.attach(bus)  # keep learning from live perception
    sup = Supervisor(ROOT / "tiles", bus, remember=remember)
    await sup.start_all()
    print(f"homie: up with tiles {sup.status()}", flush=True)
    await asyncio.Event().wait()  # run until the service stops us


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
