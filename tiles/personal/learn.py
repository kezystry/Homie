"""Personal Assistant — self-learning.

Friction is the signal: if offering the agenda gets reversed or remarked on,
stop offering it unprompted. The system needs you less over time.
"""
from __future__ import annotations


async def learn(state, friction) -> None:
    if friction.kind in ("reversal", "remark"):
        await state.put("suppress_agenda", True)
