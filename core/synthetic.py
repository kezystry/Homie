"""SyntheticPerception — a deterministic perception source for the whole graph.

Replays a scripted trace of already-normalized events as a `PerceptionSource`, so
the entire daemon — tiles, friction, Reason — can be exercised end to end with no
camera, Pi, or GPU. It is the SAME intake seam the live adapter uses (inject it as
the source of `core.perceive.Perceive`), not a test-only fork: that is what keeps
"the graph the harness drives" identical to "the graph production drives".

`speed = 0.0` (default) yields every event as fast as possible with no sleeps, so a
replay is deterministic and bit-identical run to run. `speed > 0` paces events by
their inter-arrival gaps scaled to wall-clock seconds, for a believable live demo
(idea #1 in the master plan: `HOMIE_FAKE_PERCEPTION` boots the real daemon against a
synthetic day).
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterable

from core.tile import Event


class SyntheticPerception:
    """A `PerceptionSource` that replays a fixed list of Events."""

    def __init__(self, trace: Iterable[Event], *, speed: float = 0.0) -> None:
        self._trace = list(trace)
        self._speed = max(0.0, speed)

    async def events(self) -> AsyncIterator[Event]:
        prev_ts: float | None = None
        for event in self._trace:
            if self._speed > 0.0 and prev_ts is not None:
                await asyncio.sleep(max(0.0, (event.ts - prev_ts) * self._speed))
            prev_ts = event.ts
            yield event
