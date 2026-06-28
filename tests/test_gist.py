"""GIST integer STATE core (slice 2) — the determinism foundation.

Proves the ratification's load-bearing guarantees for this slice: the decay operator is
deterministic and integer, firmness is float-free, and state round-trips through bytes exactly
(gate G1). No crypto, no remember.py coupling, no nightly fold here — those are later slices.

Run: python3 -m unittest discover -s tests
"""
import decimal
import random
import unittest

from core.gist import (
    DAY_MINUTES, SCALE, Beta, Schema, TimeStat, confidence_q, decay_q, decode_state,
    encode_state, firmness, varint_decode, varint_encode, zigzag_decode, zigzag_encode,
)


class DecayTests(unittest.TestCase):
    def test_identity_at_zero_nights(self):
        self.assertEqual(decay_q(123456, 0), 123456)

    def test_zero_value_stays_zero(self):
        self.assertEqual(decay_q(0, 17), 0)

    def test_halves_over_one_half_life(self):
        self.assertEqual(decay_q(1_000_000, 30), 500_000)   # 2**(-30/30) = 0.5 exactly
        self.assertEqual(decay_q(1_000_000, 60), 250_000)

    def test_negative_nights_refused(self):
        with self.assertRaises(ValueError):
            decay_q(1000, -1)

    def test_monotone_non_increasing(self):
        prev = 1_000_000
        for n in range(1, 40):
            cur = decay_q(1_000_000, n)
            self.assertLessEqual(cur, prev)
            prev = cur

    def test_deterministic_and_leaves_global_context_untouched(self):
        before = decimal.getcontext().prec
        a = decay_q(987_654, 7)
        b = decay_q(987_654, 7)
        self.assertEqual(a, b)
        self.assertEqual(decimal.getcontext().prec, before)  # we never mutate the global ctx

    def test_known_single_night(self):
        # 2**(-1/30) ≈ 0.9771599... ; 1000 * that = 977.159..., banker-rounds to 977
        self.assertEqual(decay_q(1000, 1), 977)

    def test_golden_decay_vectors(self):
        # Pin the operator's output so a future libmpdec last-ULP change can never silently
        # alter persisted/signed state without a failing test (external review G-1). These are
        # the canonical decay of 1_000_000 milli-units at a range of night counts.
        golden = {0: 1_000_000, 1: 977_160, 7: 850_667, 15: 707_107, 30: 500_000, 60: 250_000, 90: 125_000}
        for nights, expected in golden.items():
            self.assertEqual(decay_q(1_000_000, nights), expected, f"decay at {nights} nights drifted")

    def test_deterministic_across_decimal_backends(self):
        # decay_q rests on Decimal being identical across CPython's C (_decimal) and pure-Python
        # (_pydecimal) backends. Force the pure-Python one and assert it matches the live result,
        # so the "bit-identical on every host" claim is gated, not just asserted in prose (G-1).
        import importlib
        try:
            pydec = importlib.import_module("_pydecimal")
        except ImportError:
            self.skipTest("_pydecimal not available")
        ctx = pydec.Context(prec=50, rounding=pydec.ROUND_HALF_EVEN)
        two, hl = pydec.Decimal(2), pydec.Decimal(30)
        for value_q in (1000, 1_000_000, 987_654, 5_000_000_000):
            for nights in (1, 7, 15, 30, 61):
                factor = ctx.power(two, ctx.divide(pydec.Decimal(-nights), hl))
                scaled = ctx.multiply(pydec.Decimal(value_q), factor)
                py = int(scaled.to_integral_value(rounding=pydec.ROUND_HALF_EVEN))
                self.assertEqual(py, decay_q(value_q, nights),
                                 f"backend mismatch at value={value_q} nights={nights}")


class FirmnessTests(unittest.TestCase):
    def test_float_free_and_clamped(self):
        self.assertEqual(firmness(Beta(0, 0)), 0)
        self.assertEqual(firmness(Beta(1 * SCALE, 0)), 0)      # 1 day -> bit_length 1 -> 0
        self.assertEqual(firmness(Beta(2 * SCALE, 0)), 1)      # 2 days -> 1
        self.assertEqual(firmness(Beta(40 * SCALE, 0)), 5)     # 40 days -> floor(log2 40)=5
        self.assertEqual(firmness(Beta(100_000 * SCALE, 0)), 9)  # clamped at 9
        self.assertIsInstance(firmness(Beta(40 * SCALE, 0)), int)


class ConfidenceTests(unittest.TestCase):
    def test_in_unit_interval(self):
        for a, b in [(0, 0), (10 * SCALE, 0), (0, 10 * SCALE), (5 * SCALE, 5 * SCALE)]:
            c = confidence_q(Beta(a, b))
            self.assertGreaterEqual(c, 0)
            self.assertLessEqual(c, SCALE)

    def test_prior_pulls_sparse_evidence_low(self):
        # one fire, no misses: prior B(.3,4) keeps it well under 50%
        self.assertLess(confidence_q(Beta(1 * SCALE, 0)), 500)

    def test_strong_evidence_approaches_one(self):
        self.assertGreater(confidence_q(Beta(100 * SCALE, 0)), 950)


class TimeStatTests(unittest.TestCase):
    def test_mean_tracks_observations(self):
        t = TimeStat().add(420).add(440)  # 07:00 and 07:20
        self.assertEqual(t.mean_milli_minutes(), (430 * SCALE))  # mean 430 min, in milli-minutes

    def test_uniform_decay_approximately_preserves_mean(self):
        # In exact arithmetic uniform decay leaves μ=S1/W unchanged. Under per-field
        # banker's rounding the two fields round slightly differently, so μ is preserved
        # only WITHIN ROUNDING (here < 1 minute). Decay is still fully deterministic (G1);
        # this is an honest fixed-point caveat, not a bug.
        t = TimeStat().add(420).add(440)
        drift = abs(t.decayed(5).mean_milli_minutes() - t.mean_milli_minutes())
        self.assertLess(drift, SCALE)  # < 1 minute of rounding drift

    def test_minute_bounds_enforced(self):
        with self.assertRaises(ValueError):
            TimeStat().add(DAY_MINUTES)
        with self.assertRaises(ValueError):
            TimeStat().add(-1)

    def test_variance_non_negative(self):
        t = TimeStat().add(100).add(200).add(300)
        self.assertGreaterEqual(t.var_minutes2(), 0)


class ZigzagVarintTests(unittest.TestCase):
    def test_zigzag_roundtrip(self):
        for n in [0, -1, 1, -2, 2, 1000, -1000, 2**40, -(2**40)]:
            self.assertEqual(zigzag_decode(zigzag_encode(n)), n)

    def test_varint_roundtrip(self):
        for u in [0, 1, 127, 128, 300, 2**63, 2**70]:
            v, nxt = varint_decode(varint_encode(u), 0)
            self.assertEqual(v, u)

    def test_varint_rejects_negative(self):
        with self.assertRaises(ValueError):
            varint_encode(-1)


class G1RoundTripTests(unittest.TestCase):
    """Gate G1: state -> bytes -> state identity, on a fuzz corpus."""

    def _random_schema(self, rng):
        kind = rng.choice(["seq", "rule", "obs"])
        daytype = rng.choice(["wd", "we", "aw"])
        daypart = rng.choice(["dawn", "am", "mid", "pm", "eve", "night"])
        ntok = rng.randint(1, 4)
        tokens = tuple(f"Z[{rng.choice('kbfu')}]" for _ in range(ntok))
        beta = Beta(rng.randint(0, 5_000_000), rng.randint(0, 5_000_000))
        t = TimeStat(rng.randint(0, 5_000_000), rng.randint(0, 5_000_000_000),
                     rng.randint(0, 5_000_000_000_000))
        return Schema(kind, daytype, daypart, tokens, beta, t, rng.randint(0, 5_000_000))

    def test_roundtrip_identity_on_fuzz_corpus(self):
        rng = random.Random(20260627)
        for _ in range(2000):
            schemas = [self._random_schema(rng) for _ in range(rng.randint(0, 6))]
            data = encode_state(schemas)
            back = decode_state(data)
            expected = sorted((s.normalized() for s in schemas), key=Schema.key)
            self.assertEqual(back, expected)

    def test_encode_is_order_independent(self):
        a = Schema("rule", "wd", "eve", ("Z[k]", "Z[b]"), Beta(3000, 1000))
        b = Schema("obs", "we", "am", ("Z[u]",), Beta(2000, 0))
        self.assertEqual(encode_state([a, b]), encode_state([b, a]))  # sorted by key

    def test_decoded_fields_are_all_int(self):
        s = Schema("rule", "wd", "eve", ("Z[k]",), Beta(3000, 1000), TimeStat(2000, 84000, 3_528_000), 5000)
        (back,) = decode_state(encode_state([s]))
        for v in (back.beta.a_q, back.beta.b_q, back.time.W, back.time.S1, back.time.S2, back.day_mass_q):
            self.assertIsInstance(v, int)
            self.assertNotIsInstance(v, bool)

    def test_empty_state_roundtrips(self):
        self.assertEqual(decode_state(encode_state([])), [])


if __name__ == "__main__":
    unittest.main()
