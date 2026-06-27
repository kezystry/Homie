"""Lighting — self-learning.

A reversal or remark on a light Homie turned on teaches it to stop auto-lighting
that room at that hour. The correction's `zone`/`actor` (stamped by the runtime)
let it scope the lesson to the room and honour the privacy rule: never learn from a
guest or unrecognized person — only the household shapes the home's behaviour.
"""
from __future__ import annotations

from datetime import datetime

_EXCLUDED_ACTORS = ("guest", "unknown")  # never train on non-household people (Q39 / BACKLOG #9)


def _hour(ts: float) -> int:
    return datetime.fromtimestamp(ts).hour


def _oclock(hour: int) -> str:
    """A human "around 7pm" for the spoken lesson — friendlier than "19:00"."""
    suffix = "am" if hour < 12 else "pm"
    h12 = hour % 12 or 12
    return f"{h12}{suffix}"


async def learn(state, friction) -> str | None:
    """Fold a correction into the suppression map. Returns a ONE-LINE narration the
    runtime speaks the FIRST time a given (room, hour) lesson forms — the moment the
    home audibly admits it learned something hour-shaped about this household (M4) —
    and None for a repeat or an ignored correction (so it never narrates a tick twice)."""
    if friction.kind not in ("reversal", "remark"):
        return None
    if (friction.actor or "").lower().startswith(_EXCLUDED_ACTORS):
        return None  # a guest's correction is not a household preference

    ref = friction.reverses
    room = friction.zone
    if room is None and ref is not None and ref.actuator.startswith("light."):
        room = ref.actuator.split(".", 1)[1]
    if not room:
        return None

    when = ref.at if ref is not None else friction.at
    hour = _hour(when)
    suppressed = dict(state.get("suppressed", {}))
    hours = set(suppressed.get(room, []))
    if hour in hours:
        return None  # already learned this (room, hour) — stay quiet
    hours.add(hour)
    suppressed[room] = sorted(hours)
    await state.put("suppressed", suppressed)
    return f"Got it — I'll stop lighting the {room} around {_oclock(hour)}."
