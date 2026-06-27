"""The capability registry — mint is idempotent, resolve is strict, revoke is clean.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.capability import Capability, CapabilityRegistry


class CapabilityRegistryTests(unittest.TestCase):
    def test_mint_is_idempotent_per_tile_actuator(self) -> None:
        r = CapabilityRegistry()
        h1 = r.mint("lighting", "light.kitchen", "ambient")
        h2 = r.mint("lighting", "light.kitchen", "ambient")
        self.assertEqual(h1, h2)  # same pair -> same handle, registry does not grow
        self.assertEqual(len(r._by_id), 1)

    def test_distinct_pairs_get_distinct_handles(self) -> None:
        r = CapabilityRegistry()
        a = r.mint("lighting", "light.kitchen", "ambient")
        b = r.mint("lighting", "light.living_room", "ambient")
        c = r.mint("security", "light.kitchen", "security")
        self.assertEqual(len({a, b, c}), 3)

    def test_resolve_recovers_authoritative_identity(self) -> None:
        r = CapabilityRegistry()
        h = r.mint("lighting", "light.kitchen", "ambient")
        cap = r.resolve(h)
        self.assertEqual(cap, Capability("lighting", "light.kitchen", "ambient"))

    def test_resolve_refuses_unknown_and_nonstring(self) -> None:
        r = CapabilityRegistry()
        r.mint("lighting", "light.kitchen", "ambient")
        self.assertIsNone(r.resolve("deadbeef"))
        self.assertIsNone(r.resolve(None))
        self.assertIsNone(r.resolve(12345))
        self.assertIsNone(r.resolve({"tile": "lighting"}))

    def test_handle_is_opaque_and_unguessable(self) -> None:
        h = CapabilityRegistry().mint("lighting", "light.kitchen", "ambient")
        self.assertEqual(len(h), 32)  # 16 bytes hex
        self.assertNotIn("lighting", h)
        self.assertNotIn("kitchen", h)

    def test_revoke_drops_only_that_tiles_handles(self) -> None:
        r = CapabilityRegistry()
        a = r.mint("lighting", "light.kitchen", "ambient")
        b = r.mint("security", "siren", "safety")
        r.revoke_tile("lighting")
        self.assertIsNone(r.resolve(a))
        self.assertIsNotNone(r.resolve(b))
        # re-mint after revoke yields a fresh handle (the old one stays dead)
        a2 = r.mint("lighting", "light.kitchen", "ambient")
        self.assertNotEqual(a, a2)


if __name__ == "__main__":
    unittest.main()
