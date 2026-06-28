"""The storage limb (Charter 28a) — silent densify, a notice only when almost full.

Proves the owner's ask: it stays quiet while tidying, speaks ONLY on a worsening transition
into LOW/CRITICAL, never flaps at a boundary (hysteresis), and never re-nags within a day
(debounce). Pure: a fake disk-usage seam drives every band without touching a real disk.

Run: python3 -m unittest discover -s tests
"""
import unittest
from dataclasses import dataclass

from core.bus import Bus
from core.groundskeeper import Bands, Groundskeeper
from core.tile import Event

DAY = 86400.0


@dataclass
class _DU:
    total: int
    free: int


class _FakeDisk:
    """A controllable disk-usage seam: set .frac to the free fraction you want next."""
    def __init__(self, frac: float = 1.0):
        self.frac = frac

    def __call__(self, path):
        return _DU(total=1000, free=int(1000 * self.frac))


def _gk(bus, disk, **kw):
    # snapshot_provider returns an empty dict; tail file won't exist (tail_bytes=0)
    return Groundskeeper("/nonexistent-state", bus, lambda: {}, disk_usage=disk, **kw)


class BandMachineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = Bus()
        self.disk = _FakeDisk(1.0)
        self.notices: list = []
        self.says: list = []
        self.bus.subscribe("storage.pressure", lambda e: self.notices.append(e))
        self.bus.subscribe("interface.say", lambda e: self.says.append(e))
        self.gk = _gk(self.bus, self.disk)

    async def tick(self, frac: float, now: float) -> str:
        self.disk.frac = frac
        band = await self.gk.tick(now)
        await self.bus.drain()
        return band

    async def test_healthy_disk_is_silent(self) -> None:
        self.assertEqual(await self.tick(0.80, 0.0), "OK")
        self.assertEqual(self.notices, [])
        self.assertEqual(self.says, [])

    async def test_notice_band_densifies_but_stays_silent(self) -> None:
        # 12% free → NOTICE: it tidies (no crash) but never speaks
        self.assertEqual(await self.tick(0.12, 0.0), "NOTICE")
        self.assertEqual(self.notices, [])
        self.assertEqual(self.says, [])

    async def test_low_band_notifies_once(self) -> None:
        band = await self.tick(0.09, 0.0)
        self.assertEqual(band, "LOW")
        self.assertEqual(len(self.notices), 1)
        self.assertEqual(self.notices[0].payload["band"], "LOW")
        self.assertEqual(len(self.says), 1)            # one governed spoken heads-up
        self.assertEqual(self.says[0].payload["kind"], "proactive")

    async def test_critical_speaks_as_exempt_alert(self) -> None:
        await self.tick(0.04, 0.0)
        self.assertEqual(self.says[-1].payload["kind"], "alert")   # must be heard, bypasses budget

    async def test_steady_low_notifies_only_once(self) -> None:
        # held at LOW across several ticks within the day → exactly one notice (no spam)
        for i in range(5):
            await self.tick(0.09, i * 100.0)
        self.assertEqual(len(self.notices), 1)

    async def test_hysteresis_no_flap_at_boundary(self) -> None:
        await self.tick(0.09, 0.0)                      # enter LOW
        self.assertEqual(len(self.notices), 1)
        b = await self.tick(0.11, 100.0)                # above low_in(0.10) but below low_out(0.14)
        self.assertEqual(b, "LOW")                      # still LOW — no clear, no re-notify
        self.assertEqual(len(self.notices), 1)

    async def test_clear_then_renter_debounced_within_a_day(self) -> None:
        await self.tick(0.09, 0.0)                      # LOW (notice #1)
        await self.tick(0.80, 100.0)                    # recover to OK (silent)
        await self.tick(0.09, 200.0)                    # LOW again, same day → debounced
        self.assertEqual(len(self.notices), 1)

    async def test_renotify_after_a_day(self) -> None:
        await self.tick(0.09, 0.0)
        await self.tick(0.80, 100.0)
        await self.tick(0.09, DAY + 200.0)              # a day later → allowed to notify again
        self.assertEqual(len(self.notices), 2)

    async def test_recovery_is_silent(self) -> None:
        await self.tick(0.04, 0.0)                      # CRITICAL
        before = len(self.says)
        await self.tick(0.80, 100.0)                    # back to OK
        self.assertEqual(len(self.says), before)        # recovery says nothing new


class DensifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_pressure_forces_a_compaction(self) -> None:
        compacts: list = []

        class _Bus(Bus):
            def compact(self, snap):
                compacts.append(snap)

        bus = _Bus()
        gk = _gk(bus, _FakeDisk(0.12))                  # NOTICE band on first tick
        await gk.tick(0.0)
        self.assertEqual(len(compacts), 1)              # densified silently on entering NOTICE


if __name__ == "__main__":
    unittest.main()
