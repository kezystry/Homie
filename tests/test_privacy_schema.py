"""The positive-schema privacy guard (M7) — the named acceptance test plus the unit suite.

The Charter Law 6 promise — "raw faces/audio and identity vectors never cross a wire" — is now
positive: a payload is emittable only if every key is declared and every leaf matches its
declared scalar type. The load-bearing property is `test_features_and_nested_faceprint_rejected`:
a float vector is refused at ANY nesting depth, under ANY key name, while a declared in-spec
event passes — because the vector has no declared home, not because a token matched a denylist.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest

from core import schema
from core.schema import (
    SCHEMA, SCHEMA_FINGERPRINT, is_emittable, schema_fingerprint, validate,
)


class AcceptanceTests(unittest.TestCase):
    def test_features_and_nested_faceprint_rejected(self) -> None:
        # A declared, in-spec event passes.
        self.assertTrue(is_emittable("presence.detected",
                                     {"camera": "front", "zone": "porch", "label": "owner"}))

        # A float feature vector is refused at every depth and under every key name —
        # structurally (no field declares a list), never by a name-denylist.
        faceprint = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        rejected = [
            ("presence.detected", {"camera": "front", "zone": "porch", "label": faceprint}),  # leaf
            ("presence.detected", {"camera": "front", "zone": "porch", "features": faceprint}),  # undeclared key
            ("presence.detected", {"camera": "front", "zone": "porch", "data": {"vector": faceprint}}),  # nested
            ("presence.detected", {"camera": "front", "zone": "porch", "meta": [[0.1, 0.2], [0.3, 0.4]]}),  # nested lists
            ("presence.arrived", {"zone": "porch", "embedding": faceprint}),
        ]
        for topic, payload in rejected:
            with self.subTest(payload=payload):
                self.assertFalse(is_emittable(topic, payload))
                self.assertTrue(validate(topic, payload))   # non-empty reasons

    def test_oversized_array_rejected_even_of_ints(self) -> None:
        # A quantised int8 faceprint dodges "it's floats" — the hard list cap kills it anyway.
        quantised = list(range(64))
        self.assertFalse(is_emittable("presence.detected",
                                      {"camera": "c", "zone": "z", "label": quantised}))


class UnknownTopicTests(unittest.TestCase):
    def test_undeclared_topic_is_refused_failclosed(self) -> None:
        self.assertFalse(is_emittable("camera.frame", {"zone": "porch"}))
        self.assertFalse(is_emittable("face.faceprint.ready", {"zone": "porch"}))
        self.assertTrue(validate("totally.new.topic", {"x": 1}))   # reasons given, not silent


class LeafTypeTests(unittest.TestCase):
    def test_declared_scalars_pass_and_wrong_types_fail(self) -> None:
        self.assertTrue(is_emittable("occupancy.changed", {"zone": "kitchen", "occupied": True}))
        self.assertFalse(is_emittable("occupancy.changed", {"zone": "kitchen", "occupied": "yes"}))  # str, not bool
        self.assertFalse(is_emittable("motion.detected", {"zone": "hall", "seq": 1.5}))  # float, not int

    def test_bool_never_satisfies_a_numeric_field(self) -> None:
        # bool is a subclass of int — a True must not pass as an INT/NUM reading.
        self.assertFalse(is_emittable("motion.detected", {"zone": "h", "seq": True}))
        self.assertTrue(is_emittable("security.alert",
                                     {"reason": "r", "topic": "presence.unknown", "zone": "z",
                                      "novel": True, "rate": 0.05}))   # rate NUM, novel BOOL

    def test_none_is_always_acceptable_for_a_declared_field(self) -> None:
        # security.alert's zone can be None (event.payload.get("zone")); None is never a vector.
        self.assertTrue(is_emittable("security.alert",
                                     {"reason": "r", "topic": "t", "zone": None,
                                      "novel": False, "rate": 0.0}))

    def test_declared_key_may_be_absent(self) -> None:
        self.assertTrue(is_emittable("presence.arrived", {"zone": "kitchen"}))   # camera/label optional
        self.assertTrue(is_emittable("presence.arrived", {}))                    # all optional


class BoundsTests(unittest.TestCase):
    def test_deeply_nested_payload_fails_closed(self) -> None:
        nested: dict = {"zone": "z"}
        cur = nested
        for _ in range(schema.MAX_DEPTH + 3):
            cur["camera"] = {}        # over-deep even though every key is "declared"-ish
            cur = cur["camera"]
        self.assertFalse(is_emittable("presence.arrived", nested))

    def test_blob_payload_rejected_by_byte_cap(self) -> None:
        self.assertFalse(is_emittable("desktop.focus.changed", {"app": "x" * (schema.MAX_PAYLOAD_BYTES + 1)}))


class WireShapeTests(unittest.TestCase):
    def test_validates_post_json_normalized_shape(self) -> None:
        # What actually crosses the mesh is JSON: tuples become lists, int keys become strings.
        # A clean scalar payload must still pass after a real round-trip (the mesh inbound path).
        payload = {"zone": "kitchen", "occupied": True}
        roundtripped = json.loads(json.dumps(payload))
        self.assertTrue(is_emittable("occupancy.changed", roundtripped))


class FingerprintTests(unittest.TestCase):
    def test_pinned_fingerprint_matches(self) -> None:
        # Law 8a tripwire: the schema cannot change without a human consciously updating the pin.
        self.assertEqual(schema_fingerprint(SCHEMA), SCHEMA_FINGERPRINT)

    def test_fingerprint_is_deterministic_and_order_independent(self) -> None:
        shuffled = {k: SCHEMA[k] for k in reversed(list(SCHEMA))}
        self.assertEqual(schema_fingerprint(shuffled), schema_fingerprint(SCHEMA))

    def test_fingerprint_changes_when_the_schema_widens(self) -> None:
        widened = dict(SCHEMA)
        widened["new.topic"] = {"x": schema.STR}
        self.assertNotEqual(schema_fingerprint(widened), SCHEMA_FINGERPRINT)


if __name__ == "__main__":
    unittest.main()
