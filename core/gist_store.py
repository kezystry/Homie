"""GIST store + collector — persist the distilled memory and feed it the day's events.

Slice 7 wiring: the fold (`core/gist.py`) is pure; this is the live plumbing around it.

  * `GistStore` — load/save the schema state to a single `.ddn` file (the byte-exact
    `encode_state`/`decode_state`), written atomically (temp + fsync + replace) so a crash can
    never tear it. A missing or corrupt file loads as empty memory (honest-empty, never a crash).
  * `GistCollector` — a bus subscriber that buffers the day's GIST-worthy events as
    `(minute, tokens)` and, once a night, folds them into the store and clears the buffer. The
    day-type is derived from the date + whether anyone was seen home (none → 'away'). Raw events
    never persist; only the distilled schema state does.

The collector touches no raw imagery and stores no identifiers — it maps an event to a few
plain tokens (topic tail + zone) and OFF-fences any off-limits zone before it can become a line.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.gist import Schema, daytype_of, decode_state, encode_state, fold_day
from core.tile import Event

log = logging.getLogger("homie.gist")

# Topics the distill cares about, and how each maps to plain tokens. The zone (when present)
# is the second token, so the OFF-fence can reject an off-limits room. Everything else is
# ignored — the GIST is a memory of life-shape, not a firehose.
_PRESENCE = {"presence.arrived", "occupancy.changed"}
_ACTUATOR = "actuator.done"
_MEDIA = "media.activity"   # the desktop media adapter's normalized event (app/kind/state only)


def event_tokens(event: Event) -> tuple[str, ...] | None:
    """Map a bus event to GIST tokens, or None to skip it. Plain words only — no ids, no blobs."""
    p = event.payload or {}
    if event.topic in _PRESENCE:
        zone = p.get("zone")
        return ("home", str(zone)) if zone else None
    if event.topic == _ACTUATOR:
        actuator = p.get("actuator")
        if not actuator:
            return None
        # 'light.living_room' → ('light', 'living_room'); the room is the OFF-fenceable token
        domain, _, rest = str(actuator).partition(".")
        return (domain, rest) if rest else (domain,)
    if event.topic == _MEDIA:
        # The media council's rule: learn the SHAPE of his media life (app + coarse kind), so
        # "weekend evenings → a film" falls out — but NEVER the title. A title is sensitive like
        # a self-photo (Charter 23a); it lives live-only/pin-to-keep elsewhere, never in the
        # durable GIST. We read ONLY app/kind here, so a title can't leak into the record.
        app = p.get("app")
        if not app:
            return None
        toks = ["media", str(app)]
        kind = p.get("kind")
        if kind in ("film", "series"):
            toks.append(str(kind))
        return tuple(toks)
    return None


class GistStore:
    """The distilled memory on disk — one `.ddn` of byte-exact schema state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> list[Schema]:
        try:
            return decode_state(self.path.read_bytes())
        except FileNotFoundError:
            return []
        except Exception:                       # corrupt → honest-empty, never a crash
            log.warning("gist: %s unreadable; starting from empty memory", self.path)
            return []

    def save(self, schemas: list[Schema]) -> None:
        data = encode_state(schemas)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)              # atomic: a crash leaves old or new, never torn


class GistCollector:
    """Buffer the day's GIST-worthy events; fold them into the store once a night."""

    def __init__(self, bus, store: GistStore, *, tz: str | None = None,
                 off_zones=frozenset()) -> None:
        self.bus = bus
        self.store = store
        self._tz = ZoneInfo(tz) if tz else None
        self.off_zones = frozenset(off_zones)
        self._day: list[tuple[int, tuple[str, ...]]] = []   # (minute, tokens) for the current day
        self._saw_presence = False
        self._subs: list = []
        self.last_summary = None    # FoldSummary of the most recent fold (what changed last night)

    async def start(self) -> None:
        topics = list(_PRESENCE) + [_ACTUATOR]
        self._subs = [self.bus.subscribe(t, self._on_event, owner="gist") for t in topics]

    async def stop(self) -> None:
        for s in self._subs:
            self.bus.unsubscribe(s)
        self._subs = []

    async def _on_event(self, event: Event) -> None:
        toks = event_tokens(event)
        if toks is None:
            return
        if event.topic in _PRESENCE:
            self._saw_presence = True
        dt = datetime.fromtimestamp(event.ts, self._tz) if self._tz else datetime.fromtimestamp(event.ts)
        self._day.append((dt.hour * 60 + dt.minute, toks))

    def fold(self, now: float) -> int:
        """Fold the buffered day into the persisted state and clear the buffer. Returns the
        number of observations folded. Called from the nightly ritual (before log rotation)."""
        from core.gist import DayObs, summarize_fold
        if not self._day:
            self.last_summary = None
            return 0
        dt = datetime.fromtimestamp(now, self._tz) if self._tz else datetime.fromtimestamp(now)
        daytype = daytype_of(dt.date().isoformat(), away=not self._saw_presence)
        obs = [DayObs(minute=m, tokens=t) for m, t in self._day]
        prior = self.store.load()
        new_state = fold_day(prior, obs, daytype=daytype, off_zones=self.off_zones)
        self.store.save(new_state)
        # Capture the night-over-night delta BEFORE clearing the buffer; the save above is the
        # commit point (it raises on failure, so the buffer is kept and nothing is lost).
        self.last_summary = summarize_fold(prior, new_state)
        n = len(obs)
        self._day = []
        self._saw_presence = False
        return n
