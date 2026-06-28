"""Recap — yesterday, in one honest plain-language line.

The backward half of the morning surface (the forward half is `core/briefing.py`). Given a
small bag of facts about yesterday, it renders a single past-tense line — "Tuesday. Out 9–6.
Lit the kitchen at dusk; you corrected the hallway. Stayed quiet — 4 held." Pure (no bus, no
clock, no I/O), capped, and honest-empty: with nothing to say it renders just the weekday, or
"a quiet one", never an invented event.

Caps mirror the briefing/§4.1 discipline: at most ONE thing Homie did and ONE correction
reach the line; the rest collapse to a count. A recap is a glance at yesterday, not a log.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecapFacts:
    """What is known about yesterday. Every field is optional — the composer renders only
    what is present, so a thin day produces a short honest line, not padding."""

    weekday: str                       # "Tuesday" (the only always-present fact)
    presence: str | None = None        # "out 9–6" / "home most of the day" / "a quiet day in"
    did: tuple[str, ...] = ()          # things Homie did ("lit the kitchen at dusk")
    corrected: tuple[str, ...] = ()    # corrections the owner made ("the hallway light")
    quiet_held: int = 0                # proactive lines deferred (the SpeechLedger relief count)


def compose(f: RecapFacts) -> str:
    """One plain past-tense line. Caps: one `did`, one `corrected`, the rest a count."""
    parts: list[str] = [f"{f.weekday}."]
    if f.presence:
        parts.append(_cap(f.presence) + ".")

    actions: list[str] = []
    if f.did:
        extra = len(f.did) - 1
        actions.append(f.did[0] + (f" (+{extra} more)" if extra > 0 else ""))
    if f.corrected:
        extra = len(f.corrected) - 1
        actions.append(f"you corrected {f.corrected[0]}" + (f" (+{extra} more)" if extra > 0 else ""))
    if actions:
        parts.append(_cap("; ".join(actions)) + ".")

    if f.quiet_held > 0:
        parts.append(f"Stayed quiet — {f.quiet_held} held.")
    elif not f.presence and not actions:
        parts.append("A quiet one.")            # honest-empty: nothing to report

    return " ".join(parts)


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s
