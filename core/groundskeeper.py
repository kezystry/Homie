"""Groundskeeper — the storage limb of self-sufficiency (Charter 28a).

The owner asked for storage that grows EXTREMELY slowly and silently, and that only ever
speaks up when the disk is nearly full — never a running commentary on tidying. This is that:
a tiny background process, ticked from the daemon's housekeep loop (so it shares the one
process that owns `events.jsonl` — no second writer), that does two things:

  * **Silently densify under pressure.** When free space dips into the NOTICE band (or the live
    log tail grows too big), force a compaction — fold raw events into the snapshot — without a
    word. Memory gets *denser*, not just bigger; the owner hears nothing.
  * **Speak only when almost full.** A `storage.pressure` notice (and one governed spoken line)
    fires ONLY on a transition into LOW/CRITICAL, with hysteresis (different enter/exit
    thresholds so a value hovering at a boundary can't flap) and a 24h per-band debounce. Steady
    state at LOW for three days = one notice, not seventy-two.

It is read-only about the disk (`shutil.disk_usage`, stdlib) and never opens the log itself —
to densify it asks the bus, exactly like every other component. Destructive garbage collection
(rolling old GISTs up, dropping stale low-confidence beliefs, the forget-everywhere transaction)
is a SECOND increment that belongs behind the nightly ritual's abort gates; this first limb is
pure detection + the already-safe densify path, so it can never lose information.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.tile import Event

log = logging.getLogger("homie.groundskeeper")

PRESSURE = "storage.pressure"     # out: {"band": ..., "free": 0.xx} — only on worsening transition
SAY = "interface.say"             # out: one governed line, only when almost full

# Band order, worst last. _rank lets us compare "is this worse than that".
_BANDS = ("OK", "NOTICE", "LOW", "CRITICAL")


def _rank(band: str) -> int:
    return _BANDS.index(band) if band in _BANDS else 0


@dataclass(frozen=True)
class Bands:
    """Free-fraction thresholds with hysteresis: a band is ENTERED at the lower fraction and
    only CLEARED at the higher one, so a disk hovering at a boundary cannot notification-storm."""
    notice_in: float = 0.15
    notice_out: float = 0.20
    low_in: float = 0.10
    low_out: float = 0.14
    crit_in: float = 0.05
    crit_out: float = 0.08


class Groundskeeper:
    def __init__(self, state_dir: Path | str, bus, snapshot_provider: Callable[[], dict], *,
                 bands: Bands = Bands(), tail_max_bytes: int = 64 * 1024 * 1024,
                 renotify_seconds: float = 86400.0,
                 disk_usage: Callable[[str], object] = shutil.disk_usage) -> None:
        self.state_dir = Path(state_dir)
        self.bus = bus
        self.snapshot_provider = snapshot_provider
        self.bands = bands
        self.tail_max_bytes = tail_max_bytes
        self.renotify_seconds = renotify_seconds
        self._disk_usage = disk_usage
        self._band = "OK"
        self._last_notice: dict[str, float] = {}   # band -> ts of last spoken notice (debounce)

    # -- pure helpers (unit-testable without a disk) ------------------------- #
    def free_fraction(self) -> float:
        try:
            du = self._disk_usage(str(self.state_dir))
            return du.free / du.total if du.total else 1.0
        except OSError as ex:                       # path gone / unreadable → assume fine, log
            log.warning("groundskeeper: disk read failed (%r); assuming healthy", ex)
            return 1.0

    def _tail_bytes(self) -> int:
        p = self.state_dir / "events.jsonl"
        try:
            return p.stat().st_size
        except OSError:
            return 0

    def _next_band(self, free: float, current: str) -> str:
        """The hysteresis state machine. Worsen as soon as free drops below an enter-threshold;
        improve only once free rises above the (higher) exit-threshold of the current band."""
        b = self.bands
        # worsening is checked from worst to mild (the deepest breached band wins)
        if free < b.crit_in:
            return "CRITICAL"
        if free < b.low_in:
            return "LOW" if _rank(current) <= _rank("LOW") else current
        if free < b.notice_in:
            return "NOTICE" if _rank(current) <= _rank("NOTICE") else current
        # not below any enter-threshold → maybe clear, but only past this band's exit-threshold
        if current == "CRITICAL":
            return "LOW" if free < b.crit_out else self._clear_from("LOW", free)
        if current == "LOW":
            return "NOTICE" if free < b.low_out else self._clear_from("NOTICE", free)
        if current == "NOTICE":
            return "NOTICE" if free < b.notice_out else "OK"
        return "OK"

    def _clear_from(self, band: str, free: float) -> str:
        """Cascade a clear: e.g. clearing CRITICAL may also clear LOW/NOTICE in one step if free
        has risen well past their exit-thresholds."""
        b = self.bands
        if band == "LOW":
            return "NOTICE" if free < b.low_out else ("NOTICE" if free < b.notice_out else "OK")
        if band == "NOTICE":
            return "NOTICE" if free < b.notice_out else "OK"
        return "OK"

    def _debounced(self, band: str, now: float) -> bool:
        last = self._last_notice.get(band)
        return last is None or (now - last) >= self.renotify_seconds

    # -- the background tick ------------------------------------------------- #
    async def tick(self, now: float) -> str:
        free = self.free_fraction()
        new_band = self._next_band(free, self._band)

        # Silently densify: on a worsening transition into NOTICE+, or if the live tail is too big.
        worsening = _rank(new_band) > _rank(self._band)
        if (worsening and _rank(new_band) >= _rank("NOTICE")) or self._tail_bytes() > self.tail_max_bytes:
            try:
                self.bus.compact(self.snapshot_provider())   # fold raw events into the snapshot
                log.info("groundskeeper: densified (band=%s, free=%.2f)", new_band, free)
            except Exception as ex:                          # never let hygiene kill the loop
                log.warning("groundskeeper: densify failed (%r)", ex)

        # Speak ONLY when crossing into LOW/CRITICAL (worsening), debounced per band.
        if new_band != self._band:
            prev, self._band = self._band, new_band
            if worsening and _rank(new_band) >= _rank("LOW") and self._debounced(new_band, now):
                self._last_notice[new_band] = now
                await self._notify(new_band, free, now)
            elif not worsening:
                log.info("groundskeeper: storage recovered to %s (free=%.2f)", new_band, free)
        return new_band

    async def _notify(self, band: str, free: float, now: float) -> None:
        await self.bus.publish(Event(PRESSURE, now, {"band": band, "free": round(free, 3)},
                                     source="groundskeeper"))
        pct = round(free * 100)
        if band == "CRITICAL":
            text = f"Storage is critically low ({pct}% free) — I'm freeing what I safely can."
            kind = "alert"          # exempt from the speech budget — this must be heard
        else:
            text = f"Storage is getting low ({pct}% free). I'll keep tidying; no action needed yet."
            kind = "proactive"      # governed — a single, rare, low-priority heads-up
        await self.bus.publish(Event(SAY, now, {"text": text, "kind": kind}, source="groundskeeper"))
