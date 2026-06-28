"""FrigateAdapter — the seam where a camera detection becomes a bus event, and a frame dies.

Frigate runs on the Pi, decodes the camera, and runs object detection on the Hailo-8. Its
output is a firehose of rich detection objects — each one carrying a snapshot, a crop, a
bounding box, an embedding. NONE of that may leave the edge. This adapter is the strainer:
it reads the firehose and yields only normalized `(camera, zone, label)` presence events,
gated by the camera registry's POSITIVE zone-allowlist, constructing each payload from
scratch so a frame can't ride along even by accident.

It is a `PerceptionSource` (core/perceive.py), so its output flows through the SAME
`assert_emittable` privacy guard as every other perception event — belt (this adapter only
ever names three clean fields) and braces (the guard would hard-fail any forbidden key).

Edge-triggered: an event is emitted when an object ENTERS an allowed zone, not for every
frame it lingers there — so a person standing in view produces one "entered the driveway",
not sixty per second. Dedup is keyed on `(object_id, zone)` and bounded.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Protocol

from core.camera import CameraRegistry
from core.tile import Event

log = logging.getLogger("homie.frigate")

PRESENCE = "presence.detected"   # out: a known label entered an allowed zone on a camera
_DEDUP_MAX = 4096                 # bound the seen-set so a long uptime can't grow it forever


class FrigateEventStream(Protocol):
    """The raw Frigate detection stream (MQTT `frigate/events`, or a fake in tests). Each
    item is Frigate's event dict; the adapter reads only the safe scalar fields from it."""

    def detections(self) -> AsyncIterator[dict]: ...


def _after(detection: dict) -> dict:
    """Frigate wraps state in before/after; a flat test event is its own `after`."""
    a = detection.get("after")
    return a if isinstance(a, dict) else detection


def _entered_zones(after: dict) -> list[str]:
    """The zones this object NEWLY entered. Prefer Frigate's edge-triggered `entered_zones`;
    fall back to `current_zones`, then a single `zone`, so simpler producers still work."""
    for key in ("entered_zones", "current_zones", "zones"):
        zs = after.get(key)
        if isinstance(zs, list) and zs:
            return [str(z) for z in zs]
    z = after.get("zone")
    return [str(z)] if z else []


class FrigateAdapter:
    """Wrap a Frigate event stream as a privacy-clean `PerceptionSource`.

    `registry` is the camera allowlist: only `(camera, zone, label)` triples it permits ever
    become events. Everything else — wrong zone, untracked label, unknown camera, or a frame
    of any kind — dies here, on the Pi, and never touches the bus."""

    def __init__(self, stream: FrigateEventStream, registry: CameraRegistry) -> None:
        self.stream = stream
        self.registry = registry
        self._seen: set[tuple[str, str]] = set()

    async def events(self) -> AsyncIterator[Event]:
        async for detection in self.stream.detections():
            for event in self._normalize(detection):
                yield event

    def _normalize(self, detection: dict) -> list[Event]:
        after = _after(detection)
        camera = after.get("camera")
        label = after.get("label")
        if not isinstance(camera, str) or not isinstance(label, str):
            return []
        ts = after.get("frame_time", detection.get("frame_time", 0.0))
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            ts = 0.0
        obj_id = str(after.get("id", ""))

        out: list[Event] = []
        for zone in _entered_zones(after):
            if not self.registry.allowed(camera, zone, label):
                continue                      # not on the allowlist → die at the edge
            dedup = (obj_id, zone)
            if obj_id and dedup in self._seen:
                continue                      # already announced this object entering this zone
            if obj_id:
                self._remember(dedup)
            # Built field-by-field from scalars only — no snapshot, crop, box, or embedding
            # is ever read, so none can ever leak. assert_emittable guards this downstream too.
            out.append(Event(
                PRESENCE, ts,
                {"camera": camera, "zone": zone, "label": label},
                source="perception",
            ))
        return out

    def _remember(self, key: tuple[str, str]) -> None:
        if len(self._seen) >= _DEDUP_MAX:
            self._seen.clear()                # crude bound; a re-announce after a flush is harmless
        self._seen.add(key)
