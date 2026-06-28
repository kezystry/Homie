"""Route — the honest offline errand-sequencer.

The owner wanted "the easiest route." The honest truth, stated in the copy, is that with no
map data Homie cannot compute a *route* — but it CAN compute a sensible *order*: anchor the
fixed appointments in time, then slot the flexible errands into the gaps along the owner's
habitual loop from home. That is what this module does, stdlib-only, pure (fed `now`, no
I/O, no clock), so it is deterministic and unit-testable like `core/journal.py`.

Two hard honesty rules, both from the brainstorm audit:
  * It says "easiest loop / sensible order", NEVER "fastest route", and never quotes a drive
    time it did not measure. Overclaiming a route we can't compute is the exact dishonesty
    the audit warns against.
  * A FIXED appointment is never silently reordered or crammed. If two fixed windows collide,
    it FLAGS the conflict in plain words — a dropped fixed item is a reliability failure, and
    reliability is the #1 trust earner.

The spatial model is ONE owner-authored map: `deploy/zones.toml` (place/zone -> ordinal along
the habitual loop from home). No coordinates, no geocoding, no traffic. The cost function is
an injected seam: the offline default is `zone_cost` (ordinal distance); when the owner later
approves a live lookup, the SAME sequencer takes a `map_cost` through the consent gate —
map routing is a one-function upgrade, never a rewrite and never default-on.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.agenda import AT, ROUTINE, AgendaItem

log = logging.getLogger("homie.route")

ROOT = Path(__file__).resolve().parents[1]
HOME = "home"  # the origin and assumed return point of every loop
DEFAULT_AT_SECONDS = 3600.0  # assumed length of a timed item that carries no explicit end (1h)


@dataclass(frozen=True)
class RoutePlan:
    """The sequencer's output: the ordered stops and one honest clause, plus any conflicts.
    `clause` is None when there is nothing worth sequencing (< 2 place-anchored items)."""

    stops: tuple[AgendaItem, ...]
    clause: str | None
    conflicts: tuple[str, ...] = ()


def load_zones(path: Path | None = None) -> dict[str, int]:
    """Load the owner-authored place/zone -> ordinal map. Missing/odd file -> {} (the
    sequencer then falls back to pure time order, which is honest, not broken)."""
    p = path or (ROOT / "deploy" / "zones.toml")
    if not p.exists():
        return {}
    try:
        import tomllib
        data = tomllib.loads(p.read_text("utf-8"))
        zones = data.get("zones", data)
        return {str(k): int(v) for k, v in zones.items() if isinstance(v, (int, float))}
    except Exception:
        log.warning("route: could not read %s; falling back to time order", p)
        return {}


def zone_cost(zones: dict[str, int]) -> Callable[[AgendaItem | None, AgendaItem | None], float]:
    """The offline cost seam: distance = |ordinal(a.zone) - ordinal(b.zone)| along the loop.
    Home is ordinal 0; an unknown zone costs 0 (neutral) so it never fakes proximity."""
    def ordinal(it: AgendaItem | None) -> int:
        if it is None or it.place is None or it.place.zone is None:
            return 0
        return zones.get(it.place.zone, 0)
    return lambda a, b: float(abs(ordinal(a) - ordinal(b)))


def _placed(items: list[AgendaItem]) -> list[AgendaItem]:
    # Only places you actually GO are errands. A learned ROUTINE has a zone but is render-only
    # (you don't "travel" to your own kitchen habit), so it never becomes a route stop.
    return [it for it in items if it.place is not None and it.kind != ROUTINE]


def _clock(ts: float, tz=None) -> str:
    dt = datetime.fromtimestamp(ts, tz) if tz else datetime.fromtimestamp(ts)
    h, m = dt.hour, dt.minute
    suffix = "am" if h < 12 else "pm"
    hr = h % 12 or 12
    return f"{hr}:{m:02d}{suffix}" if m else f"{hr}{suffix}"


def sequence(items: list[AgendaItem], now: float, *,
             cost: Callable[[AgendaItem | None, AgendaItem | None], float] | None = None,
             tz=None) -> RoutePlan:
    """Order today's place-anchored errands sensibly. Fixed (timed AT) stops are the immovable
    spine in time order; flexible (untimed) errands are inserted greedily where they add the
    least travel along the loop. Returns None-clause when there is nothing to sequence."""
    placed = _placed(items)
    if len(placed) < 2:
        return RoutePlan(stops=(), clause=None)
    cost = cost or zone_cost({})

    fixed = sorted((it for it in placed if it.when.kind == AT and it.when.start is not None),
                   key=lambda it: it.when.start)
    flexible = [it for it in placed if not (it.when.kind == AT and it.when.start is not None)]

    conflicts = []
    for a, b in zip(fixed, fixed[1:]):
        # A timed item with no explicit end isn't zero-length — assume a sensible default window
        # so a 14:00 (no-end) appointment is still seen to collide with a 14:30 one.
        a_end = a.when.end if a.when.end is not None else a.when.start + DEFAULT_AT_SECONDS
        if b.when.start < a_end:
            conflicts.append(f"{a.title} and {b.title} overlap — can't do both")

    # The fixed spine is immovable. Greedily insert each flexible errand at the cheapest gap
    # (cheapest-insertion heuristic), with HOME bracketing the loop as origin and return.
    seq: list[AgendaItem] = list(fixed)
    for err in flexible:
        best_pos, best_delta = 0, None
        for pos in range(len(seq) + 1):
            prev = seq[pos - 1] if pos > 0 else None
            nxt = seq[pos] if pos < len(seq) else None
            # added travel = cost(prev,err)+cost(err,nxt)-cost(prev,nxt), home for the ends
            delta = cost(prev, err) + cost(err, nxt) - cost(prev, nxt)
            if best_delta is None or delta < best_delta:
                best_delta, best_pos = delta, pos
        seq.insert(best_pos, err)

    # Display uses the recognizable TITLE; the place/zone only drove the ordering above.
    parts = []
    for it in seq:
        if it.when.kind == AT and it.when.start is not None:
            parts.append(f"{_clock(it.when.start, tz)} {it.title}")
        else:
            parts.append(it.title)
    clause = "Out today: " + " → ".join(parts)
    return RoutePlan(stops=tuple(seq), clause=clause, conflicts=tuple(conflicts))
