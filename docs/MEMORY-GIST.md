# GIST — Homie's distilled memory format

*Invented by a research council (2026-06-27), then revised to **v2** by a maximum-fleet
brainstorm (16 expert critics + 4 red-teamers + a synthesis chair). The chair checked every
claim against the real `core/remember.py`, so the fixes below trace to actual lines of code,
not prose. Status: **decided design (v2), not yet built.***

## The idea (one line)
Don't store a household's events — store the **sufficient statistics of its recurring
behaviour** as an exact, integer, decayed state, and *render* that state into a tiny
human-readable field-notebook the local LLM reads. File: `memory.ddn` (Decayed Day-Note).

## What changed from v1 → v2 (the one structural inversion)
v1's headline promise was "the human string **is** the machine state, round-tripped exactly."
**That promise was false**, and 16/16 critics plus 3/3 high-severity red-teams hit the same
wall independently: a rendered line like `~.90 @0712±03` shows only the Beta **mean** and a
rounded clock time — it drops α+β and the sample count, so `Beta(9,1)` and `Beta(900,100)`
render identically and the parser **cannot** reconstruct what it rendered. v1 therefore had to
secretly reload the real numbers from `remember.py`'s snapshot — so what actually persisted was
a hidden sidecar, and the HMAC authenticated the lossy *view*, not the truth.

**v2 inverts the direction.** There is one **integer STATE block** that is the source of truth
and the thing the HMAC signs; the glyph notebook and the prose summary are **pure renders** of
that state. What you read is a faithful projection of what persists — and now the round-trip
(`state → bytes → state`) really is exact, because the bytes carry the whole state.

## Why it's still small, clean, and honest
- **Patterns, not instances.** A known schema costs ~0 bits; we spend bits only on **surprise**
  (novelty, friction, anomalies). Steady-state memory **converges** to a few hundred bytes of
  state + a ~2000-token prose brief, whether it covers a month or a year — it consolidates, it
  doesn't accumulate.
- **Exact integer state, no floats on the wire.** Every statistic is fixed-point integer
  (value ×1000), decayed by *multiply-then-round-half-even* once per nightly fold using the
  *same* `_factor` (half-life) as `core/remember.py`. No float ever crosses the serialization
  boundary, so the HMAC and the replay are bit-identical on every host — no "C-locale prayer"
  (this kills the `remember.py:139` 6-decimal rounding hazard the chair confirmed is real).
- **Human-inspectable by projection.** The "what Homie knows" trust screen reads a deterministic
  prose render of the signed state — faithful, and now provably so.

## The seven headline upgrades (each traced to its experts)
1. **STATE / VIEW split** — one integer state, two rendered views (glyph + prose); the string is
   never parsed back into numbers. *(info-theory, compression, DSL, determinism, DB, HCI, all 3 red-teams)*
2. **Exponentially-weighted time moments replace Welford.** Welford's `M2` is an unweighted
   sum-of-squares and is **mathematically invalid under exponential reweighting** — decaying μ
   and M2 by a scalar is *not* the decayed variance, which broke v1's replay guarantee. v2 keeps
   `(W, S1, S2)` (decayed mass, Σw·t, Σw·t²); μ=S1/W, σ²=S2/W−μ². One scalar multiply to decay,
   order-invariant. *(info-theory, Bayesian, drift, cog-sci)*
3. **Symmetric Beta with counted absence + a pinned prior.** v1 only ever added "it happened"
   (α); it never recorded "it could have but didn't" (β) — so per `remember.py:96` (`# d cancels:
   a stopped pattern's rate holds`) a 4-night house-guest's routine would **fossilize** for a
   full 30-day half-life. v2's fold scores β on every reached-but-no-show daypart, so a stopped
   routine mean-reverts in ~3–5 days. *(red-team #1, Bayesian)*
4. **True Bernoulli daily probability.** `remember.py:86` counts *every event* in the numerator
   and distinct days in the denominator, so v1's `rate` is events/day-at-hour and **can exceed
   1.0** — treating it as `P(happens)` is a confident lie (an empty house read as "90% normal").
   v2 adds a `present_days` counter (≤ one hit per distinct date) so confidence is a real
   `P(happens on a day) ∈ [0,1]`. *(red-team #2 — a ~4-line fix to the owner's own code)*
5. **Day-type as a first-class section axis `{wd, we, aw}`.** A weekend lie-in can no longer
   poison the weekday wake schema — they land in different buckets. *(11 of 16 experts; the
   single highest-leverage fix)*
6. **Two-rate consolidation + change-point fast-lane.** Fast (7d) / slow (180d) traces; a
   genuinely *moved* routine re-converges in ~7 days instead of ~30. *(cog-sci, drift, Bayesian, time-series)*
7. **Inter-arrival "rare-but-watch" slot + due-lane.** Monthly bins / a weekly carer decay
   against *their own period*, not the global 30d, and are force-injected when due within 24h; an
   overdue expected event flips to a **MISSING** anomaly (welfare-shaped for the mother).
   *(time-series, anomaly, cog-sci)*

## Grammar (v2 — two byte-exact LAYERS over one canonical integer state)
The `§S=` STATE block is the truth and the HMAC covers it; the glyph VIEW and the prose BRIEF
are pure deterministic renders.
```
codex   := header legend off? prior section+ rare? anomalies due? state sig
header  := "§GIST v2 home=<id8> day=<YYYY-MM-DD> n=<days> hl=30d hlfast=7d hlslow=180d"
                  " pri=B(.3,4) loc=de-DE@1 grammar=2 nmin=8 drift=lbf2.0 eps=0.7 rho=0.012"
legend  := "@Z " glyph"="name+   NL  "@T " glyph"="name+    ; canonical-Huffman by frequency, ties lexicographic
off     := "OFF: " name+         ; fenced spaces — unrepresentable by ABSENCE of a glyph (mum-flat)
section := "#" daytype "/" daypart NL line+   ; daytype∈{wd,we,aw}; daypart∈{dawn,am,mid,pm,eve,night}
line    := kind tokens flags " ~" conf firm drift? " @" time NL
              ; kind  ∈ {seq, rule, obs} → leading sigil (none)|! |.
              ; tokens namespaced: Z[..] zones, T[..] topics; ">" = sequence link (backed by a transition stat)
              ; flags (a reserved sigil class that can't collide with glyphs): /off +on ?novel *N(ring ref) °sensitive ^slow ~drift
              ; conf  = Bernoulli posterior mean (α₀+a)/(α₀+β₀+a+b), 2dp
              ; firm  = ⌊log₂ n_eff⌋ clamped 0–9, ONE superscript char — ".90 from 3 days" vs ".90 from 40 days"
              ; drift = trailing ~ if the change-point guard fired (re-converging fast)
              ; time  = @hhmm±mm in pinned civil minutes (ZoneInfo), DST-safe
rare    := "RARE:" NL (tokens " every~" gap "d±" gsd " due≈" dow " last=" date " ~" conf)*
anomaly := "#! " (score ":" date ":" glyphseq)*  ; SCORE-RANKED reservoir (s=−log₂ P_pred, bits); evict LOWEST score
due     := "DUE:" NL (tokens " @tomorrow~" hhmm)* ; any periodic schema predicted <24h, force-injected even if decayed
state   := "§S=" base64( per-line varint record, zigzag-delta-coded vs (a) prev line in section, (b) same line 1 night ago )
sig     := "§hmac=<b64-16>"      ; HMAC over header+sections+rare+anomalies+STATE — the TRUTH, not the view
```
**Match key (kills v1's silent split/merge):** the nightly fold keys on the *parsed* structure
`(kind, daytype, daypart, sorted(tokens))`, never on the rendered string (v1's undelimited glyph
soup let `Axk` parse two ways and corrupt the very stats it folded). `parse(render(state))==state`
**and** the canonical key being render-permutation-invariant are both CI gates.

## Layer B — the prose BRIEF (what the LLM actually reads)
The block injected into the 8B is **not glyphs** — it's a deterministic prose render of the same
state: *"On weekday mornings, almost always (91%, well-established) the owner moves
kitchen → bathroom → front door, leaving ~07:08 (typically 07:04–07:12)."* Confidence becomes a
word ("almost always / usually / sometimes") thresholded on the Bernoulli mean **and** firmness.
A `loc=de-DE` catalog renders the same state in German for the mother. The signed body stays
ASCII-only (so UTF-8 normalization can never break the HMAC); the German catalog is unsigned and
regenerated on demand. ~2000 tokens — trivial in a 4–8k context, and the accuracy win is on the
only thing that matters: the model acting correctly.

## Worked example (two weekend nights, against the real snapshot)
**Saturday 2026-06-27** — owner up later (kitchen→bath→door ~09:31); kitchen-off ~19:05 (no
correction); upstairs-on 22:30 (no reversal); a Tuesday carer is 14 days established; bin night
is due tomorrow:
```
§GIST v2 home=a3f1c0d9 day=2026-06-27 n=212 hl=30d hlfast=7d hlslow=180d pri=B(.3,4) loc=de-DE@1 grammar=2 nmin=8 drift=lbf2.0 eps=0.7 rho=0.012
@Z k=kitchen b=bath f=front-door u=upstairs
@T P=presence A=lightAct C=correction D=door
OFF: mum-flat
#wd/am
Z[k]>Z[b]>Z[f] ~.91⁵ @0708±04        ; weekday wake, firm (n_eff≈32), well-established
#we/am
Z[k]>Z[b]>Z[f] ~.78³ @0931±12        ; SATURDAY wake — own bucket, cannot poison the weekday line
#wd/eve
!Z[k]T[A]/off ~.88⁴ @1903±05         ; learned rule: kitchen light off ~19:03
.Z[u]T[A]/on ~.41² @2238±21          ; upstairs-on: obs only, NOT promoted — the one-off mean-reverted via no-show β
RARE:
Z[f]T[D] every~7d±1 due≈Tue last=2026-06-23 ~.82⁴   ; carer, weekly — decays vs its 7d period, not global 30d
DUE:
Z[f]T[D]·bins @tomorrow~0700         ; monthly bin run predicted <24h → force-injected though decayed
#! 9.2:2026-06-27:?Z[f]T[D]          ; score-ranked: one 9.2-bit unknown-at-door outranks seven 2-bit ones
§S=AAEC...(varint-delta integer state, the HMAC'd truth)...
§hmac=Qx8r2Vd1mK0pLn3w
```
**Sunday 2026-06-28** — a second weekend wake at 09:40 folds in: it matches the `#we/am` line by
*parsed structure*; the fold parses `§S=` to exact integers (not the lossy `.78`), decays
`(W,S1,S2)` and `(a,b)` by `2^(−1/30)`, adds the 09:40 hit (μ 09:31→09:34, σ tightens), scores
α today and β on every other reached we/am schema that didn't fire. The weekday `#wd/am` line is
**untouched** — the Sunday lie-in is structurally unable to poison it. The Tuesday carer (0 events
today, but elapsed 5d < gap+2σ ≈ 9d) does **not** decay toward novel. Re-render, re-noise with
the day's seed, re-sign; `parse(render(state))==state` byte-for-byte.

## Nightly distill algorithm (the "sleep" fold; stdlib, deterministic)
1. **Bin** today's normalized events into `(daytype, daypart)` sections + candidate schemas;
   daytype `{wd,we,aw}` from a deterministic calendar+presence function ("away" days count to
   neither weekday nor weekend).
2. **Match** each candidate to a live line by the **typed canonical key** (never the string).
3. **Decay then update** the integer stats with the *same* half-life as `PatternModel` (decay
   **before** update so replay is exact). Time via EW moments `(W,S1,S2)`; confidence via
   **symmetric** Beta — α on fire, **β on no-show** for every reached-but-silent schema.
4. **Promote/demote** with hysteresis (birth/death thresholds in **bits**, MDL); the `nmin`
   evidence floor blocks any render/promotion below ~8 decayed days, so a coincidence stays a
   low-confidence `?`, never a `!` rule.
5. **Prune** by an explicit **MDL bit-budget** (a line earns its place iff it shortens total
   description length) — not v1's arbitrary 12-lines/daypart cap.
6. **Two-rate + change-point:** maintain fast(7d)/slow(180d) traces; on a BOCPD-lite log-Bayes
   factor > `drift`, mark `~` and halve local evidence so a moved routine re-converges in ~7d.
7. **Re-render** the glyph VIEW + prose BRIEF deterministically, apply render-time privacy noise,
   **re-sign** the STATE+views, drop `°` lines, throw away the raw log. Only `memory.ddn` survives.

## Recall (how it's used)
- The cortex is fed the **prose BRIEF** (not glyphs), small enough to inject whole — no embeddings,
  no vector DB. For hot paths, pre-filter to the live section + all rules + due/rare + recent anomalies.
- The **novelty-gate and tiles never read the `.ddn`** — they query the clean, full-precision
  in-memory stats in `core/remember.py` (which never leave the box, so they carry no privacy cost).
  GIST *derives* from that snapshot; it never recomputes it independently, so the two can't drift.

## Privacy & encryption (structural, not bolted on)
- At rest: key from the owner's password (**Argon2id/scrypt → AES-GCM**), sealed in LUKS.
  **Password-reversible** ("lock, don't lose"); the HMAC authenticates the **state**.
- The format **cannot hold** a raw face/audio/image/free-text identifier — identity appears only
  as enrolled household **labels**.
- **Fenced spaces:** a zone with no glyph (listed under `OFF:`) is **unrepresentable** — mum's
  flat gets no glyph, so no line can reference it. Off-limits by absence; the writer rejects any
  claim whose zone ∈ OFF.
- **`nmin` floor** = k-anonymity in decayed days: no single-event line ever renders.
- **Accountable release (DP):** seeded Gaussian noise at **render only** (seed =
  `HKDF(LUKS_key, day, schema)`, so same-day re-render is bit-identical and the CI gate holds, but
  the noise is per-schema and unguessable without the key); an `eps`/`rho` (zCDP) budget in the
  header composes by addition, and sparse-vector accounting charges budget only when a rendered
  value moves beyond its noise band — defeating the average-it-out attack. DP defends the
  LLM-context / trust-screen / backup surface; it is **not** a defense against a coerced unlock.
- **Per-line `°`** → purged on the nightly wipe.

## Build plan (its own milestone, before/with M7 retrieval — stdlib, suite green)
1. `core/remember.py`: add the decayed **`present_days`** mass (~4 lines in `observe()`, guarded by
   the existing `_lastd[key] != today` check at `remember.py:83`), expose it on `Expectation`, bump
   `SNAPSHOT_VERSION 2→3` with a rate-preserving migration. Ship **with** a test that
   `confidence = present_days/_days ∈ [0,1]`. This is the prerequisite — GIST derives from it.
2. `core/gist.py` — **STATE first**: fixed-point integer stat objects (Beta `a_q/b_q`, EW moments
   `W/S1/S2`, slow-Beta, day-mass), decay-then-update via `_factor` with round-half-even applied
   once. No float crosses the serialization boundary. Two-rate traces + change-point scalar here.
3. Typed canonical key `(kind, daytype, daypart, sorted(tokens))` from parsed structure; day-type
   from a deterministic calendar+presence function.
4. Renderer (state→glyph VIEW) + parser (`§S`→state) with **three hard CI gates**: G1 `state→bytes→state`
   identity on a 10k fuzz corpus; G2 render byte-identical across `LANG=C`, `de_DE.UTF-8`, randomized
   `PYTHONHASHSEED`; G3 replay-equivalence (folding twice from persisted state == folding the
   concatenation once) — proves decay-then-update associativity under fixed-point.
5. Symmetric Beta fold (α on fire / β on no-show, gated by day-type); `nmin` floor; MDL bit-budget;
   hysteresis in bits.
6. `RARE` inter-arrival slot (period-matched decay, overdue→MISSING), `DUE` lane, score-ranked
   anomaly reservoir (evict lowest `−log₂ P_pred`).
7. Prose BRIEF renderer (state→English) + `legend.de.tsv` (state→German) — pure, unsigned, ASCII-only signed body.
8. Privacy layer: `nmin`, render-time seeded noise, `eps`/`rho` budget + sparse-vector accounting,
   noisy anomaly class-counts; OFF-fence writer-reject + `°`-drop.
9. `memory.overlay`: an **unsigned, human-owned** directive file (pin / forget / freeze /
   never-learn / rename) the fold reads as high-priority evidence, then re-renders and re-signs —
   correction without breaking the HMAC. The trust screen gets one-tap `[that's me] / [forget] / [lock]`.
10. Wire the fold into `core/ritual.py` (consolidate → write `.ddn` → wipe raw); recall injects the
    BRIEF; the gate/tiles keep reading the in-memory stats.
11. **Per the standing instruction:** ratify this v2 spec in a domain-professional panel before
    building, then ship stdlib-only on `claude/homie-overview-bo4l8v` with the unittest suite green.

## Honest limits (kept — these are real)
- **Transitions only partially modelled.** v2 backs the `>` link with a per-link Beta + lag stat
  (so the gate can ask "did the morning chain break?"), but does **not** convert the whole format
  to a context-keyed Markov graph — that risks the ~850-token convergence target every expert
  called the crown jewel. Promoting transitions to first-class is the right **v3** move if
  chain-anomalies (e.g. the mother's broken-morning-chain welfare case) prove high-value.
- **DP is real but modest and unproven.** The `eps`/`rho` guarantee is only as honest as the
  sensitivity bound and noise scale; the sparse-vector accounting needs empirical validation
  against the real re-render cadence. A determined adversary with the password reads everything.
- **Knobs are principled, not validated.** Two-rate half-lives, change-point threshold, MDL budget,
  `nmin`, the `Beta(.3,4)` prior — all header-pinned (auditable, versioned) but must be tuned
  offline against replayed logs; a 2-person household is a tiny sample.
- **Token cost rises** ~850 → ~2000 for the BRIEF — judged clearly worth it in a 4–8k context, but
  the glyph VIEW remains available as a tighter injection at a known accuracy penalty.
- **Day-type detection is now load-bearing** and inherits whatever blind spots `remember.py`'s
  presence has; a flapping presence sensor could misclassify a day. The symmetric-absence fix and
  `nmin` floor blunt the damage, but it deserves its own reliability test.
