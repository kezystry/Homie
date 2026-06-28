"""Self-improvement — the nightly "am I fitting you better?" loop.

The project's own success signal (docs/DESIGN.md) is a **declining rate of corrections**: a
home that needs you to fix it less often is a home that learned. This counts the day's
corrections (a human reversing Homie's own act, from the StateReconciler), keeps a per-day
history, and each morning speaks ONE honest line about the trend — measurable self-improvement,
no new model, no overclaim. Pure trend math + a small bus tracker.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.tile import Event

log = logging.getLogger("homie.selfimprove")

CORRECTION = "friction.correction"   # in: a human reversed Homie's own act (the measurable signal)
SAY = "interface.say"                # out: one governed morning line about the trend
TIME_MORNING = "time.morning"
_WINDOW = 7                          # days in each comparison window


# --------------------------------------------------------------------------- #
# Pure trend math over a {date_iso: count} history
# --------------------------------------------------------------------------- #
def _recent(history: dict[str, int], days: int, *, before: str | None = None) -> list[int]:
    keys = sorted(k for k in history if before is None or k < before)
    return [history[k] for k in keys[-days:]]


def average(history: dict[str, int], days: int = _WINDOW, *, before: str | None = None) -> float:
    vals = _recent(history, days, before=before)
    return sum(vals) / len(vals) if vals else 0.0


def trend(history: dict[str, int]) -> str:
    """'down' (improving) / 'up' (more corrections) / 'steady' — this week vs the week before.
    Needs at least a few days of evidence; otherwise 'new' (not enough to claim a direction)."""
    if len(history) < 4:
        return "new"
    keys = sorted(history)
    split = keys[-_WINDOW] if len(keys) > _WINDOW else keys[len(keys) // 2]
    this = average(history, _WINDOW)
    prior = average(history, _WINDOW, before=split)
    if prior == 0.0 and this == 0.0:
        return "steady"
    if this < prior - 0.5:
        return "down"
    if this > prior + 0.5:
        return "up"
    return "steady"


def note(history: dict[str, int], yesterday_count: int) -> str | None:
    """One honest morning line, or None when there's nothing worth saying yet."""
    if len(history) < 3:
        return None  # too early to claim a trend — stay quiet (honest-empty)
    avg = average(history)
    t = trend(history)
    head = f"Yesterday I needed {yesterday_count} correction{'s' if yesterday_count != 1 else ''}."
    if t == "down":
        return f"{head} That's fewer than lately — I'm fitting you a little better."
    if t == "up":
        return f"{head} A bit more than usual — still learning your preferences."
    return f"{head} About my usual ({avg:.1f}/day) — settling in."


# --------------------------------------------------------------------------- #
# The nightly tracker (bus)
# --------------------------------------------------------------------------- #
class ImproveTracker:
    """Count corrections per day; each morning, finalize yesterday and speak the trend line."""

    def __init__(self, bus, *, state_path: Path | str | None = None, tz: str | None = None) -> None:
        self.bus = bus
        self._tz = ZoneInfo(tz) if tz else None
        self._path = Path(state_path) if state_path else None
        self._counts: dict[str, int] = self._load()
        self._subs: list = []

    async def start(self) -> None:
        self._subs = [self.bus.subscribe(CORRECTION, self._on_correction, owner="improve"),
                      self.bus.subscribe(TIME_MORNING, self._on_morning, owner="improve")]

    async def stop(self) -> None:
        for s in self._subs:
            self.bus.unsubscribe(s)
        self._subs = []

    def _date(self, ts: float) -> str:
        dt = datetime.fromtimestamp(ts, self._tz) if self._tz else datetime.fromtimestamp(ts)
        return dt.date().isoformat()

    async def _on_correction(self, event: Event) -> None:
        self._counts[self._date(event.ts)] = self._counts.get(self._date(event.ts), 0) + 1
        self._save()

    async def _on_morning(self, event: Event) -> None:
        yesterday = self._date(event.ts - 86400.0)
        count = self._counts.get(yesterday, 0)
        line = note(self._counts, count)
        if line:
            await self.bus.publish(Event(SAY, event.ts, {"text": line, "kind": "proactive"},
                                         source="improve"))

    # -- persistence (best-effort) ------------------------------------------- #
    def _load(self) -> dict[str, int]:
        if self._path is None:
            return {}
        try:
            return {str(k): int(v) for k, v in json.loads(self._path.read_text("utf-8")).items()}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # keep the history bounded — the last ~90 days is plenty for a trend
            keys = sorted(self._counts)[-90:]
            self._counts = {k: self._counts[k] for k in keys}
            self._path.write_text(json.dumps(self._counts, separators=(",", ":")), "utf-8")
        except OSError:
            pass
