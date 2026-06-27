"""Solar dusk/dawn — the latitude-correct dark-gate (fixes second-review N4).

Timestamps are built in explicit UTC so the assertions are independent of the host
timezone. Reference location: Kiel (~54.32°N, 10.14°E), where a hardcoded 18:00 dusk
is wrong by hours.

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timezone

from core import sun

KIEL = (54.32, 10.14)


def utc(y: int, mo: int, d: int, h: int, mi: int = 0) -> float:
    return datetime(y, mo, d, h, mi, 0, tzinfo=timezone.utc).timestamp()


class SunTests(unittest.TestCase):
    def test_dark_gate_tracks_season_at_high_latitude(self) -> None:
        # June 21:00 local (19:00 UTC) at Kiel is still daylight — the exact N4 bug a
        # hardcoded 18:00 cutoff gets wrong.
        self.assertFalse(sun.is_dark(utc(2026, 6, 21, 19), *KIEL))
        self.assertFalse(sun.is_dark(utc(2026, 6, 21, 11), *KIEL))   # midday, clearly light
        self.assertTrue(sun.is_dark(utc(2026, 6, 21, 22), *KIEL))    # ~midnight local, dark
        # December: dark already by 18:00 local (17:00 UTC) — the other half of N4.
        self.assertTrue(sun.is_dark(utc(2026, 12, 21, 17), *KIEL))
        self.assertFalse(sun.is_dark(utc(2026, 12, 21, 11), *KIEL))  # midday, light

    def test_summer_and_winter_sunset_differ_by_hours(self) -> None:
        def sunset_hour(ts: float) -> float:
            rise, set_ = sun.sun_events(ts, *KIEL)
            d = datetime.fromtimestamp(set_, tz=timezone.utc)
            return d.hour + d.minute / 60.0

        june = sunset_hour(utc(2026, 6, 21, 12))
        december = sunset_hour(utc(2026, 12, 21, 12))
        self.assertGreater(june - december, 3.0)  # ~5h at this latitude

    def test_polar_day_and_night(self) -> None:
        svalbard = (78.0, 16.0)
        self.assertFalse(sun.is_dark(utc(2026, 6, 21, 0), *svalbard))   # midnight sun
        self.assertTrue(sun.is_dark(utc(2026, 12, 21, 12), *svalbard))  # polar night


if __name__ == "__main__":
    unittest.main()
