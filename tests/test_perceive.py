"""Perception privacy-guard tests — raw imagery can never leave the edge.

`assert_emittable` is the fail-closed guard the perception adapter calls before
every emit, mirroring the mesh PrivacyGuard one layer earlier (at the source).

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.mesh import PrivacyGuard
from core.perceive import FORBIDDEN, PrivacyViolation, assert_emittable


class AssertEmittableTests(unittest.TestCase):
    def test_clean_event_passes(self) -> None:
        assert_emittable("presence.arrived", {"zone": "entry", "label": "alice"})  # no raise

    def test_forbidden_topic_segment_rejected(self) -> None:
        for topic in ("camera.frame", "face.faceprint.ready", "image.raw"):
            with self.assertRaises(PrivacyViolation):
                assert_emittable(topic, {"zone": "entry"})

    def test_forbidden_payload_key_rejected(self) -> None:
        for key in ("frame", "crop", "vector", "faceprint", "image", "raw"):
            with self.assertRaises(PrivacyViolation):
                assert_emittable("presence.unknown", {"zone": "entry", key: "..."})

    def test_blob_sized_payload_rejected(self) -> None:
        with self.assertRaises(PrivacyViolation):
            assert_emittable("presence.arrived", {"zone": "x", "blob": "A" * 5000})

    def test_shares_forbidden_set_with_mesh_guard(self) -> None:
        # single source of truth — the two guards can never drift apart
        self.assertIs(FORBIDDEN, PrivacyGuard.FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
