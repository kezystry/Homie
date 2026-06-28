"""Briefing — the forward morning render over the one Agenda.

The recap looks back; this looks forward: what's on today, in the order of waking. It is a
FROZEN-SHAPE render with hard integer caps and lossy overflow — exactly the SpeechBudget
§4.1 discipline — so it is a tight glance, never the wall-of-text the owner named as his
single worst outcome. Pure (fed `now`, no bus/clock/IO), like `core/journal.py`.

The fixed top-to-bottom order is the lived arc of the morning:
  0. RECAP    — one past-tense line of yesterday (composed by the caller; optional).
  1. TIMELINE — today's time-anchored events, chronological, MAX 3. Weather is WOVEN here as
                one clause ("9:00 dentist · rain from 11"), never its own headline.
  2. DUE      — deadline items with no fixed clock, soonest-first, MAX 2.
  3. ROUTE    — the offline sequencer's ONE honest "Out today" clause (only if 2+ places).

Honest-empty at every level: a slot with nothing in it is omitted, not padded; a truly empty
day renders "Quiet day — nothing on." On a non-work, nothing-due morning the `speak_line` is
None (the vision's gentle silent ready-state) — the screen still renders the honest line if
opened, but Homie says nothing. When it DOES speak, it is ONE budgeted proactive line through
the shipped VoiceGate: timeline-head + the single most-urgent due + the route verb. Nothing
else is ever spoken; the rest is screen/notification-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.agenda import AT, ALLDAY, DUE, FLOAT, ROUTINE, AgendaView
from core.route import RoutePlan, sequence, zone_cost

TIMELINE_MAX = 3   # the spine: at most three timed things, then a lossy "(+N more)"
DUE_MAX = 2        # at most two deadlines on the page; the rest collapse to a count
DEFAULT_DUE_HORIZON_S = 86400.0  # "due today or tomorrow" — one bill never surprises you


def _clock(ts: float, tz=None) -> str:
    dt = datetime.fromtimestamp(ts, tz) if tz else datetime.fromtimestamp(ts)
    h, m = dt.hour, dt.minute
    suffix = "am" if h < 12 else "pm"
    hr = h % 12 or 12
    return f"{hr}:{m:02d}{suffix}" if m else f"{hr}{suffix}"


@dataclass(frozen=True)
class Briefing:
    """The rendered morning surface — frozen shape, caps already applied."""

    recap_line: str | None
    timeline: tuple[str, ...]          # <= TIMELINE_MAX lines
    timeline_overflow: int
    weather: str | None
    due: tuple[str, ...]               # <= DUE_MAX lines
    due_overflow: int
    route_clause: str | None
    conflicts: tuple[str, ...]
    is_quiet: bool                     # nothing on the timeline and nothing due
    work_day: bool                     # there is something time-anchored or due today

    def render_lines(self) -> list[str]:
        L: list[str] = []
        if self.recap_line:
            L.append(self.recap_line)
        if self.is_quiet:
            L.append("Quiet day — nothing on.")
            return L
        head = "Today" + (f" · {self.weather}" if self.weather else "") + ":"
        L.append(head)
        for t in self.timeline:
            L.append(f"  {t}")
        if self.timeline_overflow:
            L.append(f"  (+{self.timeline_overflow} more)")
        for d in self.due:
            L.append(f"  {d}")
        if self.due_overflow:
            L.append(f"  (+{self.due_overflow} due)")
        if self.route_clause:
            L.append(f"  {self.route_clause}")
        for c in self.conflicts:
            L.append(f"  ⚠ {c}")
        return L

    def render_text(self) -> str:
        return "\n".join(self.render_lines())

    def speak_line(self) -> str | None:
        """The SINGLE budgeted proactive line, or None to stay silent. Carries only the next
        timed thing + the most-urgent due + the route verb — never the whole page."""
        if self.is_quiet or not self.work_day:
            return None
        bits = []
        if self.timeline:
            bits.append(self.timeline[0])
        if self.due:
            bits.append(self.due[0])
        if self.route_clause:
            bits.append("errands out")          # a short verb; the full order stays on screen
        return "Today — " + "; ".join(bits) if bits else None


# When redacting (the spoken/pushed surface), a 'sensitive' item shows this instead of its title.
# The full title still renders on the LOCAL screen (build called with redact=False there).
PRIVATE_LABEL = "a private appointment"


def _title(it, redact: bool) -> str:
    return PRIVATE_LABEL if (redact and getattr(it, "reveal", "household") == "sensitive") else it.title


def _timeline_label(it, tz, redact: bool = False) -> str:
    title = _title(it, redact)
    if it.when.kind == ALLDAY:
        return f"{title} (all day)"
    if it.when.kind == AT and it.when.start is not None:
        return f"{_clock(it.when.start, tz)} {title}"
    return title


def _due_label(it, now: float, tz, redact: bool = False) -> str:
    title = _title(it, redact)
    when = it.when.start
    if when is None:
        return f"{title} — to do"
    if when <= now:
        return f"{title} — overdue"
    same_day = datetime.fromtimestamp(when, tz).date() == datetime.fromtimestamp(now, tz).date() if tz \
        else datetime.fromtimestamp(when).date() == datetime.fromtimestamp(now).date()
    return f"{title} — due today" if same_day else f"{title} — due {_clock(when, tz)}"


def build(view: AgendaView, now: float, *, weather: str | None = None,
          zones: dict | None = None, tz=None, recap_line: str | None = None,
          due_horizon_s: float = DEFAULT_DUE_HORIZON_S, redact: bool = False) -> Briefing:
    """Fold today's slice of the Agenda into the capped morning shape. Pure: same inputs →
    same Briefing, so the speak/screen/push surfaces all agree and a test pins every cap."""
    today = view.today(now)
    # Timeline: time-anchored events, chronological. DUE items go to the due lane, not the
    # timeline, so a deadline never masquerades as an appointment. Hard FACTS (real events)
    # claim the cap first; learned ROUTINES only fill remaining space — a guess never pushes a
    # real appointment off the page.
    timed = [it for it in today if it.when.kind in (AT, ALLDAY) and it.kind != DUE]
    facts = [it for it in timed if it.kind != ROUTINE]
    routines = [it for it in timed if it.kind == ROUTINE]
    chosen = facts[:TIMELINE_MAX]
    if len(chosen) < TIMELINE_MAX:
        chosen = chosen + routines[:TIMELINE_MAX - len(chosen)]
    chosen.sort(key=lambda it: it.sort_key(now))           # display chronologically
    timeline = [_timeline_label(it, tz, redact) for it in chosen]
    timeline_overflow = max(0, len(timed) - len(chosen))

    # The due lane: deadlined items within the horizon first, then undated FLOAT to-dos
    # ("anytime today"). An undated task must not vanish just because it has no clock.
    deadlined = view.due(now, due_horizon_s)
    undated = [it for it in today if it.when.kind == FLOAT and it.kind == DUE]
    due_items = deadlined + undated
    due = [_due_label(it, now, tz, redact) for it in due_items[:DUE_MAX]]
    due_overflow = max(0, len(due_items) - DUE_MAX)

    plan: RoutePlan = sequence(today, now, cost=zone_cost(zones or {}), tz=tz)

    is_quiet = not timed and not due_items
    work_day = bool(timed) or bool(due_items)
    return Briefing(
        recap_line=recap_line, timeline=tuple(timeline), timeline_overflow=timeline_overflow,
        weather=weather, due=tuple(due), due_overflow=due_overflow,
        route_clause=plan.clause, conflicts=plan.conflicts,
        is_quiet=is_quiet, work_day=work_day)
