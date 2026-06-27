# Handoff — GIST + Remember (for an independent review / rework)

*Prepared 2026-06-27 for a fresh reviewer (another Claude or a human). Scope: **Homie's memory
subsystem** — the `core/remember.py` pattern-of-life model and the new `core/gist.py` distilled-
memory format. This document is the entry point: it tells you what to read, what is built vs
designed, what is verified, and the **open questions where I want you to push back or rework**.*

> **Your charge:** review the design and the built code with fresh, skeptical eyes; confirm or
> refute the claims below; and rework anything that is wrong, fragile, or over-built. Do not
> assume my decisions are right — the most valuable thing you can do is find where they aren't.
> Three external audits + two internal panels have already improved this; a fourth pass is welcome.

## 1. Read these, in this order
1. **`docs/MEMORY-GIST.md`** — the GIST v2.1 spec. Start with the "⚖️ Ratification status" callout
   (binding amendments) and the "Ratified build order" at the end.
2. **`docs/audits/2026-06-27-gist-ratification.md`** — the panel verdict that produced those
   amendments (determinism, crypto, Bayesian, edge, HCI, scope reviews).
3. **`docs/audits/2026-06-27-third-review-deep.md`** — the external code audit of the wider branch
   (its §2 NEW-1/NEW-2 bugs in the HA adapter are already fixed; relevant here are the determinism
   and privacy themes).
4. **`core/remember.py`** — the live model (float, exponentially-decayed; the gate/tiles read it).
5. **`core/gist.py`** + **`tests/test_gist.py`** — the new integer STATE core (slice 2 — the only
   GIST code that exists yet).

## 2. What is BUILT vs DESIGNED (do not let the docs blur this)
- **BUILT, tested, green (366 tests total):**
  - `core/remember.py` — the existing pattern-of-life model (predates this work). Unchanged here.
  - `core/gist.py` **slice 2 only** — the integer STATE core *in isolation*: fixed-point stat
    objects (`Beta`, `TimeStat`, `Schema`), the pinned `decay_q` operator, integer
    `firmness`/`confidence_q`, and a deterministic byte serialization with an exact round-trip
    (gate **G1**, a 2000-case fuzz corpus). No crypto, no nightly fold, no `remember.py` coupling.
- **DESIGNED ONLY (paper, not code):** everything else in `docs/MEMORY-GIST.md` — the `§S`
  varint-delta framing (slice 3), the renderer/parser + day-type + G2 (slice 4), the absence-
  counted fold + `nmin` + OFF-fence (slice 5), the prose BRIEF (slice 6), wiring into
  `ritual.consolidate()` (slice 7), HMAC (slice 8), and all of slice 9 (crypto, DP, two-rate,
  RARE/DUE, transitions, German, overlay). **The memory system does not run yet.**

## 3. The crux you must judge: how GIST relates to Remember
The spec **v1 claimed** GIST "derives from `remember.py`'s snapshot, never recomputes, so the two
can't drift." The ratification panel proved that **false** against the code: `remember.py` holds
*none* of GIST's statistics (no Beta, no `present_days`, no EW moments, no day-type axis), and it
decays with `math.exp(-λ·dt)` over continuous epoch-seconds on host floats (`remember.py:70-71`),
while GIST decays integer milli-units once per night by `2^(-1/30)` with banker's rounding.

**v2.1 resolution (now in the spec):** GIST is an **independent integer estimator** folded over
the same raw events, sharing only the 30-day half-life *constant*. The two **may drift within a
bounded tolerance**; a reconciliation test (slice 7) asserts GIST day-mass tracks `remember._days`
within rounding — never equality.

**Question for you:** is "two independent estimators of the same household, reconciled within a
tolerance" the right architecture, or is the duplication a smell? The alternative — extend
`remember.py` to hold the richer integer statistics and make GIST a pure *renderer* of them — was
not chosen because it would rewrite the live, tested model the gate/tiles depend on. **Push on
this.** If you think the renderer-of-one-model design is cleaner and worth the churn, say so.

## 4. OPEN DESIGN QUESTION — slice 1 (`present_days`), unbuilt on purpose
The build order's slice 1 is "add a `present_days` counter to `remember.py` so confidence is a
true Bernoulli `P(happens on a day) ∈ [0,1]`." The motivating bug is real and verified:
`remember.py:86` counts **every event** in the numerator (`w[hour] += 1.0`) while the denominator
counts **distinct days** (`_days`), so `rate = count/days` is *events-per-day-at-hour* and **can
exceed 1.0** — an empty house can read as "90% normal."

**I deliberately did NOT build this yet, because the proposed fix is under-specified and I do not
want to ship a wrong statistic into the live model.** The brainstorm's text says "add a decayed
`present_days` incremented at most once per distinct date" — but `_days` is *already* incremented
exactly once per distinct date (`remember.py:83-85`). So a scalar `present_days` defined that way
**equals `_days`**, making `present_days/_days ≡ 1.0` — which fixes nothing. The real choice is:

- **(a)** denominator = "days the *home* was observed at all" (a new global opportunity counter),
  numerator `present_days[key]` = days *this key* fired ⇒ `P(key active on an observed day)`; or
- **(b)** keep per-key `_days` as the denominator and make the **numerator per (key, hour)** count
  distinct days that hour fired (a 24-vector of last-fired-dates), ⇒ `P(hour fires | key active)`.

These measure **different things**, both defensible. **This is the first decision I want the
reviewer to make** before slice 1 is written. (GIST slice 2 was built in isolation precisely so it
does not depend on this being resolved.)

## 5. Determinism guarantees in the built code — verify them
`core/gist.py` claims (and `tests/test_gist.py` checks): no float crosses the serialization
boundary; `decay_q` is deterministic via a pinned `decimal` context (not host floats); firmness is
integer `bit_length`, not `log2`; `state→bytes→state` is exact on a fuzz corpus. **One honest
caveat surfaced and is documented in the test:** under per-field banker's rounding, the EW mean
`μ=S1/W` is preserved by uniform decay only *within rounding* (< 1 minute), not exactly — the
decay is deterministic, the mathematical invariance is approximate. Confirm you agree that is
acceptable, and check the two still-unpinned items the spec defers to slice 3/4: the **varint-delta
reference frame** and the **canonical-Huffman ASCII tie-break** (both must be nailed before G2/G3
can truly guarantee cross-host byte-identity).

## 6. Things I am least sure about (start here if you want the highest-value targets)
- **The present_days semantics (§4)** — genuinely unresolved; pick (a) or (b) or a third option.
- **Independent-estimator vs renderer-of-one-model (§3)** — an architecture call worth re-opening.
- **Scope:** is even the *integer core* over-built for a 2-person household? The scope-hawk on the
  panel argued hard for cutting; I kept the core and deferred all of slice 9. Re-litigate freely.
- **The DP story** is downgraded to "advisory noise" with no theorem; the spec says so honestly,
  but if you think shipping *any* eps/rho header field (even advisory) is misleading, cut it.
- **`firmness` formula** (`bit_length - 1`, clamped 0..9) is a pinned choice, not a derived one —
  challenge the thresholds.

## 7. How to run what exists
```sh
python3 -m unittest discover -s tests          # full suite (366 tests, must stay green)
python3 -m unittest tests.test_gist -v         # the GIST integer core (slice 2) + G1 gate
```
The suite is the contract: any rework must keep it green (or change a test with a stated reason).
GIST `slice 2` adds no dependency, no I/O, and no coupling — it is safe to rework in isolation.
