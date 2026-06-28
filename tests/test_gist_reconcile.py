"""GIST <-> Remember reconciliation - the bounded-tolerance check the GIST v2 ratification
required (amendment 1). GIST is an INDEPENDENT integer estimator, not derived from Remember;
this proves the two have not silently diverged. The comparable quantity is the BASE-decayed
EVIDENCE count: GIST's beta-evidence (a_q+b_q)/SCALE and Remember's decayed distinct-day count
_days both accrue 1/day and decay at the same base half-life (30), so over a single-routine
trace they track within a small bound. (GIST's day_mass deliberately decays SLOWER once
firmness rises - earned persistence - so it is NOT the quantity to reconcile.)

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timezone

from core.gist import DayObs, SCALE, daypart_of, fold_day
from core.remember import Remember
from core.tile import Event

UTC = timezone.utc


def _ts(day: int, hour: int = 8) -> float:
    # exactly 24h apart so Remember's lazy decay and GIST's per-night decay align
    return datetime(2026, 6, 1 + day, hour, 0, 0, tzinfo=UTC).timestamp()


class ReconcileTests(unittest.IsolatedAsyncioTestCase):
    async def test_gist_evidence_tracks_remember_days_within_bound(self) -> None:
        rem = Remember()
        schemas: list = []
        DAYS = 6
        minute = 8 * 60
        for d in range(DAYS):
            ts = _ts(d)
            await rem.record(Event("presence.arrived", ts, {"zone": "kitchen"}))
            schemas = fold_day(schemas, [DayObs(minute=minute, tokens=("home", "kitchen"))],
                               daytype="wd")

        rem_days = (await rem.normal("presence.arrived", "kitchen", _ts(DAYS - 1))).days
        line = next(s for s in schemas if tuple(sorted(s.tokens)) == ("home", "kitchen")
                    and s.daypart == daypart_of(minute))
        gist_evidence = (line.beta.a_q + line.beta.b_q) / SCALE

        self.assertGreater(rem_days, DAYS - 1.5)        # both accumulated ~DAYS of evidence
        self.assertAlmostEqual(rem_days, gist_evidence, delta=0.1)   # bounded tolerance


if __name__ == "__main__":
    unittest.main()
