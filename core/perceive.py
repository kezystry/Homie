"""Perceive — intake of structured events from the perception node.

Raw thermal/radar/camera inference runs at the edge (see perception/). This
module receives normalized events over the mesh and publishes them to the bus.

The perception adapter is the one place raw imagery exists, so it carries a
fail-closed guard at the source: `assert_emittable` rejects any event whose
topic/payload is not declared emittable by the positive schema (`core/schema.py`)
*before* it reaches the bus — mirroring the mesh `PrivacyGuard`, but one layer
earlier so a leak is impossible by construction rather than caught in transit.
Both guards call the same `core.schema.validate`, so the two can never drift apart.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import AsyncIterator, Protocol

from core.schema import MAX_PAYLOAD_BYTES, validate
from core.tile import Event

log = logging.getLogger("homie.perceive")

# The positive-schema privacy guard (core/schema.py) is the single source of truth for what
# perception may emit, shared byte-for-byte with the mesh PrivacyGuard. We no longer carry a
# denylist here: a payload is emittable only if its topic is declared and every leaf matches
# its declared scalar type — so a faceprint/embedding/frame is refused structurally, at any
# depth, regardless of key name, rather than caught by a finite list of forbidden words.


class PrivacyViolation(ValueError):
    """Raised when the perception adapter tries to emit a non-emittable event."""


def assert_emittable(topic: str, payload: dict) -> None:
    """Fail closed at the source. Raise PrivacyViolation unless `topic`/`payload` are declared
    emittable by the positive schema. The adapter calls this before every emit; raising (not
    returning False) makes a slip a hard stop on that one event, never a silent leak."""
    errors = validate(topic, payload)
    if errors:
        raise PrivacyViolation(f"perception event on {topic!r} refused: {'; '.join(errors)}")


class PerceptionSource(Protocol):
    """A stream of already-normalized perception events. The live mesh/device adapter
    and the `SyntheticPerception` harness implement the SAME interface, so `Perceive.run`
    is the one intake path both flow through — the harness is not a test-only fork."""

    def events(self) -> AsyncIterator[Event]: ...


class Perceive:
    """The perception intake loop: pull normalized events from an injected source and
    publish them onto the bus, fail-closed-guarded by `assert_emittable` at the source
    (one layer before the mesh). A forbidden event is dropped + logged loudly, never
    published and never allowed to kill intake. Injected into the daemon as the
    perception seam (`build_daemon(home, Perceive(source), ...)`)."""

    def __init__(self, source: PerceptionSource) -> None:
        self.source = source

    async def run(self, bus) -> None:
        async for event in self.source.events():
            try:
                assert_emittable(event.topic, event.payload)
            except PrivacyViolation:
                log.error("perceive: dropped non-emittable event on %r (privacy guard)", event.topic)
                continue
            await bus.publish(replace(event, source=event.source or "perception"))
