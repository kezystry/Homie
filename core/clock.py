"""Clock — the heartbeat the event-reactive system otherwise lacks.

Homie is event-driven, which hides a structural gap (second-review N1): without a
clock, every "after N minutes / at dusk / each morning" behavior secretly depends on
an *unrelated* future event arriving — and in a genuinely empty room none does, so
the lighting auto-off never fires. The Clock gives the bus a sense of time passing:

  - it emits `tick.minute` / `tick.hour` on a wall-clock cadence, and
  - it serves a TIMER SEAM: a tile (or anything) publishes `timer.set` with an
    `after` (seconds) and a `key`, and later receives a single `timer.fired` for that
    key — even if nothing else ever happens in the home.

Time and sleep are injectable so tests are deterministic and never actually wait. The
Clock is wired unconditionally by `build_daemon`; its tick loop simply parks on
`sleep` between ticks (and is cancelled on shutdown), so it adds no cost to a test.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from core.tile import Event

log = logging.getLogger("homie.clock")

TIMER_SET = "timer.set"        # in:  {"after": seconds, "key": str, "data": any?}
TIMER_CANCEL = "timer.cancel"  # in:  {"key": str} — drop a pending timer, no fire
TIMER_FIRED = "timer.fired"    # out: {"key": str, "data": any?}
TICK_MINUTE = "tick.minute"
TICK_HOUR = "tick.hour"
TIME_MORNING = "time.morning"  # out: {"hour": h} — once per local day at/after the morning hour
DEFAULT_MORNING_HOUR = 7


class Clock:
    """A single time producer on the bus. `now`/`sleep` are injectable; `tick_seconds`
    is the cadence of `tick.minute` (an hour boundary also emits `tick.hour`)."""

    def __init__(
        self,
        bus,
        *,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        tick_seconds: float = 60.0,
        morning_hour: int = DEFAULT_MORNING_HOUR,
        tz: str | None = None,
    ) -> None:
        self.bus = bus
        self._now = now
        self._sleep = sleep
        self._tick_seconds = max(0.0, tick_seconds)
        self._morning_hour = morning_hour
        self._tz = ZoneInfo(tz) if tz else (ZoneInfo(os.environ["HOMIE_TZ"]) if os.environ.get("HOMIE_TZ") else None)
        self._last_morning: str | None = None  # local date we last fired time.morning on
        self._subs: list = []
        self._tick_task: asyncio.Task | None = None
        self._timers: dict[object, asyncio.Task] = {}

    async def start(self) -> None:
        self._subs = [
            self.bus.subscribe(TIMER_SET, self._on_set, owner="clock"),
            self.bus.subscribe(TIMER_CANCEL, self._on_cancel, owner="clock"),
        ]
        self._tick_task = asyncio.ensure_future(self._run_ticks())

    async def stop(self) -> None:
        for sub in self._subs:
            self.bus.unsubscribe(sub)
        self._subs = []
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None
        for task in list(self._timers.values()):
            task.cancel()
        self._timers.clear()

    # -- the tick loop -------------------------------------------------------- #
    async def _run_ticks(self) -> None:
        last_hour: int | None = None
        try:
            while True:
                await self._sleep(self._tick_seconds)
                now = self._now()
                await self.bus.publish(Event(TICK_MINUTE, now, {}, source="clock"))
                hour = int(now // 3600)
                if hour != last_hour:
                    last_hour = hour
                    await self.bus.publish(Event(TICK_HOUR, now, {}, source="clock"))
                await self._maybe_morning(now)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("clock: tick loop failed")

    async def _maybe_morning(self, now: float) -> None:
        """Fire `time.morning` exactly once on each local day, the first tick at or after the
        morning hour — the trigger the day briefing wakes on. Event-clocked off `now`, so a
        replayed log reproduces it deterministically; the local date gates the once-a-day."""
        local = datetime.fromtimestamp(now, self._tz) if self._tz else datetime.fromtimestamp(now)
        today = local.date().isoformat()
        if local.hour >= self._morning_hour and self._last_morning != today:
            self._last_morning = today
            await self.bus.publish(Event(TIME_MORNING, now, {"hour": local.hour}, source="clock"))

    # -- the timer seam ------------------------------------------------------- #
    async def _on_set(self, event: Event) -> None:
        after = (event.payload or {}).get("after")
        key = (event.payload or {}).get("key")
        if key is None or not isinstance(after, (int, float)) or isinstance(after, bool) or after < 0:
            log.warning("clock: ignoring malformed timer.set %r", event.payload)
            return
        # Setting a timer with an existing key REPLACES it (debounce/rearm semantics).
        existing = self._timers.pop(key, None)
        if existing is not None:
            existing.cancel()
        data = (event.payload or {}).get("data")
        self._timers[key] = asyncio.ensure_future(self._fire_after(float(after), key, data))

    async def _on_cancel(self, event: Event) -> None:
        key = (event.payload or {}).get("key")
        if key is not None:
            self.cancel(key)

    async def _fire_after(self, after: float, key: object, data) -> None:
        try:
            await self._sleep(after)
        except asyncio.CancelledError:
            return  # rearmed or cancelled — no fire
        self._timers.pop(key, None)
        await self.bus.publish(Event(TIMER_FIRED, self._now(), {"key": key, "data": data}, source="clock"))

    def cancel(self, key: object) -> bool:
        """Cancel a pending timer by key (no `timer.fired`). Returns whether one was
        pending. (Publishing `timer.set` with the same key + a new `after` rearms it.)"""
        task = self._timers.pop(key, None)
        if task is None:
            return False
        task.cancel()
        return True
