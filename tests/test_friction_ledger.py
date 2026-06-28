"""The Friction Ledger (Phase D / step 6) — the undo timeline.

Records confirmed actions as reversible rows, remembers the prior state so an undo can restore
it, renders plain sentences, and never re-drives by itself.

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timezone

from core.bus import Bus
from core.friction_ledger import Action, FrictionLedger, describe
from core.tile import Event

UTC = timezone.utc


def at(h: int, m: int = 0) -> float:
    return datetime(2026, 3, 10, h, m, tzinfo=UTC).timestamp()


class DescribeTests(unittest.TestCase):
    def test_plain_sentence_no_raw_id(self) -> None:
        a = Action(1, at(19, 32), "light.kitchen", "on", "off", "lighting")
        s = describe(a, tz=UTC)
        self.assertIn("kitchen light", s)
        self.assertIn("on", s)
        self.assertIn("7:32pm", s)
        self.assertNotIn("light.kitchen", s)

    def test_undone_is_marked(self) -> None:
        a = Action(1, at(8), "light.hall", "off", "on", "lighting", undone=True)
        self.assertIn("(undone)", describe(a, tz=UTC))


class LedgerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = Bus()
        self.led = FrictionLedger(self.bus)
        await self.led.start()

    async def asyncTearDown(self) -> None:
        await self.led.stop()
        await self.bus.aclose()

    async def _done(self, actuator: str, value, ts: float) -> None:
        await self.bus.publish(Event("actuator.done", ts, {"actuator": actuator, "value": value,
                                                           "tile": "lighting"}, source="act"))
        await self.bus.drain()

    async def test_records_actions_newest_first(self) -> None:
        await self._done("light.kitchen", "on", at(8))
        await self._done("light.hall", "on", at(9))
        rows = self.led.recent()
        self.assertEqual([r.actuator for r in rows], ["light.hall", "light.kitchen"])

    async def test_prior_is_captured_for_undo(self) -> None:
        await self._done("light.kitchen", "on", at(8))     # prior unknown (first touch)
        await self._done("light.kitchen", "off", at(9))    # prior is "on"
        rows = self.led.recent()
        self.assertEqual(rows[0].value, "off")
        self.assertEqual(rows[0].prior, "on")              # undo restores "on"
        self.assertTrue(rows[0].reversible)

    async def test_first_touch_has_no_prior_so_not_reversible(self) -> None:
        await self._done("light.kitchen", "on", at(8))
        row = self.led.recent()[0]
        self.assertIsNone(row.prior)
        self.assertFalse(row.reversible)
        self.assertIsNone(self.led.inverse(row.id))

    async def test_inverse_restores_prior(self) -> None:
        await self._done("light.kitchen", "on", at(8))
        await self._done("light.kitchen", "off", at(9))
        rid = self.led.recent()[0].id
        self.assertEqual(self.led.inverse(rid), ("light.kitchen", "on"))

    async def test_mark_undone_flips_the_row_and_restores_current(self) -> None:
        await self._done("light.kitchen", "on", at(8))
        await self._done("light.kitchen", "off", at(9))
        rid = self.led.recent()[0].id
        self.led.mark_undone(rid)
        self.assertTrue(self.led.get(rid).undone)
        self.assertIsNone(self.led.inverse(rid))           # an undone row can't be undone again
        # the ledger's notion of "current" is back to the prior value
        await self._done("light.kitchen", "on", at(10))
        self.assertEqual(self.led.recent()[0].prior, "on")  # current had been restored to "on"

    async def test_lines_render_plain(self) -> None:
        await self._done("light.kitchen", "on", at(8))
        lines = self.led.lines(tz=UTC)
        self.assertTrue(lines and "kitchen light on" in lines[0])


if __name__ == "__main__":
    unittest.main()
