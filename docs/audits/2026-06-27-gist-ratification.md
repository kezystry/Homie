# GIST v2 — build-ratification verdict (2026-06-27)

*A 7-agent ratification panel (determinism, crypto/DP, Bayesian, edge-systems, HCI/trust,
scope-hawk + a synthesis chair) reviewed `docs/MEMORY-GIST.md` **against the real code** before
any GIST code was written. This is the panel's recorded verdict; the binding amendments are
folded into the spec's "⚖️ Ratification status" callout and "Ratified build order" section.*

## Verdict: **ratified-with-amendments**

The load-bearing core is sound and buildable on this codebase: the STATE/VIEW inversion, the
exponentially-weighted time moments `(W,S1,S2)` replacing the (invalid-under-decay) Welford `M2`,
the absence-counted Beta, and the day-type axis `{wd,we,aw}` are mutually consistent. But the
spec shipped two **false guarantees** and several **silent determinism bombs** that had to be
fixed in the document first, because the determinism CI gates get written first and would be
built on the contradictions.

## Must-fix before any build (all folded into the spec, v2.1)

1. **Delete the false "derives, never recomputes, can't drift" guarantee.** Verified against
   `remember.py:40-145`: it carries no Beta, no `present_days`, no EW moments, no day-type axis,
   no transition stats — so GIST physically cannot derive them from `snapshot()`. GIST is an
   **independent integer estimator** over the same raw events, sharing only the 30d half-life
   constant. Replace equality with a **bounded-tolerance reconciliation test**.
2. **`(W,S1,S2)` time origin must be local-midnight-minutes [0,1439], not epoch-seconds** —
   epoch-seconds makes `σ²=S2/W−μ²` a precision-dead subtraction of ~1e21 integers.
3. **Firmness must be integer `bit_length`, not `math.log2`** — it sits in the signed body; a
   libm float there flips ±1 at power-of-two boundaries across hosts and breaks the HMAC.
4. **Redefine G3 as replay-idempotence, NOT associativity.** "Fold A then B == fold A+B once" is
   false under once-per-night rounding (two roundings ≠ one).
5. **Pin the integer decay operator** — `2^(-1/30)` is irrational; specify a fixed-precision
   `decimal` context with `ROUND_HALF_EVEN` (or pure-int banker's rounding with `P_num/P_den`).
6. **Forbid seeding GIST integer state from `remember.py`'s `round(x,6)` snapshot floats**
   (`remember.py:139-140`) — that is the exact float-crossing hazard the spec names.
7. **Fix the cipher contradiction** — neither Argon2id nor AES-GCM is in the Python stdlib.
   At-rest = LUKS/dm-crypt; KDF = `hashlib.scrypt`; HKDF-SHA256 hand-rolled (RFC 5869); in-Python
   crypto = HMAC-SHA256 over the canonical integer STATE bytes only.
8. **Pin the `§S` varint-delta reference frame** (canonical-key total order, missing-prior ⇒
   delta-vs-zero, fixed field order, varint convention) and the canonical-Huffman tie-break as
   **ASCII-bytewise** (or G2 breaks under `de_DE`).
9. **OFF-fence at perception ingest**, not only at render — mum-flat events must never enter
   `remember.model`, or the clean in-memory stats the gate reads contain off-limits data.
10. **Wire the fold into `ritual.consolidate()`'s always-run block** before `bus.compact()` and
    before the abort gate; fsync `.ddn` (temp + atomic rename) before rotating raw, or an active
    night skips the raw wipe and raw accumulates unbounded.

## Deferred out of the first build (forward-compatible, not built yet)

All DP machinery (eps/rho is *advisory noise*, not a guarantee, until a sensitivity table
exists), two-rate consolidation + change-point, the RARE/DUE/anomaly reservoir, transition
stats, the German catalog, `memory.overlay`, and any in-Python AEAD. Build the deterministic
integer core green first.

## Build order (the panel's slices — also in the spec)

1. `remember.py` `present_days` (no new file). **⚠ has an open design question — see handoff.**
2. `core/gist.py` integer STATE in isolation + **G1** (`state→bytes→state`). ← **built this session.**
3. `core/gist.py` `§S` varint-delta codec + **G3** (replay-idempotence).
4. Canonical key + day-type + renderer/parser + **G2** (locale/hashseed byte-identity).
5. Absence-counted Beta fold + `nmin` floor + MDL prune + OFF-fence.
6. Prose BRIEF renderer (English).
7. Wire into `ritual.consolidate()` + reconciliation test.
8. HMAC-SHA256 over the integer STATE.
9. Later: scrypt KDF + HKDF + panic-wipe → DP (advisory) → two-rate → RARE/DUE → transitions →
   German → `memory.overlay`.

## Guardrails (non-negotiable every slice)

Determinism is a CI gate (G1/G2/G3, G3 = replay-idempotence). No float crosses the `§S`
boundary. OFF-fence by absence AND at ingest. No data egress. Encryption/reversibility/panic-wipe
coherence (LUKS + HMAC + scrypt re-derive, not recover-wiped-data). Suite stays green every
slice. The gate/tiles read `remember.py`, never the `.ddn`. The raw-event wipe runs before the
abort gate so it is never skipped on an active night.
