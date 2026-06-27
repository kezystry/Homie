# GIST — Homie's distilled memory format

*Invented by the research council (2026-06-27). Two independent experts converged on the same
design, so this is chaired from their agreement; a full 7-expert synthesis is pending a re-run
(the first run hit a usage cap). Status: **leading design, not yet built.***

## The idea (one line)
Don't store a household's events — store the **sufficient statistics of its recurring
behaviour**, rendered as a tiny, glyph-interned, line-oriented **field-notebook** the local LLM
reads directly and a Python parser round-trips exactly. File: `memory.ddn` (Decayed Day-Note).

## Why it's small, clean, and honest
- **Patterns, not instances.** A 07:11 weekday departure carries ~0 bits once a schema for it
  exists — so we keep only the schema's parameters and spend bits on **surprise** (novelty,
  friction, anomalies). Steady-state memory **converges** to ~50–60 lines (~**850 tokens**)
  whether it covers a month or a year — it consolidates, it doesn't accumulate.
- **Three sufficient statistics per schema** (all decayed with the same half-life as
  `core/remember.py`, so replay is bit-identical):
  - **Beta(α,β)** → confidence `P(happens on a given day)`;
  - **Welford(μ,M2,n)** → learned clock time `@hhmm±mm`;
  - **decayed day-mass** (shared from the existing `PatternModel`) → recency/evidence.
- **Human-inspectable.** It reads like terse field notes, so the "what Homie knows" trust
  screen renders the decrypted file verbatim — what the owner reads *is* exactly what persists.

## Grammar (v1, line-oriented UTF-8, deterministic ordering, version-pinned)
```
codex   := header legend off? section+ anomalies? sig
header  := "§GIST v1 home=<id8> day=<YYYY-MM-DD> n=<days> hl=30d"
legend  := "@Z " zone+   NL "@T " topic+        ; interning: names → 1-char glyphs
off     := "OFF: " name+                        ; spaces Homie must NOT represent (mum's flat)
section := "#" daypart NL line+                 ; dayparts: dawn,am,mid,pm,eve,night (6 bins)
line    := schema " ~" conf " @" time NL        ; e.g.  Pk>Pb>Pf ~.90 @0712±03
schema  := glyphseq                             ; zone/topic glyphs + ops (the behavioural gist)
op-vocab: ">" then  "/" or  "x" off  "+" on  "?" novel  "!" learned-rule  "*" anomaly-ref  "°" sensitive
anomaly := "#! " (date ":" glyphseq)0..7        ; bounded ring, newest-first; recur≥k ⇒ promote to schema
sig     := "§hmac=<b64-12>"                      ; integrity over the body (key sealed in LUKS)
```
`!xk ~.74 @1903±21` = "rule learned: lights-off kitchen, ~74% of evenings, ~19:03 ±21m".
A `°`-tagged line is **sensitive** → dropped on the nightly wipe, never persisted.

## Worked example (two nights)
**Night 1** (kitchen→bath→door ~07:11; kitchen-off 19:02 no correction; upstairs-on 22:51 then
resident reversal; unknown face at door 14:00):
```
§GIST v1 home=a3f1c0d9 day=2026-06-27 n=1 hl=30d
@Z k=kitchen b=bath f=front-door u=upstairs
@T P=presence A=lightAct C=correction D=door
OFF: mum-flat
#am
Pk>Pb>Pf ~.50 @0711±00
#eve
!Axk ~.50 @1902±00
Au*C ~.50 @2251±00      ; friction: resident reversed lights-on upstairs
#! 2026-06-27:?Df       ; unknown at front-door 14:00
§hmac=Qx8r2Vd1mK0p
```
**Night 2** (same morning ~07:13; kitchen-off ~19:05 again; upstairs-on 22:30 **no** reversal;
no unknown) folds in and re-renders:
```
#am
Pk>Pb>Pf ~.90 @0712±03
#eve
!Axk ~.90 @1903±02      ; rule firming
Pu ~.66 @2235±07        ; the one-off reversal decayed away — learned it wasn't a rule
```

## Nightly distill algorithm (the "sleep" fold; stdlib, deterministic)
1. **Bin** today's *normalized* events into 6 dayparts + candidate schemas (short-window
   sequences/co-occurrences; reuse presence/lightAct/correction topics).
2. **Match** each candidate to an existing line (exact glyphseq key) or open a candidate.
3. **Decay then update** the sufficient stats (Beta α/β; Welford μ,M2; day-mass) using the
   *same* exponential half-life as `PatternModel` — decay **before** update so replay is exact.
4. **Promote/demote** with **hysteresis** (separate birth/death thresholds, k-day clearance) so
   lines don't flap; friction lines get a **short** half-life (one-off corrections don't calcify).
5. **Prune** schemas below evidence ε or confidence×support τ (MDL: a line earns its place only
   if it shortens total description length). Cap ≤~12 schemas/daypart; anomaly ring fixed 7.
6. **Re-render** in deterministic order (daypart, then glyphseq lexicographic) with **pinned
   formatting** (fixed decimals, sorted keys, C locale) and **re-sign** (HMAC). Drop `°` lines.
7. Throw away the raw log. Only the `.ddn` survives.

## Recall (how it's used)
- Default: decrypt in memory, inject the whole `.ddn` verbatim as a `MEMORY:` system block,
  preceded by a 4-line decoder key the LLM reads literally. Small enough to fit whole — **no
  embeddings, no vector DB**. For hot paths, pre-filter to lines matching the live event's
  zone/time + all rules + recent anomalies.
- A **deterministic Python reader** parses the same grammar back into the stat objects, so the
  **novelty-gate and tiles query confidence/expected-time without the LLM** — the round-trip
  guarantees the human string and machine state never diverge. (Derive rates from `remember.py`'s
  snapshot in the same ritual pass — never recompute independently, or the two drift.)

## Privacy & encryption (structural, not bolted on)
- At rest: key from the owner's password (**Argon2id/scrypt KDF → AES-GCM**), sealed in the LUKS
  volume. **Password-reversible** ("lock, don't lose"); an HMAC line authenticates integrity.
- The format **cannot hold** a raw face/audio/image/free-text identifier — identity appears only
  as enrolled household **labels** (or an opaque token), matching the identity ladder.
- **Fenced spaces:** a zone absent from `@Z` (listed under `OFF:`) is unrepresentable — **mum's
  flat gets no glyph, so no line can reference it**. Off-limits by absence, not by filtering;
  the writer rejects any claim whose zone ∈ OFF.
- **Per-line `°` sensitivity** → purged on the nightly wipe. Minimal forensic surface: the codex
  reveals routines, never recordings.

## Build plan (when we get here — its own milestone, before/with M7 retrieval)
1. `core/gist.py`: the stat objects (Beta, Welford, decayed day-mass) + a `Schema` dataclass.
2. Renderer + parser with a **round-trip unit test as a hard gate** (byte-stable re-render).
3. Nightly fold wired into `core/ritual.py` (consolidate → write `.ddn` → wipe raw).
4. Recall: inject into the cortex context; parser feeds the novelty-gate/tiles.
5. Encryption + `OFF:` fence + `°` drop + HMAC; the "what Homie knows" screen renders it.
6. Tune half-lives/priors offline against replayed logs (put them in the header — versioned).

## Honest limits (kept)
Chaotic/irregular households yield low-confidence flapping lines; moved routines lag ~one
half-life (~30d) to re-converge; rare-but-important events (monthly bins/carer) can decay
between occurrences — need a pinned "rare-but-watch" slot; day-type (weekday/weekend/away)
must be modelled or a weekend lie-in poisons the weekday wake schema; round-trip/HMAC is
brittle without pinned formatting (hence the CI gate). None are blockers; all are designed-for.
