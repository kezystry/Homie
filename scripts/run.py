"""Homie reasoning-node daemon entrypoint.

Boots the bus, Behavioral Analysis, and the tile Supervisor, then runs until
stopped. This is what the OS `homie.service` launches. Edge perception and the
mesh transport attach to the same bus as they come online.

    python3 scripts/run.py            # state in $HOMIE_STATE (default /var/lib/homie)
    HOMIE_STATE=./.state python3 scripts/run.py
"""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

log = logging.getLogger("homie.run")

from core.bus import Bus  # noqa: E402
from core.consent import Consent  # noqa: E402
from core.remember import Remember  # noqa: E402
from core.tile import Supervisor  # noqa: E402

STATE = Path(os.environ.get("HOMIE_STATE", "/var/lib/homie"))


COMPACT_THRESHOLD = int(os.environ.get("HOMIE_COMPACT_THRESHOLD", "5000"))
COMPACT_INTERVAL = float(os.environ.get("HOMIE_COMPACT_INTERVAL", "3600"))


async def _housekeep(bus: Bus, remember: Remember) -> None:
    """Periodically bound the durability log so it can't grow unbounded or wear
    the SD card. maybe_compact() no-ops until the append threshold is crossed.
    One bad cycle must never kill the loop (or compaction silently stops)."""
    while True:
        await asyncio.sleep(COMPACT_INTERVAL)
        try:
            remember.decay(time.time())  # age + prune the pattern of life, then consolidate
            await bus.maybe_compact(remember.snapshot)
        except Exception:
            log.exception("housekeep: compaction cycle failed; will retry")


def _supervise(task: asyncio.Task, restart) -> None:
    """Keep a long-lived background task alive: log and respawn on abnormal exit."""
    def _done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        log.error("background task exited (%r); restarting", t.exception())
        restart()
    task.add_done_callback(_done)


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

    def _spawn_housekeep() -> None:
        _supervise(asyncio.ensure_future(_housekeep(bus, remember)), _spawn_housekeep)

    _spawn_housekeep()  # held alive + respawned on abnormal exit
    await asyncio.Event().wait()  # run until the service stops us


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
