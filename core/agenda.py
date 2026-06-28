"""Agenda — the one typed substrate the morning surface renders.

The owner asked for a day briefing and "the most logical, smart organizing system." The
design council's answer (and this module): ONE typed list of things that have a time, a
place, or a deadline, folded fresh from the sources Homie already has — and then TWO pure
renders over the same list, a backward RECAP and a forward BRIEFING (`core/briefing.py`).
There is NO new store: the bus durability log is the memory, read live, exactly like
`core/remember.py`. There is NO new mouth: the Agenda only ever renders, or spends ONE
budgeted line through the shipped `VoiceGate`.

The load-bearing PIM decision is the temporal anchor: an item is anchored to a time-window,
a deadline, an all-day date, or nothing — never "sort of." Three real shapes cover the whole
of calendar reality, so every render reads `when` through one `sort_key`.

This file is PURE — no bus, no clock, no I/O (it is handed `now`), mirroring
`core/journal.py` — so it renders bit-identically on the cockpit, the status page, the
recap, and a phone push, and is trivially unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from zoneinfo import ZoneInfo

# Temporal kinds — exactly one anchor per item.
AT = "at"          # time-window: start (+ optional end). Calendar events, errand stops.
BY = "by"          # deadline: the ONLY kind allowed to escalate to a proactive line.
ALLDAY = "allday"  # an all-day date with no clock. Birthdays, clockless appointments.
FLOAT = "float"    # no time at all. An undated todo, or a routine belief ("anytime").

# Item kinds — what the thing IS (drives phrasing + which adapters produce it).
EVENT, DUE, PARCEL, SHIP, ROUTINE = "event", "due", "parcel", "ship", "routine"


@dataclass(frozen=True)
class Temporal:
    """A tiny tagged union over the four temporal shapes. Construct via the classmethods,
    which validate that exactly one anchor is set for the kind."""

    kind: str
    start: float | None = None   # AT start / BY deadline / ALLDAY day-start (epoch seconds)
    end: float | None = None     # AT end only (optional)

    @classmethod
    def at(cls, start: float, end: float | None = None) -> "Temporal":
        if end is not None and end < start:
            raise ValueError("Temporal.at: end before start")
        return cls(AT, float(start), None if end is None else float(end))

    @classmethod
    def by(cls, deadline: float) -> "Temporal":
        return cls(BY, float(deadline), None)

    @classmethod
    def allday(cls, day_start: float) -> "Temporal":
        return cls(ALLDAY, float(day_start), None)

    @classmethod
    def floating(cls) -> "Temporal":
        return cls(FLOAT, None, None)

    @property
    def anchor(self) -> float | None:
        """The single epoch this item sorts by (None for FLOAT)."""
        return self.start


@dataclass(frozen=True)
class Place:
    """Where an item happens — a stable human label + a coarse OWNER-AUTHORED zone only.
    Never coordinates, never a carrier/tracking id. The zone is the entire spatial model the
    offline route-sequencer reads (see `core/route.py` + `deploy/zones.toml`)."""

    label: str
    zone: str | None = None


@dataclass(frozen=True)
class AgendaItem:
    """One typed thing on the day. JSON-safe (rides the bus as an `agenda.item` payload like
    every other Event). `confidence` is 1.0 for a hard fact (a real calendar event) and the
    belief probability for a routine, so a fact always outranks a learned guess for the same
    slot — the `journal.py` 'fact beats coincidence' rule, here at merge time."""

    kind: str               # EVENT | DUE | PARCEL | SHIP | ROUTINE
    when: Temporal
    title: str
    place: Place | None = None
    source: str = ""        # provenance ("ha:calendar.work"), mapped to plain words on render
    source_id: str = ""     # stable per-source key for identity dedup
    confidence: float = 1.0
    firm: bool = True
    reveal: str = "household"  # 'public' | 'household' | 'sensitive' — how much may cross to push

    def sort_key(self, now: float) -> tuple:
        """The one total order every render shares: overdue deadlines first, then the day's
        timeline by time, then all-day, then floating. Deterministic and float-free of bias."""
        w = self.when
        if w.kind == BY and w.start is not None and w.start <= now:
            return (0, w.start, self.title)          # overdue — most overdue first
        if w.kind in (AT, BY) and w.start is not None:
            return (1, w.start, self.title)          # upcoming, on the timeline by time
        if w.kind == ALLDAY and w.start is not None:
            return (2, w.start, self.title)
        return (3, 0.0, self.title)                  # FLOAT — anytime, sorts last


def _norm_title(t: str) -> str:
    """Casefold + strip non-alphanumerics for cross-source coalesce (display-only)."""
    return "".join(ch for ch in t.casefold() if ch.isalnum())


class AgendaView:
    """A pure view over a list of items: dedup/merge, total ordering, and the day-slices the
    two renders consume. Constructed with the items + the home's timezone (so 'today' means
    the home's calendar day, stable across hosts — same discipline as `PatternModel`)."""

    COALESCE_WINDOW_S = 3600.0  # cross-source title matches within an hour collapse for display

    def __init__(self, items: list[AgendaItem], *, tz: str | None = None) -> None:
        self._tz = ZoneInfo(tz) if tz else None
        self._items = self._merge(items)

    def _merge(self, items: list[AgendaItem]) -> list[AgendaItem]:
        """Two-level deterministic dedup (NO LLM): (1) identity on (source, source_id) so a
        re-read replaces rather than duplicates; (2) cross-source coalesce on
        (normalized-title, near-window) keeping the highest-confidence representative — but
        NEVER merging across different deadlines (coalesce collapses DISPLAY, not meaning)."""
        by_identity: dict[tuple, AgendaItem] = {}
        for it in items:
            key = (it.source, it.source_id) if it.source_id else (id(it),)
            by_identity[key] = it  # last write wins — a fresh read supersedes
        kept: list[AgendaItem] = []
        for it in by_identity.values():
            dup = None
            for i, k in enumerate(kept):
                if _norm_title(k.title) != _norm_title(it.title):
                    continue
                a, b = k.when.anchor, it.when.anchor
                same_when = (a is None and b is None) or (
                    a is not None and b is not None and abs(a - b) <= self.COALESCE_WINDOW_S)
                if same_when and not (k.when.kind == BY and it.when.kind == BY and k.when.start != it.when.start):
                    dup = i
                    break
            if dup is None:
                kept.append(it)
            elif it.confidence > kept[dup].confidence:
                kept[dup] = it  # the harder fact wins the slot; the guess is hidden
        return kept

    def _date(self, ts: float) -> str:
        return (datetime.fromtimestamp(ts, self._tz) if self._tz
                else datetime.fromtimestamp(ts)).date().isoformat()

    def all(self, now: float) -> list[AgendaItem]:
        return sorted(self._items, key=lambda it: it.sort_key(now))

    def today(self, now: float) -> list[AgendaItem]:
        """Items happening on the home's current calendar day, plus floating 'anytime' items.
        Overdue deadlines are surfaced too (they are still on you today)."""
        d = self._date(now)
        out = []
        for it in self._items:
            a = it.when.anchor
            if it.when.kind == FLOAT:
                out.append(it)
            elif a is not None and (self._date(a) == d or (it.when.kind == BY and a <= now)):
                out.append(it)
        return sorted(out, key=lambda it: it.sort_key(now))

    def yesterday(self, now: float) -> list[AgendaItem]:
        prior = self._date(now - 86400)
        out = [it for it in self._items
               if it.when.anchor is not None and self._date(it.when.anchor) == prior]
        return sorted(out, key=lambda it: it.sort_key(now))

    def due(self, now: float, horizon_s: float) -> list[AgendaItem]:
        """BY-deadline items due within `horizon_s` of now (or already overdue) — the only
        items that may escalate to a proactive line. Soonest/most-overdue first."""
        out = [it for it in self._items
               if it.when.kind == BY and it.when.start is not None and it.when.start <= now + horizon_s]
        return sorted(out, key=lambda it: it.sort_key(now))


# --------------------------------------------------------------------------- #
# Source adapters — pure mappers (record/state -> items), one per source. No source owns
# rendering; they only produce typed items. Mirrors core/ha.py's pure mappers.
# --------------------------------------------------------------------------- #
def from_beliefs(rows: list[dict], *, day_start: float) -> list[AgendaItem]:
    """Homie's own learned routines (`Remember.beliefs(now)`) as ROUTINE items. Anchored at
    today's belief-hour (AT) so they fall on the timeline; render-only, never escalate."""
    out = []
    for r in rows:
        hour = int(r.get("hour", 0))
        out.append(AgendaItem(
            kind=ROUTINE, when=Temporal.at(day_start + hour * 3600.0),
            title=_belief_title(r), source="homie:routine",
            source_id=f"{r.get('topic')}|{r.get('zone')}",
            confidence=float(r.get("prob", 0.0)), firm=bool(r.get("firm", False)),
            place=Place(r["zone"], r["zone"]) if r.get("zone") else None))
    return out


def _belief_title(r: dict) -> str:
    from core.journal import _subject  # reuse the one plain-language mapper (no topic leak)
    return _subject(r.get("topic", ""), r.get("zone")).capitalize()


def from_ha_calendar(events: list[dict]) -> list[AgendaItem]:
    """HA `calendar.*` events -> EVENT items. Each event is a dict with start/end epoch (or an
    all_day flag), a summary, an optional location, and a stable uid."""
    out = []
    for e in events:
        all_day = bool(e.get("all_day"))
        start = float(e["start"])
        when = Temporal.allday(start) if all_day else Temporal.at(start, e.get("end"))
        loc = e.get("location")
        out.append(AgendaItem(
            kind=EVENT, when=when, title=str(e.get("summary", "(event)")),
            place=Place(loc) if loc else None,
            source=f"ha:{e.get('entity', 'calendar')}", source_id=str(e.get("uid", "")),
            confidence=1.0, firm=True))
    return out


def from_ha_todo(items: list[dict]) -> list[AgendaItem]:
    """HA `todo.*` items -> DUE items (BY their due epoch) or FLOAT (undated)."""
    out = []
    for t in items:
        due = t.get("due")
        when = Temporal.by(float(due)) if due is not None else Temporal.floating()
        out.append(AgendaItem(
            kind=DUE, when=when, title=str(t.get("summary", "(task)")),
            source=f"ha:{t.get('entity', 'todo')}", source_id=str(t.get("uid", "")),
            confidence=1.0, firm=True))
    return out


def weather_clause(state: dict | None) -> str | None:
    """HA `weather.*` -> a single woven context clause, NEVER a row or a pane (so weather can
    never become a forecast wall). e.g. 'rain from 11' / 'cold, 2–7°'. None if unavailable."""
    if not state:
        return None
    rain_h = state.get("rain_onset_hour")
    if rain_h is not None:
        h = int(rain_h)
        clock = f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"
        return f"rain from {clock}"
    hi, lo = state.get("high"), state.get("low")
    if hi is not None and lo is not None:
        return f"{round(lo)}–{round(hi)}°"
    cond = state.get("condition")
    return str(cond) if cond else None
