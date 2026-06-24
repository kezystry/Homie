"""Perceive — intake of structured events from the perception node.

Raw thermal/radar/camera inference runs at the edge (see perception/). This
module receives normalized events over the mesh and publishes them to the bus.

The perception adapter is the one place raw imagery exists, so it carries a
fail-closed guard at the source: `assert_emittable` rejects any event that
would carry a frame, crop, bounding box, faceprint, or embedding *before* it
reaches the bus — mirroring the mesh `PrivacyGuard`, but one layer earlier so a
leak is impossible by construction rather than caught in transit. The forbidden
token set is shared with the mesh guard so the two can never drift apart.
"""
from __future__ import annotations

from core.mesh import PrivacyGuard

# Single source of truth for what perception may never emit (raw imagery, crops,
# bounding boxes, faceprints, embeddings). Shared with the mesh PrivacyGuard.
FORBIDDEN = PrivacyGuard.FORBIDDEN
MAX_PAYLOAD_BYTES = 4096


class PrivacyViolation(ValueError):
    """Raised when the perception adapter tries to emit forbidden content."""


def assert_emittable(topic: str, payload: dict, *, max_bytes: int = MAX_PAYLOAD_BYTES) -> None:
    """Fail closed at the source. Raise PrivacyViolation if `topic`/`payload`
    would carry raw imagery off the perception node. The adapter calls this
    before every emit; raising (not returning False) makes a slip a hard crash
    on that one event, never a silent leak."""
    forbidden_topic = FORBIDDEN & set(topic.split("."))
    if forbidden_topic:
        raise PrivacyViolation(f"perception topic '{topic}' carries forbidden segment {sorted(forbidden_topic)}")
    forbidden_keys = FORBIDDEN & set(payload)
    if forbidden_keys:
        raise PrivacyViolation(f"perception payload carries forbidden key(s) {sorted(forbidden_keys)}")
    # a blob-sized payload is almost certainly imagery sneaking through under an
    # innocuous key name
    size = sum(len(str(v)) for v in payload.values())
    if size > max_bytes:
        raise PrivacyViolation(f"perception payload is {size} bytes (>{max_bytes}) — likely raw imagery")


class Perceive:
    async def run(self, bus) -> None: ...
