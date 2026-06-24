"""Remember — Behavioral Analysis, the heart.

Builds a pattern of life from the event stream and answers "what is normal?" for
a given topic, zone, and time. It reads the same append-only log the bus writes
(bootstrap on start) and updates live by subscribing — one log, two readers.

The model is deliberately simple: per (topic, zone) it counts observations into
hour-of-day buckets and tracks how many distinct days it has seen, so an
expectation is a per-day rate. Novel keys (never observed) are flagged. Security
and Self-Learning consume this; thresholds/policy live in the caller, not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from core.bus import _compile
from core.tile import Event

HOURS = 24


@dataclass(frozen=True)
class Expectation:
    rate: float  # observed events/day in this (key, hour) bucket
    count: int  # raw observations in the bucket
    days: int  # distinct days of history for the key
    novel: bool  # the (topic, zone) was never observed before


def _zone(event: Event) -> str | None:
    return event.payload.get("zone")


class PatternModel:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, str | None], list[int]] = {}
        self._dates: dict[tuple[str, str | None], set[date]] = {}

    def observe(self, event: Event) -> None:
        key = (event.topic, _zone(event))
        when = datetime.fromtimestamp(event.ts)  # local time — patterns are local
        self._counts.setdefault(key, [0] * HOURS)[when.hour] += 1
        self._dates.setdefault(key, set()).add(when.date())

    def expectation(self, topic: str, zone: str | None, when: float) -> Expectation:
        key = (topic, zone)
        if key not in self._counts:
            return Expectation(rate=0.0, count=0, days=0, novel=True)
        hour = datetime.fromtimestamp(when).hour
        count = self._counts[key][hour]
        days = len(self._dates[key]) or 1
        return Expectation(rate=count / days, count=count, days=days, novel=False)


class Remember:
    def __init__(self) -> None:
        self.model = PatternModel()

    async def record(self, event: Event) -> None:
        self.model.observe(event)

    async def normal(self, topic: str, zone: str | None, when: float) -> Expectation:
        """What is expected for this topic/zone at this time."""
        return self.model.expectation(topic, zone, when)

    def bootstrap(self, bus) -> None:
        """Rebuild the model from the bus's durability log — the log is the memory.

        Only perception events feed the pattern of life, matching attach(), so
        internal chatter (interface/actuator/security events) in the log is ignored.
        """
        patterns = [_compile(p) for p in self.PERCEPTION]
        for event in bus.replay():
            if any(p.match(event.topic) for p in patterns):
                self.model.observe(event)

    #: perception topics the pattern of life is built from (not internal chatter)
    PERCEPTION = ("presence.**", "motion.**", "occupancy.**")

    def attach(self, bus) -> None:
        """Record perception events live, on top of the bootstrap history.

        Note the ordering contract: anomaly evaluation (Security/Reason) must judge
        an event against *prior* history. A consumer that both evaluates and learns
        from the same event must evaluate first, then commit — otherwise the event
        masks its own novelty. Remember therefore lags evaluation by design; live
        learning here is for consumers that are not evaluating the same instant.
        """
        for topic in self.PERCEPTION:
            bus.subscribe(topic, self.record, owner="core:remember")
