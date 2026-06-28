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

import datetime
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


def decay_q(value_q: int, nights: int, hl: int = HALF_LIFE_NIGHTS) -> int:
    """Decay a fixed-point integer by ``2**(-nights/hl)``, banker's-rounded back to an integer.
    Deterministic across hosts (pinned Decimal context + ROUND_HALF_EVEN). `hl` is an INTEGER
    half-life in nights (default 30) — the persistence path passes a longer, earned one; it is
    never a float, so the signed state stays bit-identical across hosts.

    ``nights == 0`` is the identity; a negative ``nights`` is refused — a replayed clock never
    runs backward, so mass never grows (mirrors `remember.py`'s clamp)."""
    if nights < 0:
        raise ValueError("decay_q: nights must be >= 0 (time never runs backward)")
    if nights == 0 or value_q == 0:
        return value_q
    exponent = _CTX.divide(decimal.Decimal(-nights), decimal.Decimal(hl))
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
        # Confidence (beta) and the time-shape decay at BASE — so a stopped routine still fades
        # fast (anti-fossilization, untouched). PERSISTENCE (day_mass) decays at the line's
        # EARNED half-life, so a deeply-proven pattern lingers for years as a low-confidence
        # "you used to…" memory — present-belief honesty + long-record wisdom, decoupled.
        return replace(self, beta=self.beta.decayed(nights), time=self.time.decayed(nights),
                       day_mass_q=decay_q(self.day_mass_q, nights, persist_hl(self.beta)))


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


# Persistence (≠ confidence): how long a line's RECORD survives, earned by how proven it is.
# Confidence still decays at BASE (30); only this — the day_mass that gates the forget-drop —
# earns a longer half-life, so a months-proven routine lingers for years as honest low-confidence
# wisdom. Integer + bit_length-derived → deterministic, no float in the signed state.
PERSIST_PER_FIRM = 75   # extra half-life nights per firmness step
PERSIST_MAX = 365       # the "max 1 year" ceiling (Charter 22a) — applied to record, not belief
PERSIST_FLOOR = SCALE   # a line is still "a thing that existed" while day_mass ≥ 1 day-unit


def persist_hl(beta: Beta) -> int:
    """The earned persistence half-life (nights) for a line of this evidence depth: BASE for a
    coincidence (firmness 0 → 30), rising to the 1-year ceiling for a months-proven routine."""
    return min(PERSIST_MAX, HALF_LIFE_NIGHTS + PERSIST_PER_FIRM * firmness(beta))


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


# --------------------------------------------------------------------------- #
# Slice 4 — deterministic day-type + daypart classifiers (pinned, float-free)
# --------------------------------------------------------------------------- #
GIST_NMIN = 3          # firmness floor to promote obs → rule (mirrors remember.NMIN_DAYS)
MAX_SCHEMAS = 256      # the hard ceiling on stored behaviour lines (the prune budget)

# Pinned daypart boundaries over local-midnight minutes [0,1440). 'night' wraps both ends.
_DAYPART_BOUNDS = ((0, "night"), (300, "dawn"), (480, "am"), (720, "mid"),
                   (960, "pm"), (1140, "eve"), (1320, "night"))


def daypart_of(minute: int) -> str:
    """The pinned daypart for a local-midnight minute. Deterministic, no float, no locale."""
    if not 0 <= minute < DAY_MINUTES:
        raise ValueError(f"minute {minute} out of [0,{DAY_MINUTES})")
    label = "night"
    for start, lab in _DAYPART_BOUNDS:
        if minute >= start:
            label = lab
        else:
            break
    return label


def daytype_of(date_iso: str, *, away: bool = False) -> str:
    """Weekday / weekend / away — the day-type axis that stops Saturday being conflated with
    Tuesday. `away` (owner not home that day) wins; otherwise Sat/Sun → 'we', else 'wd'."""
    if away:
        return "aw"
    return "we" if datetime.date.fromisoformat(date_iso).weekday() >= 5 else "wd"


# --------------------------------------------------------------------------- #
# Slice 5 — the nightly fold: events → schemas, with counted absence + a hard prune
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DayObs:
    """One fold input: an event fired at `minute` (0..1439 local) carrying identity `tokens`
    (e.g. the topic + zone). The fold keys on the parsed structure, never the string spelling."""
    minute: int
    tokens: tuple[str, ...]


def _match_key(daytype: str, daypart: str, tokens) -> tuple:
    """The STRUCTURAL identity the fold matches on — kind is excluded so an obs that earns
    promotion to rule keeps folding into the same line (kind is derived, never a split-key)."""
    return (daytype, daypart, tuple(sorted(tokens)))


def _kind_for(beta: Beta, prior_kind: str) -> str:
    """obs until there's enough evidence (firmness ≥ nmin), then rule. `seq` is preserved as-is
    (sequence lines are a later milestone, not produced by this single-event fold)."""
    if prior_kind == "seq":
        return "seq"
    return "rule" if firmness(beta) >= GIST_NMIN else "obs"


def _payoff(s: Schema) -> int:
    """A schema's predictive worth for the prune: posterior confidence × evidence depth. Noise
    (low confidence, shallow evidence) sinks to the bottom and is dropped first. Integer."""
    return confidence_q(s.beta) * (firmness(s.beta) + 1)


def _prune_to_ceiling(schemas: list[Schema], max_schemas: int) -> list[Schema]:
    """Bound the stored schema count (the storage-forever guarantee). A pragmatic stand-in for
    the MDL ideal: keep the most predictive `max_schemas`, drop the rest. Deterministic
    tie-break on the canonical key so the survivor set is replay-stable."""
    if len(schemas) <= max_schemas:
        return schemas
    ordered = sorted(schemas, key=lambda s: (-_payoff(s), s.key()))
    return ordered[:max_schemas]


def fold_day(prior: list[Schema], observations: list[DayObs], *, daytype: str,
             nmin: int = GIST_NMIN, max_schemas: int = MAX_SCHEMAS,
             off_zones=frozenset()) -> list[Schema]:
    """Fold one day of raw events into the schema state — the heart of the nightly distill.

    Deterministic and integer-only. The night's work, in order:
      1. age the prior state by one night (`decay_q`);
      2. for each fire, α += SCALE on its (daytype, daypart, tokens) line + fold its minute;
      3. **counted absence** — every existing line of *today's* daytype that did NOT fire gets
         β += SCALE, so a stopped routine mean-reverts within days (anti-fossilization);
      4. derive each line's kind (obs→rule at the nmin firmness floor);
      5. drop lines faded to nothing and any referencing an off-limits zone (the OFF-fence);
      6. prune to the hard ceiling so the stored count is bounded forever.
    """
    decayed = [s.decayed(1) for s in prior]
    seqs = [s for s in decayed if s.kind == "seq"]               # passthrough (later milestone)
    by_match: dict[tuple, Schema] = {
        _match_key(s.daytype, s.daypart, s.tokens): s for s in decayed if s.kind != "seq"}

    fired: set[tuple] = set()
    for obs in observations:
        toks = tuple(sorted(obs.tokens))
        if off_zones and any(t in off_zones for t in toks):     # OFF-fence at ingest
            continue
        mk = (daytype, daypart_of(obs.minute), toks)
        cur = by_match.get(mk) or Schema(kind="obs", daytype=daytype, daypart=mk[1], tokens=toks)
        cur = replace(cur, beta=Beta(cur.beta.a_q + SCALE, cur.beta.b_q),
                      time=cur.time.add(obs.minute), day_mass_q=cur.day_mass_q + SCALE)
        by_match[mk] = cur
        fired.add(mk)

    for mk, s in list(by_match.items()):                        # counted absence
        if s.daytype == daytype and mk not in fired:
            by_match[mk] = replace(s, beta=Beta(s.beta.a_q, s.beta.b_q + SCALE))

    out: list[Schema] = []
    for s in by_match.values():
        if off_zones and any(t in off_zones for t in s.tokens):  # OFF-fence at write
            continue
        # Forget-drop. A PROVEN line is kept as long as its earned persistence (day_mass)
        # survives — so it lingers for years as a low-confidence "you used to…" record, even
        # after its belief has honestly collapsed. An unproven coincidence is forgotten the
        # moment both its evidence and its (base-decayed) mass fade to nothing.
        proven = firmness(s.beta) >= GIST_NMIN
        keep = (s.day_mass_q >= PERSIST_FLOOR) if proven else \
               (s.beta.a_q + s.beta.b_q >= 1 or s.day_mass_q >= 1)
        if not keep:
            continue
        out.append(replace(s, kind=_kind_for(s.beta, s.kind)))
    out += seqs
    return _prune_to_ceiling(out, max_schemas)


# --------------------------------------------------------------------------- #
# Slice 6 — the prose BRIEF: the honest, plain-words "What Homie Knows" render
# --------------------------------------------------------------------------- #
# TENSE IS THE HONESTY CONTRACT (council, HCI): present tense only for a live belief; a
# "starting to notice" hedge below the evidence floor; PAST tense the instant confidence falls
# below the action threshold — so a faded line can never read as a present claim. The exact
# number is always revealable; the word is what the owner reads.
ACTION_THRESHOLD = 400   # milli-confidence below which a proven line is spoken in the past tense
_CONF_WORDS = ((900, "almost always"), (650, "usually"), (400, "often"), (0, "sometimes"))
_DAYTYPE_PHRASE = {"wd": "on weekdays", "we": "at the weekend", "aw": "when you're away"}
_DAYPART_PHRASE = {"dawn": "early", "am": "in the morning", "mid": "around midday",
                   "pm": "in the afternoon", "eve": "in the evening", "night": "at night"}


def conf_word(c_q: int) -> str:
    """A TOTAL (milli-confidence → word) map, thresholds pinned. Never overclaims."""
    for thr, word in _CONF_WORDS:
        if c_q >= thr:
            return word
    return "sometimes"


def _clause(tokens: tuple[str, ...]) -> str:
    """tokens → a plain phrase. ('coffee','kitchen') → 'coffee in the kitchen'. Render-only —
    never the raw token soup; an off-limits token never reaches here (the fold OFF-fenced it)."""
    parts = [t.replace("_", " ") for t in tokens]
    if len(parts) == 2:
        return f"{parts[0]} in the {parts[1]}"
    return " · ".join(parts)


def line_text(s: Schema) -> str:
    """One behaviour line as an honest sentence, its tense carrying its confidence."""
    when = f"{_DAYTYPE_PHRASE.get(s.daytype, s.daytype)} {_DAYPART_PHRASE.get(s.daypart, s.daypart)}"
    what = _clause(s.tokens)
    c, f = confidence_q(s.beta), firmness(s.beta)
    if f < GIST_NMIN:                                  # below the evidence floor → tentative
        return f"I'm starting to notice {what} {when} — not sure yet."
    if c < ACTION_THRESHOLD:                           # proven once, now faded → past tense
        return f"You used to {what} {when}."
    return f"{when.capitalize()} you {conf_word(c)} {what}."


def render_brief(schemas: list[Schema], *, min_firmness: int = 0) -> list[str]:
    """The plain-words brief, most-telling first. Pure (no I/O). `min_firmness` can hide the
    'starting to notice' tier for a tighter glance. The cortex reads this; the owner sees it on
    the 'What Homie Knows' page — same honest text, never a stale belief dressed as present."""
    out = []
    for s in sorted(schemas, key=lambda s: (-_payoff(s), s.key())):
        if firmness(s.beta) < min_firmness:
            continue
        out.append(line_text(s))
    return out


# --------------------------------------------------------------------------- #
# The Dream Journal (M7): retrieval over the distilled memory. NOT a new store and NOT an
# embedder — the GIST schema keys are already a pre-tokenised structured index (daytype,
# daypart, sorted tokens), so relevance is deterministic integer facet-overlap, computable on
# the always-on node with no GPU, no float, no model. An "episode summary" is just line_text(s);
# recall is a QUERY over the memory that already exists. (Council: ML-retrieval engineer.)
# --------------------------------------------------------------------------- #
_RECALL_W_DAYTYPE = 4   # same kind of day (wd/we/aw) — gates Saturday from Tuesday
_RECALL_W_DAYPART = 2   # same part of day — a soft nudge
_RECALL_W_TOKEN = 3     # a shared token (the zone/domain) — the strongest "same situation" signal


def recall(schemas: list[Schema], *, daytype: str, daypart: str, tokens,
           k: int = 3, min_firmness: int = GIST_NMIN) -> list[str]:
    """The honest lines most relevant to *this* moment, for injection into the cortex context.

    Pure, deterministic, integer-scored. Only FIRM lines recall (`min_firmness` = the evidence
    floor) so a tentative 'starting to notice' guess never steers a live decision — the honesty
    contract, enforced at the retrieval seam. A line that shares no facet scores 0 and is
    dropped, so an irrelevant moment honestly recalls nothing (`[]`) rather than padding noise.

    Relevance requires situational overlap: a line surfaces only if it shares a token (the
    zone/activity of the moment), with same-daytype / same-daypart as ranking boosts — so a
    line never surfaces merely because "it's also a weekday." Ranking is a total order on a
    tuple — (−score, −payoff, canonical key) — never on a bare score, so ties break
    deterministically (replay-stable under LANG/PYTHONHASHSEED, the discipline `render_brief`
    and the prune already use)."""
    ev_tok = frozenset(tokens)
    scored = []
    for s in schemas:
        if firmness(s.beta) < min_firmness:
            continue
        overlap = len(ev_tok & set(s.tokens))
        if overlap == 0:
            continue                         # no situational overlap → not THIS moment's memory
        score = _RECALL_W_TOKEN * overlap \
            + (_RECALL_W_DAYTYPE if s.daytype == daytype else 0) \
            + (_RECALL_W_DAYPART if s.daypart == daypart else 0)
        scored.append(((-score, -_payoff(s), s.key()), s))
    scored.sort(key=lambda t: t[0])
    return [line_text(s) for _, s in scored[:k]]


# --------------------------------------------------------------------------- #
# The fold SUMMARY: what changed between last night's memory and tonight's.
# Contentless by default (counts, not the firehose) — the overnight composer reads this to
# answer "did I get smarter last night?" honestly, without ever spoken-leaking specifics.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FoldSummary:
    """The night-over-night delta of the distilled memory. Pure structure; no I/O.

    A line is matched across the night by its STRUCTURAL key (daytype, daypart, tokens) — the
    same key the fold dedupes on — so an obs that earned promotion to a firm rule is recognised
    as the *same* line growing up, never a forget + a brand-new learn."""

    learned: tuple[str, ...] = ()     # lines that crossed into firm this night (clauses, for detail)
    faded: tuple[str, ...] = ()       # firm lines whose belief fell to past-tense ("you used to…")
    forgotten: int = 0                # lines dropped entirely (forget-drop / prune) — count only
    kept: int = 0                     # firm lines carried unchanged

    @property
    def changed(self) -> bool:
        return bool(self.learned or self.faded or self.forgotten)


def _firm(s: Schema) -> bool:
    return firmness(s.beta) >= GIST_NMIN


def summarize_fold(prior: list[Schema], new: list[Schema]) -> FoldSummary:
    """Compare last night's state to tonight's and report what changed, honestly. Pure.

    `learned` = a line that is firm tonight but was NOT firm last night (newly trustworthy).
    `faded`   = a line firm in both, but whose confidence dropped below the action threshold
                (now spoken in the past tense — a routine you've let go).
    `forgotten` = lines present last night, gone tonight (count only — they're nothing now).
    """
    pri = {_match_key(s.daytype, s.daypart, s.tokens): s for s in prior}
    nw = {_match_key(s.daytype, s.daypart, s.tokens): s for s in new}
    learned, faded, kept = [], [], 0
    for k, s in nw.items():
        if not _firm(s):
            continue
        old = pri.get(k)
        if old is None or not _firm(old):
            learned.append(_clause(s.tokens))
        elif confidence_q(old.beta) >= ACTION_THRESHOLD and confidence_q(s.beta) < ACTION_THRESHOLD:
            faded.append(_clause(s.tokens))
        else:
            kept += 1
    forgotten = sum(1 for k in pri if k not in nw)
    return FoldSummary(learned=tuple(sorted(learned)), faded=tuple(sorted(faded)),
                       forgotten=forgotten, kept=kept)
