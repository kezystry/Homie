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


async def learn(state, friction) -> None:
    if friction.kind not in ("reversal", "remark"):
        return
    if (friction.actor or "").lower().startswith(_EXCLUDED_ACTORS):
        return  # a guest's correction is not a household preference

    ref = friction.reverses
    room = friction.zone
    if room is None and ref is not None and ref.actuator.startswith("light."):
        room = ref.actuator.split(".", 1)[1]
    if not room:
        return

    when = ref.at if ref is not None else friction.at
    suppressed = dict(state.get("suppressed", {}))
    hours = set(suppressed.get(room, []))
    hours.add(_hour(when))
    suppressed[room] = sorted(hours)
    await state.put("suppressed", suppressed)
