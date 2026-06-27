"""GIST — the integer STATE core (slice 2 of the ratified build order).

This is the determinism foundation of Homie's distilled memory (`docs/MEMORY-GIST.md`), and
DELIBERATELY nothing more. It is built in complete isolation per the ratification panel:

  * **No float crosses the serialization boundary.** Every statistic is a fixed-point integer
    of milli-units (value × 1000). Decay, the Beta evidence, the time moments, firmness, and the
    byte encoding are all pure integer. The only place a float is ever allowed is event ingest
    (a continuous timestamp → an integer minute/daypart bucket), which happens OUTSIDE this file.
  * **No coupling to `core/remember.py`.** GIST is an INDEPENDENT estimator folded over the same
    raw events; it shares only the half-life *constant* (30 nights), never `remember.py`'s float
    arithmetic or values. (This file imports nothing from `remember`.)
  * **No crypto, no privacy noise, no nightly fold yet.** Those are later slices. The point of
    the isolation is to get the determinism gate (G1: ``state → bytes → state`` identity) green
    before anything is layered on top.

What lives here: the fixed-point stat objects (`Beta`, `TimeStat`, `Schema`), the pinned
`decay_q` operator, integer `firmness`/`confidence_q`, and a deterministic byte serialization
with an exact round-trip. The `§S` varint-delta *framing* (deltas vs the previous line / last
night) is slice 3; this slice encodes each schema's integers absolutely, which is enough to
prove the core round-trips.
"""
from __future__ import annotations

import decimal
from dataclasses import dataclass, field, replace

# Fixed-point scale: one unit of evidence is SCALE milli-units, so no float is ever stored.
SCALE = 1000
HALF_LIFE_NIGHTS = 30  # the ONLY thing shared with remember.py — a constant, not its math

# Weakly-informative prior Beta(0.3, 4): "most candidate routines are rare until proven."
PRIOR_A_Q = 300   # 0.3 × SCALE
PRIOR_B_Q = 4000  # 4.0 × SCALE

# Minutes in a day — time `t` for the EW moments is local-midnight-minutes in [0, 1439]
# (ratification: NOT epoch-seconds, which would make σ² = S2/W − μ² a precision-dead
# subtraction of ~1e21 integers).
DAY_MINUTES = 1440

# A pinned Decimal context makes decay platform-independent: the `decimal` module implements
# the General Decimal Arithmetic spec in software, so 2**(-n/30) is bit-identical on every host
# (unlike a libm pow over host floats). We pass this context explicitly and never mutate the
# process-wide thread-local context.
_CTX = decimal.Context(prec=50, rounding=decimal.ROUND_HALF_EVEN)
_TWO = decimal.Decimal(2)
_HL = decimal.Decimal(HALF_LIFE_NIGHTS)


def decay_q(value_q: int, nights: int) -> int:
    """Decay a fixed-point integer by ``2**(-nights/HALF_LIFE_NIGHTS)``, banker's-rounded back
    to an integer. Deterministic across hosts (pinned Decimal context + ROUND_HALF_EVEN).

    ``nights == 0`` is the identity; a negative ``nights`` is refused — a replayed clock never
    runs backward, so mass never grows (mirrors `remember.py`'s clamp)."""
    if nights < 0:
        raise ValueError("decay_q: nights must be >= 0 (time never runs backward)")
    if nights == 0 or value_q == 0:
        return value_q
    exponent = _CTX.divide(decimal.Decimal(-nights), _HL)
    factor = _CTX.power(_TWO, exponent)
    scaled = _CTX.multiply(decimal.Decimal(value_q), factor)
    return int(scaled.to_integral_value(rounding=decimal.ROUND_HALF_EVEN))


# --------------------------------------------------------------------------- #
# Fixed-point sufficient statistics
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Beta:
    """Absence-counted Beta evidence in milli-units: α accrues on a fire, β on a reached-but-
    no-show day (the fold that decides which is slice 5). All integer."""

    a_q: int = 0
    b_q: int = 0

    def decayed(self, nights: int) -> "Beta":
        return Beta(decay_q(self.a_q, nights), decay_q(self.b_q, nights))


@dataclass(frozen=True)
class TimeStat:
    """Exponentially-weighted time moments over local-midnight-minutes t ∈ [0,1439]:
    W = Σw, S1 = Σw·t, S2 = Σw·t². μ = S1/W (minutes), σ² = S2/W − μ². In exact arithmetic,
    uniform decay of (W,S1,S2) leaves μ and σ² unchanged (the EW invariance property); under
    per-field banker's rounding it holds only WITHIN ROUNDING (< 1 minute) — the decay is still
    fully deterministic, but the invariance is approximate (see test_uniform_decay_*)."""

    W: int = 0
    S1: int = 0
    S2: int = 0

    def decayed(self, nights: int) -> "TimeStat":
        return TimeStat(decay_q(self.W, nights), decay_q(self.S1, nights), decay_q(self.S2, nights))

    def add(self, minute: int, weight_q: int = SCALE) -> "TimeStat":
        """Fold one observation at `minute` (0..1439) with `weight_q` milli-units of weight."""
        if not 0 <= minute < DAY_MINUTES:
            raise ValueError(f"minute {minute} out of [0,{DAY_MINUTES})")
        return TimeStat(self.W + weight_q, self.S1 + weight_q * minute, self.S2 + weight_q * minute * minute)

    def mean_milli_minutes(self) -> int | None:
        """μ in milli-minutes (integer), or None if there is no weight yet."""
        return None if self.W == 0 else (self.S1 * SCALE) // self.W

    def var_minutes2(self) -> int | None:
        """σ² in minutes² (integer, floored ≥ 0), or None if there is no weight yet."""
        if self.W == 0:
            return None
        # E[t²] − E[t]², both scaled back to plain minutes²; clamp tiny negatives from flooring.
        e_t2 = self.S2 // self.W
        mean = self.S1 // self.W
        return max(0, e_t2 - mean * mean)


@dataclass(frozen=True)
class Schema:
    """One behavioural line's integer state. The display glyph/prose is a render OF this
    (slices 4/6); this object is the truth the HMAC will eventually cover (slice 8)."""

    kind: str           # 'seq' | 'rule' | 'obs'
    daytype: str        # 'wd' | 'we' | 'aw'
    daypart: str        # 'dawn' | 'am' | 'mid' | 'pm' | 'eve' | 'night'
    tokens: tuple[str, ...]
    beta: Beta = field(default_factory=Beta)
    time: TimeStat = field(default_factory=TimeStat)
    day_mass_q: int = 0

    def key(self) -> tuple[str, str, str, tuple[str, ...]]:
        """The typed canonical key — a TOTAL order independent of token spelling order, used
        both to dedupe in the fold and to give the serializer a deterministic line order."""
        return (self.kind, self.daytype, self.daypart, tuple(sorted(self.tokens)))

    def normalized(self) -> "Schema":
        """Tokens sorted — the canonical form the serializer round-trips to."""
        return replace(self, tokens=tuple(sorted(self.tokens)))

    def decayed(self, nights: int) -> "Schema":
        return replace(self, beta=self.beta.decayed(nights), time=self.time.decayed(nights),
                       day_mass_q=decay_q(self.day_mass_q, nights))


# --------------------------------------------------------------------------- #
# Integer readouts (float-free — firmness uses bit_length, never log2)
# --------------------------------------------------------------------------- #
def firmness(beta: Beta) -> int:
    """⌊log₂ n_eff⌋ via integer ``bit_length`` (NOT math.log2 — a libm float in the signed
    body would flip ±1 at power-of-two boundaries across hosts and break the HMAC). n_eff is
    the whole decayed days of evidence; result clamped to 0..9 for a single render glyph."""
    n_days = (beta.a_q + beta.b_q) // SCALE
    if n_days <= 0:
        return 0
    return min(9, n_days.bit_length() - 1)


def confidence_q(beta: Beta) -> int:
    """Bernoulli posterior mean (α₀+a)/(α₀+β₀+a+b) in milli-units ∈ [0,1000]. Integer."""
    num = PRIOR_A_Q + beta.a_q
    den = PRIOR_A_Q + PRIOR_B_Q + beta.a_q + beta.b_q
    return (num * SCALE) // den  # den ≥ PRIOR sum > 0, so always defined and in [0,1000]


# --------------------------------------------------------------------------- #
# Deterministic byte serialization (slice 2: absolute integers; §S delta-framing is slice 3)
# --------------------------------------------------------------------------- #
def zigzag_encode(n: int) -> int:
    """Map a signed int to an unsigned one (arbitrary precision): 0,-1,1,-2,2 → 0,1,2,3,4."""
    return (n << 1) if n >= 0 else ((-n << 1) - 1)


def zigzag_decode(u: int) -> int:
    return (u >> 1) if (u & 1) == 0 else -((u + 1) >> 1)


def varint_encode(u: int) -> bytes:
    """Unsigned LEB128."""
    if u < 0:
        raise ValueError("varint_encode: value must be unsigned (zigzag first)")
    out = bytearray()
    while True:
        b = u & 0x7F
        u >>= 7
        if u:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def varint_decode(data: bytes, i: int) -> tuple[int, int]:
    """Decode one unsigned LEB128 at offset `i`; return (value, next_offset)."""
    shift = result = 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _put_str(out: bytearray, s: str) -> None:
    raw = s.encode("utf-8")
    out += varint_encode(len(raw))
    out += raw


def _get_str(data: bytes, i: int) -> tuple[str, int]:
    n, i = varint_decode(data, i)
    return data[i:i + n].decode("utf-8"), i + n


def _put_int(out: bytearray, n: int) -> None:
    out += varint_encode(zigzag_encode(n))


def _get_int(data: bytes, i: int) -> tuple[int, int]:
    u, i = varint_decode(data, i)
    return zigzag_decode(u), i


def encode_state(schemas: list[Schema]) -> bytes:
    """Serialize the state to bytes, deterministically: schemas in canonical-key order, tokens
    sorted, fixed field order, all integers zigzag-varint. Same state → same bytes, regardless
    of input list order (the property G1/G2 rest on)."""
    ordered = sorted((s.normalized() for s in schemas), key=Schema.key)
    out = bytearray()
    out += varint_encode(len(ordered))
    for s in ordered:
        _put_str(out, s.kind)
        _put_str(out, s.daytype)
        _put_str(out, s.daypart)
        out += varint_encode(len(s.tokens))
        for t in s.tokens:
            _put_str(out, t)
        for v in (s.beta.a_q, s.beta.b_q, s.time.W, s.time.S1, s.time.S2, s.day_mass_q):
            _put_int(out, v)
    return bytes(out)


def decode_state(data: bytes) -> list[Schema]:
    """Parse bytes back to the schema list (in canonical order). Exact inverse of
    `encode_state` for normalized state — the G1 round-trip."""
    i = 0
    count, i = varint_decode(data, i)
    out: list[Schema] = []
    for _ in range(count):
        kind, i = _get_str(data, i)
        daytype, i = _get_str(data, i)
        daypart, i = _get_str(data, i)
        ntok, i = varint_decode(data, i)
        toks = []
        for _ in range(ntok):
            t, i = _get_str(data, i)
            toks.append(t)
        a_q, i = _get_int(data, i)
        b_q, i = _get_int(data, i)
        W, i = _get_int(data, i)
        S1, i = _get_int(data, i)
        S2, i = _get_int(data, i)
        day_mass_q, i = _get_int(data, i)
        out.append(Schema(kind, daytype, daypart, tuple(toks),
                          Beta(a_q, b_q), TimeStat(W, S1, S2), day_mass_q))
    return out
