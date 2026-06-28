"""The camera foundation — registry, the positive zone-allowlist, and the edge contract.

Proves the properties the owner's "camera is everything" priority rests on:
  * a camera is plug-in-any-time: one stanza in, a validated Camera out (or a loud failure),
  * detections cross to the bus ONLY for explicitly allowed (camera, zone, label) triples,
  * raw imagery dies at the edge — a Frigate event fat with a snapshot yields a 3-field event
    that passes the same privacy guard every perception event does,
  * the generated live/NVR configs carry that same allowlist (defense in depth).

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest

from core.camera import Camera, CameraConfigError, CameraRegistry, to_yaml
from core.perceive import assert_emittable
from perception.frigate_adapter import PRESENCE, FrigateAdapter


def reg(**stanzas) -> CameraRegistry:
    return CameraRegistry.from_stanzas(stanzas)


class RegistryValidationTests(unittest.TestCase):
    def test_a_stanza_becomes_a_camera(self) -> None:
        r = reg(front={"source": "rtsp://x", "zones": ["porch"], "detect": ["person"]})
        cam = r.get("front")
        self.assertEqual(cam.id, "front")
        self.assertEqual(cam.zones, frozenset({"porch"}))
        self.assertTrue(cam.record)            # default

    def test_missing_source_is_refused(self) -> None:
        with self.assertRaises(CameraConfigError):
            reg(bad={"zones": ["porch"]})

    def test_unknown_detect_label_is_refused(self) -> None:
        with self.assertRaises(CameraConfigError):
            reg(bad={"source": "rtsp://x", "detect": ["dragon"]})

    def test_off_property_camera_cannot_identify(self) -> None:
        # The privacy red line is structural: identify is forced off when not on_property.
        r = reg(street={"source": "rtsp://x", "on_property": False, "identify": True})
        self.assertFalse(r.get("street").identify)

    def test_on_property_camera_may_identify(self) -> None:
        r = reg(porch={"source": "rtsp://x", "on_property": True, "identify": True})
        self.assertTrue(r.get("porch").identify)

    def test_empty_registry_is_valid(self) -> None:
        self.assertEqual(reg().cameras, ())


class AllowlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.r = reg(
            door={"source": "rtsp://a", "zones": ["porch", "path"], "detect": ["person", "package"]},
            drive={"source": "rtsp://b", "zones": ["driveway"], "detect": ["car"]},
            garden={"source": "rtsp://c", "zones": [], "detect": ["person"]},  # live-only
        )

    def test_allowed_triple(self) -> None:
        self.assertTrue(self.r.allowed("door", "porch", "person"))
        self.assertTrue(self.r.allowed("door", "path", "package"))

    def test_zone_not_on_allowlist_is_denied(self) -> None:
        self.assertFalse(self.r.allowed("door", "street", "person"))

    def test_label_not_tracked_is_denied(self) -> None:
        self.assertFalse(self.r.allowed("drive", "driveway", "person"))  # only 'car' here

    def test_unknown_camera_fails_closed(self) -> None:
        self.assertFalse(self.r.allowed("nope", "porch", "person"))

    def test_live_only_camera_emits_nothing(self) -> None:
        # empty zones = watchable but silent; no triple can ever be allowed
        self.assertFalse(self.r.allowed("garden", "lawn", "person"))


# --------------------------------------------------------------------------- #
# The edge adapter: detections in, clean allowlisted events out, frames dead
# --------------------------------------------------------------------------- #
class _FakeStream:
    def __init__(self, items): self.items = items
    async def detections(self):
        for it in self.items:
            yield it


def _drain(adapter) -> list:
    async def go():
        return [e async for e in adapter.events()]
    return asyncio.run(go())


def _frigate_event(camera, label, entered, *, oid="o1", fat=True):
    after = {"camera": camera, "label": label, "entered_zones": entered,
             "id": oid, "frame_time": 100.0}
    if fat:  # the stuff that must NEVER leave the edge
        after.update(snapshot={"frame": "<<jpeg bytes>>"}, box=[0, 0, 10, 10],
                     embedding=[0.1] * 128, region=[1, 2, 3, 4])
    return {"type": "update", "after": after}


class EdgeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.r = reg(door={"source": "rtsp://a", "zones": ["porch"], "detect": ["person"]})

    def test_allowed_detection_becomes_a_clean_event(self) -> None:
        out = _drain(FrigateAdapter(_FakeStream([_frigate_event("door", "person", ["porch"])]), self.r))
        self.assertEqual(len(out), 1)
        e = out[0]
        self.assertEqual(e.topic, PRESENCE)
        self.assertEqual(e.payload, {"camera": "door", "zone": "porch", "label": "person"})
        self.assertEqual(e.ts, 100.0)

    def test_emitted_event_passes_the_privacy_guard(self) -> None:
        # the fat Frigate event had a snapshot/box/embedding; none of it survives
        out = _drain(FrigateAdapter(_FakeStream([_frigate_event("door", "person", ["porch"])]), self.r))
        for e in out:
            assert_emittable(e.topic, e.payload)   # raises if anything forbidden leaked
            self.assertNotIn("snapshot", e.payload)
            self.assertNotIn("box", e.payload)
            self.assertNotIn("embedding", e.payload)

    def test_disallowed_zone_dies_at_the_edge(self) -> None:
        out = _drain(FrigateAdapter(_FakeStream([_frigate_event("door", "person", ["street"])]), self.r))
        self.assertEqual(out, [])

    def test_disallowed_label_dies_at_the_edge(self) -> None:
        out = _drain(FrigateAdapter(_FakeStream([_frigate_event("door", "car", ["porch"])]), self.r))
        self.assertEqual(out, [])

    def test_unknown_camera_dies_at_the_edge(self) -> None:
        out = _drain(FrigateAdapter(_FakeStream([_frigate_event("ghost", "person", ["porch"])]), self.r))
        self.assertEqual(out, [])

    def test_repeated_updates_announce_a_zone_entry_once(self) -> None:
        same = [_frigate_event("door", "person", ["porch"], oid="o7") for _ in range(5)]
        out = _drain(FrigateAdapter(_FakeStream(same), self.r))
        self.assertEqual(len(out), 1)              # edge-triggered, not per-frame

    def test_distinct_objects_each_announced(self) -> None:
        evs = [_frigate_event("door", "person", ["porch"], oid="a"),
               _frigate_event("door", "person", ["porch"], oid="b")]
        out = _drain(FrigateAdapter(_FakeStream(evs), self.r))
        self.assertEqual(len(out), 2)

    def test_no_zone_in_event_emits_nothing(self) -> None:
        out = _drain(FrigateAdapter(_FakeStream([_frigate_event("door", "person", [])]), self.r))
        self.assertEqual(out, [])


# --------------------------------------------------------------------------- #
# Config generation: the same allowlist drives the live + NVR services
# --------------------------------------------------------------------------- #
class ConfigGenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.r = reg(
            door={"source": "rtsp://a:${PW}@h/s", "zones": ["porch"], "detect": ["person", "package"]},
            garden={"source": "rtsp://b", "zones": [], "record": False},
        )

    def test_go2rtc_publishes_every_camera_by_source(self) -> None:
        cfg = self.r.go2rtc_config()
        self.assertEqual(cfg["streams"]["door"], ["rtsp://a:${PW}@h/s"])
        self.assertIn("garden", cfg["streams"])    # live view even with no detection zones

    def test_frigate_only_lists_allowlisted_zones(self) -> None:
        cfg = self.r.frigate_config()
        self.assertEqual(set(cfg["cameras"]["door"]["zones"]), {"porch"})
        self.assertEqual(cfg["cameras"]["door"]["objects"]["track"], ["package", "person"])
        self.assertTrue(cfg["cameras"]["door"]["detect"]["enabled"])
        # a no-zone camera detects nothing and (here) records nothing
        self.assertFalse(cfg["cameras"]["garden"]["detect"]["enabled"])
        self.assertFalse(cfg["cameras"]["garden"]["record"]["enabled"])

    def test_frigate_uses_the_hailo_detector(self) -> None:
        self.assertEqual(self.r.frigate_config()["detectors"]["hailo"]["type"], "hailo8l")

    def test_yaml_emit_is_deterministic_and_quotes_secrets(self) -> None:
        y = to_yaml(self.r.go2rtc_config())
        self.assertEqual(y, to_yaml(self.r.go2rtc_config()))   # stable
        self.assertIn('"rtsp://a:${PW}@h/s"', y)               # ${} url is quoted, not mangled

    def test_yaml_handles_nested_and_empty(self) -> None:
        y = to_yaml({"a": {"b": [1, 2]}, "empty": {}, "flag": True})
        self.assertIn("a:", y)
        self.assertIn("- 1", y)
        self.assertIn("flag: true", y)


if __name__ == "__main__":
    unittest.main()
