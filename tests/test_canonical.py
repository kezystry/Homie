"""Canonicalizer tests — a command and its differently-shaped echo must match.

This is the fix for the load-bearing echo-suppression bug: without it Homie reads
its own dimmed/colour commands as human reversals and corrupts learning.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.act import CommandLog
from core.canonical import Canon, ha_canonical


class CanonicalTests(unittest.TestCase):
    def test_structured_command_matches_ha_echo(self) -> None:
        # Homie drives 40%; HA echoes brightness as 102/255 -> same canonical form
        self.assertEqual(
            ha_canonical({"state": "on", "brightness_pct": 40}),
            ha_canonical({"state": "on", "brightness": 102}),
        )

    def test_idempotent(self) -> None:
        once = ha_canonical({"state": "on", "brightness_pct": 40})
        self.assertEqual(ha_canonical(once), once)
        self.assertIsInstance(once, Canon)

    def test_brightness_boundaries(self) -> None:
        self.assertEqual(ha_canonical({"state": "on", "brightness_pct": 0}).brightness, 0)
        self.assertEqual(ha_canonical({"state": "on", "brightness_pct": 100}).brightness, 255)
        self.assertEqual(ha_canonical({"state": "on", "brightness_pct": 40}).brightness, 102)

    def test_color_temp_kelvin_to_mired(self) -> None:
        self.assertEqual(ha_canonical({"state": "on", "color_temp_kelvin": 2700}).mired, 370)
        # HA's legacy mired attribute is accepted as-is and matches the kelvin form
        self.assertEqual(
            ha_canonical({"state": "on", "color_temp_kelvin": 2700}),
            ha_canonical({"state": "on", "color_temp": 370}),
        )

    def test_bool_str_dict_states_unify(self) -> None:
        on = {ha_canonical(True), ha_canonical("on"), ha_canonical({"state": "on"})}
        self.assertEqual(on, {Canon("on", None, None)})
        self.assertEqual(ha_canonical(False), ha_canonical("off"))
        self.assertNotEqual(ha_canonical("on"), ha_canonical("off"))

    def test_non_equivalent_do_not_match(self) -> None:
        # a plain "on" is a different intent from "on at 40%"
        self.assertNotEqual(ha_canonical("on"), ha_canonical({"state": "on", "brightness_pct": 40}))
        # 40% (102) != 41% (105)
        self.assertNotEqual(
            ha_canonical({"state": "on", "brightness_pct": 40}),
            ha_canonical({"state": "on", "brightness_pct": 41}),
        )

    def test_brightness_without_state_implies_on(self) -> None:
        self.assertEqual(ha_canonical({"brightness_pct": 50}).state, "on")

    def test_unknown_shape_is_total(self) -> None:
        self.assertEqual(ha_canonical(object()), Canon(None, None, None))  # never raises

    def test_wired_into_commandlog_suppresses_echo(self) -> None:
        # the real use: record a structured drive, match the HA-shaped echo
        log = CommandLog(canonical=ha_canonical)
        log.record("light.lr", {"state": "on", "brightness_pct": 40}, "lighting")
        self.assertIsNotNone(log.take_echo("light.lr", {"state": "on", "brightness": 102}))
        self.assertIsNone(log.take_echo("light.lr", {"state": "on", "brightness": 102}))  # popped


if __name__ == "__main__":
    unittest.main()
