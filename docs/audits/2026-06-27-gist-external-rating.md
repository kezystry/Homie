# GIST — Complete External Rating & Audit (independent Claude, 2026-06-27)

*Scope: the GIST memory subsystem — the v2.1 spec (`docs/MEMORY-GIST.md`), the built integer
core (`core/gist.py` slice 2, 366-test suite green), `tests/test_gist.py`, and the open
questions in `HANDOFF-GIST-REMEMBER.md`. I read all of it, ran the suite, **empirically
verified the load-bearing determinism claim across both CPython `decimal` backends**, and
confirmed the `remember.py` bug GIST exists to fix. The handoff asked me to *decide* its open
questions, not just discuss them — §4 below does that.*

---

## 1. The rating

| Dimension | Grade | One line |
|-----------|:-----:|----------|
| **Built core (slice 2) engineering** | **A** | Careful, integer-clean, well-tested for what it claims; determinism verified |
| **Determinism rigor** | **A−** | Verified bit-identical across backends — but unpinned (no cross-backend gate) + one docstring overclaim |
| **Statistical design (the 3 fixes)** | **A** | present_days Bernoulli, absence-Beta mean-reversion, day-type axis — all fix real, verified bugs |
| **Architecture (GIST vs Remember)** | **C+** | "Two independent estimators reconciled within tolerance" is a smell — two sources of truth that can disagree about the same household |
| **Scope / proportionality** | **C−** | The valuable 20% is ~50 lines; the other 80% (codec, Huffman, MDL, DP, HMAC, two-rate, reservoir, German) is research-grade machinery the deployment has no requirement for |
| **Epistemic honesty** | **B+** | The ratification caught two false guarantees — but a third (the `eps/rho` DP header) survived as "advisory," and one false invariance claim slipped into the built docstring |

**Overall: B+ on a curve where the engineering is A and the judgment about *what to build* is
C.** The code that exists is genuinely good. The risk is not the code — it's that a 7-agent
council, a 16-critic brainstorm, and a ratification panel have produced a beautifully-specified
memory format whose *justifying requirements are mostly speculative for a two-person home*. The
single most valuable thing you can do is cut, not polish.

---

## 2. The built core (slice 2) — verified line by line

**What's genuinely right:**
- **The round-trip (G1) is bulletproof.** `encode_state`/`decode_state` (`gist.py:220-262`) sort
  by canonical key, normalize tokens, fix field order, and zigzag-varint every integer — a pure
  arbitrary-precision-integer codec with no float, no hash-order, no locale dependence. The 2000-
  case fuzz + order-independence + empty-state tests cover it. This part cannot drift across hosts.
- **`firmness` is correctly float-free.** `n_days.bit_length() - 1` clamped 0..9 (`gist.py:144-151`)
  is exactly ⌊log₂ n_eff⌋ with no libm. Coarse by design (5 buckets over the realistic 3–40-day
  range), which is fine for a single-glyph render and the confidence-word threshold.
- **The decay operator is deterministic — I verified it.** `decay_q` (`gist.py:50-63`) uses a
  pinned `Decimal(prec=50, ROUND_HALF_EVEN)` context, passed explicitly, never mutating the global.
  I computed it under both `_decimal` (libmpdec) and `_pydecimal` across 208 cases: **0 integer
  mismatches**, and `2**(-1/30)` at prec=50 is character-identical between backends
  (`0.97715996843424595493269814617765452366631293874787`). The "bit-identical on every host"
  claim is empirically true today.

**What's wrong (small but real):**

| # | Finding | Sev | Where |
|---|---------|-----|-------|
| G-1 | **The determinism is verified but UNPINNED.** `decay_q` rests on `Decimal.power` with a non-integer exponent being correctly-rounded *identically* across libmpdec versions and the two CPython backends. I confirmed it holds now, but no test forces `_pydecimal` vs `_decimal` or pins golden decay vectors — so a future libmpdec last-ULP change would silently break the HMAC with no failing test. | **Med** | `test_gist.py` (no cross-backend case); `gist.py:60-63` |
| G-2 | **A false invariance claim slipped into the built docstring.** `TimeStat`'s docstring says uniform decay "leaves μ and σ² **unchanged** — the EW invariance property" (`gist.py:84-85`). Under per-field banker's rounding it does **not** — `μ = decay(S1)/decay(W)` differs from `S1/W` by rounding. The *test* is honest about this (`test_uniform_decay_approximately_preserves_mean`, "only WITHIN ROUNDING"). The code comment overclaims exactly the kind of guarantee this whole process exists to strike. | **Low** | `gist.py:84-85` vs `test_gist.py:83-90` |
| G-3 | **`var_minutes2` subtracts a floored mean.** `e_t2 - mean*mean` with `mean = S1//W` (whole minutes, `gist.py:109-111`) loses sub-minute precision in the squared term and floors tiny positives to 0 (a tight distribution reads as σ²=0). Acceptable for a "±mm" render; note it. | **Low** | `gist.py:104-111` |

**The cheap belt-and-suspenders the panel itself offered:** the ratification verdict (point 5)
named the alternative — decay by a fixed rational `P_num/P_den` with pure-integer banker's rounding,
eliminating `Decimal.power` (and the transcendental-correct-rounding assumption) entirely. Given I
verified Decimal holds today it isn't urgent, but for an HMAC you intend to reproduce across hosts
for *years*, pure-integer rational decay is strictly more robust than betting on libmpdec's
transcendental stability. Worth it when slice 3 touches this code anyway.

---

## 3. The spec — the three fixes are real; the rest is the question

**Genuinely valuable, fixes verified bugs (build these):**
1. **The `present_days` Bernoulli fix.** Confirmed at `remember.py:85`: `w[when.hour] += 1.0`
   counts *every event*, while `_days` counts distinct dates, so `rate = count/days`
   (`remember.py:96`) is events-per-hour-per-day and **can exceed 1.0** — "an empty house reads
   as 90% normal" is a real, current bug in the gate's own input. This is the one fix that
   improves the *live system* (the security gate), independent of all GIST machinery.
2. **Absence-counted Beta.** The "4-night guest fossilizes for 30 days" problem is real (`remember.py:96`
   "a stopped pattern's rate holds"). Scoring β on reached-but-silent dayparts so a stopped routine
   mean-reverts in ~3–5 days is a genuine correctness improvement.
3. **Day-type `{wd,we,aw}`.** A weekend lie-in poisoning the weekday wake schema is real; separate
   buckets fix it. The panel called it the highest-leverage fix and they're right.

These three are statistics, not infrastructure. They could live in `remember.py` in ~50 lines and
improve the gate *and* the LLM brief that renders from a now-correct model — **with no new file, no
codec, no determinism gates, no HMAC.**

**Everything else is the scope question:** the `§S` varint-delta compression, canonical-Huffman
legends, MDL bit-budget pruning, BOCPD-lite two-rate change-point, the score-ranked anomaly
reservoir, DP with sparse-vector accounting, the German catalog, and an HMAC over canonical integer
state. For a two-person home whose steady state is ~20–50 schemas across ~6 zones: 50 schemas are a
few KB of plain JSON — you do not need delta-varint compression or Huffman to fit them; the LLM
reads ~2000 tokens either way in an 8k context; MDL/DP/reservoir are optimizing a corpus that will
never be large enough to need them. The determinism CI gates (G1/G2/G3) *exist only because* of the
choice to persist+sign+cross-host-reproduce — a choice whose adversary is unclear on a single
LUKS-encrypted, single-user box.

---

## 4. The open questions — decided (as the handoff asked)

**Q1 — `present_days` semantics (the decision the handoff most wants):**
**Neither (a) nor (b) as written.** Choose **(a) at (key, hour) granularity with a GLOBAL
observed-day denominator.** Reasoning:
- (a) as written (per-*key* present_days ÷ per-key `_days`) gives `P(key active on a day)` but
  **drops the hour resolution** that is the histogram's whole point.
- (b) (per-(key,hour) distinct-day numerator ÷ per-key `_days`) keeps the hour but **conditions on
  the wrong base rate** — `P(hour fires | key active that day)` excludes days the zone was silent,
  so a 3am intruder in a normally-daytime-active room is scored against the wrong denominator. For
  the security question ("is presence here at this hour unusual *on a random day*?") the conditional
  base rate is exactly wrong.
- **Correct fix:** a 24-vector `present_days[key]` (decayed mass, incremented **at most once per
  (key, hour) per distinct date** — gated by a per-(key,hour) last-date check), divided by a **global
  decayed `observed_days`** counter (distinct dates the *home* logged any event). Then
  `P(key active at hour | a day) = present_days[key][hour] / observed_days ∈ [0,1]`, keeping hour
  resolution **and** the correct unconditional base rate. Cost: one 24-entry date-gate vector per key
  + one global counter + one global last-date — more than "4 lines," but it is the statistic that is
  actually correct. The "~4-line fix" framing undersells what a true `P(happens)` requires.

**Q2 — independent estimator vs renderer-of-one-model:**
**The independent estimator is a smell — but the handoff's alternative is also wrong, and there's a
better third option.** Two estimators of the same household that "may drift within a bounded
tolerance" means the gate (reads `remember.py`, float, continuous decay) and the cortex (reads GIST,
integer, nightly decay) can **judge the same event differently** — the gate ignores a "routine"
arrival while the brief calls it "rare," or vice versa. The day-mass reconciliation test does **not**
catch that, because it checks mass, not the derived rate/confidence the two consumers actually act
on. "Renderer of the existing model" (the handoff's alternative) can't work — `remember.py` holds
none of GIST's stats. So:
- **Recommended:** co-locate GIST's sufficient-statistic accumulation **in `remember.observe()`**
  (one event ingest, one bucketing → the two physically cannot disagree about *what happened*), with
  GIST's own integer nightly decay run in the ritual fold. Render GIST from those stats. The two
  representations are justified (in-memory float for gate speed; integer for a signable, inspectable
  artifact) — but they should share the *ingest*, not re-fold raw events independently.
- **And** strengthen the reconciliation test from "day-mass within rounding" to "the **derived rate
  / confidence** the gate and the brief rely on agree within a stated bound" — that is the property
  that actually matters, and the current test doesn't assert it.

**Q3 — scope (re-litigate freely):**
**Cut hard.** Ship the three statistical fixes (§3.1–3.3) inside `remember.py`. Defer or kill the
codec, Huffman, MDL, DP, two-rate, anomaly reservoir, German catalog, and the HMAC **until a
concrete requirement names them.** Each adds a determinism surface to maintain and a way to be
subtly wrong, for a corpus that converges to a few dozen lines. If you want the LLM to read a clean
memory, render the (corrected) `remember.py` model to prose directly — the integer STATE / codec /
signing is only warranted if you can name the adversary it defends against on a single-box,
LUKS-encrypted, single-user system.

**Q4 — the DP `eps/rho` header:**
**Cut it.** A header field `eps=0.7 rho=0.012` *looks* like a differential-privacy guarantee; the
spec admits there is no sensitivity table and the number is "advisory." A fabricated privacy
parameter is worse than none — it manufactures false confidence in exactly the audience (the owner,
a future reviewer) least able to check it. This is a third false guarantee surviving the same
process that correctly struck the first two; hold it to the same standard. If you want render-time
noise for the trust screen, call it noise, not ε.

**Q5 — `firmness` formula:** sound, keep. ⌊log₂ n_eff⌋ via `bit_length` is correct and float-free;
the 0..9 clamp is harmless headroom (n_eff rarely exceeds ~40 under a 30-day half-life).

**Q6 — determinism:** verified across both backends today (§2). Add the cross-backend regression
gate (G-1); adopt pure-integer rational decay when slice 3 touches the operator.

---

## 5. The throughline

GIST is what happens when an excellent engineering culture meets a problem that doesn't need most of
the engineering. The built slice is A-grade work and the three statistical insights are real and
worth shipping. But the format around them is a research artifact: it optimizes compression, signing,
and differential privacy for a household that produces a few dozen recurring patterns and trusts the
box it runs on. **The highest-value move is subtraction** — land the Bernoulli fix, the absence-Beta,
and the day-type axis as a small enrichment of the live model the gate already reads, render the
brief from that, and let the codec/Huffman/MDL/DP/HMAC machinery wait for a requirement that names
it. The council built a cathedral; the home needs a good notebook. Ship the notebook.

**One-line verdict:** *the integer core is excellent and verified; the statistics are right; the
scope is the bug. Cut to the three fixes, decide `present_days` as (a)-at-hour-with-global-
denominator, fold GIST's stats into the one model instead of running a second estimator, pin the
cross-backend determinism, and delete the `eps/rho` header.*
