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
from core.consent import Consent  # noqa: E402
from core.remember import Remember  # noqa: E402
from core.tile import Supervisor  # noqa: E402

STATE = Path(os.environ.get("HOMIE_STATE", "/var/lib/homie"))


COMPACT_THRESHOLD = int(os.environ.get("HOMIE_COMPACT_THRESHOLD", "5000"))
COMPACT_INTERVAL = float(os.environ.get("HOMIE_COMPACT_INTERVAL", "3600"))


async def _housekeep(bus: Bus, remember: Remember) -> None:
    """Periodically bound the durability log so it can't grow unbounded or wear
    the SD card. maybe_compact() no-ops until the append threshold is crossed."""
    while True:
        await asyncio.sleep(COMPACT_INTERVAL)
        await bus.maybe_compact(remember.snapshot)


async def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    bus = Bus(log_path=STATE / "events.jsonl", compact_threshold=COMPACT_THRESHOLD)
    remember = Remember()
    remember.bootstrap(bus)  # rebuild the pattern of life from snapshot + tail
    remember.attach(bus)  # keep learning from live perception
    consent = Consent(bus)  # the confirmation gate (answered by gesture/voice)
    await consent.start()
    sup = Supervisor(ROOT / "tiles", bus, remember=remember, consent=consent)
    await sup.start_all()
    print(f"homie: up with tiles {sup.status()}", flush=True)
    asyncio.ensure_future(_housekeep(bus, remember))
    await asyncio.Event().wait()  # run until the service stops us


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
