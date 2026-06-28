# External Audit of the Master-Vision Brainstorm (independent Claude, 2026-06-27)

*Audit of `docs/audits/2026-06-27-brainstorm-for-review.md` — the 18-agent wave (13 visionaries
→ 1 surviving red-team → 1 chair). I read it in full against the shipped code (M0–M6 + HA adapter
+ GIST integer core, 368 green, all of which I've audited directly), the banked decisions, and the
interview spine. The document asks four things: is the synthesis faithful, are the inventions
buildable, do the guardrails neutralise the four worries, and what did the chair over-reach or
drop. This answers those, then runs the keep/cut filter.*

---

## 1. Verdict

**The chair did well and largely sided with discipline.** The cuts are the right cuts: the GIST
codec/HMAC/DP cathedral is shelved (vindicating the two prior reviews it explicitly cites — the
ratification and my GIST rating — that a 21-agent council had overruled), self-evolution is split
into free-data-drift vs gated-code, "muzzle before mouths" correctly front-loads the unbuilt
speech budget, and camera intent-reading stays a horizon. The single best structural idea in the
whole document — **the single-waist law** (one Voice / AliveState / SpeechBudget / EgressGuard /
AutonomyGate, CI-enforced so no tile speaks/egresses/acts except through its waist) — is genuinely
the anti-over-complexity invariant the system needs, and it's buildable on the shipped graph.

**But the synthesis re-committed the exact ratchet it diagnosed.** Scope-discipline agent 3.13
states the soul is six things: *morning note + what-I-know page + one-key undo + lights/climate
autonomy + stranger-flag + alert-only guardian.* The chair then adopted **24 inventions** and
sequenced a **12-phase (A–L) roadmap** — and never ran its own output through the **Complexity
Budget it invented** (invention #24). The document produces a rule that "every ADD must name a
CUT," lists 24 ADDs, and names cuts only for the things it was already cutting. The brainstorm
machinery became the complexity engine *again*, one level up — which is 3.13's own central thesis,
now demonstrated by the artifact containing it. **1.4M tokens and 18 agents to plan a six-thing
product.** That process cost is itself the strongest evidence for 3.13.

So: trust the cuts, trust the single-waist law, and then **cut the synthesis by another half**
before building — most of the 24 are correct *eventually* and wrong *as a near-term plan*.

---

## 2. The filter

| Bucket | Items | Note |
|--------|-------|------|
| **KEEP — the true first-light set** | The 3 GIST stat fixes in `remember.py` (present_days, β-on-no-show, day-type) + `nmin`; the crash-safe nightly fold (fsync-before-rotate); the Recap Composer (template-first, capped in code); the "What Homie Knows" page + `memory.overlay`; one-key undo + Friction Ledger; the **confirm.response producer**; lights+climate silent-after-clean-record. | This is 3.13's six-thing soul plus the one real prerequisite (confirm producer). Everything here is buildable on shipped seams and most fixes a verified bug. Build *only* this before the month of living-with-it. |
| **KEEP THE LAW, not the apparatus** | The single-waist law + the Coherence CI test (no tile speaks/egresses/acts directly). | The *invariant* is worth everything; the eight inventions hung off it (AliveState, ToneState, register state machine, etc.) are mostly deferrable. Ship the CI test that enforces the waist now; fill the waist with one Voice; defer the rest. |
| **KEEP-BUT-SIMPLER (over-built for the deployment)** | AutonomyGate + TrustLedger as a *per-(capability,zone,hour-class) rolling-score auto-promotion engine*. | For **two** actuator classes (lights, climate) you don't need a measured trust-scoring ladder. Smallest version: a hand-set rung per capability the owner flips from the trust page, plus auto-demote-on-reversal. The rolling-score auto-promotion is the scope agent's exact failure mode — sophistication that hasn't earned its place for two capabilities. Add the score when there's a third and fourth capability to promote. |
| **ALREADY-HAVE (don't rebuild)** | HA reconnect + heartbeat + loud in-flight-drive failure (the wave correctly notes this — it's the NEW-1/NEW-2 fix already landed); the DurabilityLog crash-safety; Supervisor quarantine/reload; the M5 capability gate; the M3 wake budget. | The wave is accurate about built-vs-unbuilt — good. The one trap: agents lean on "re-point the M3 budget at speech" — the red-team is right, that's a **new** component, not a re-use (M3 caps GPU wakes, not utterances). |
| **FIXES A REAL BUG (maps to my prior audits — prioritise these)** | The 3 stat fixes (the present_days `rate>1.0` bug is live); the confirm.response producer (N10, consent is a 30s dead-end today); the signature-gate + captured-good-rollback for self-update (NEW-3); the EgressGuard (the real leak surface post single-node collapse). | These aren't features, they're corrections. They should jump the queue over any net-new mouth. |
| **CORRECTLY CUT/DEFERRED (the chair got these right)** | The GIST codec/HMAC/DP/varint/two-rate/reservoir; three-node mesh transport (seam-as-flag); autonomous cyber-defense → alert-only; camera intent-reading → north-star; delights/MusicDJ; QLoRA; remote-wipe/off-site backup. | No notes. These are the right shelves and the reasoning is sound. |
| **CONTRADICTIONS (logical holes to resolve before building)** | See §4. | Three of these are load-bearing and one is a safety illusion. |

---

## 3. The four audit asks, answered

**(a) Is the synthesis faithful to the owner's wishes?** *Mostly yes.* The pillars and cuts trace
to the interview/decisions, and the chair is honest about what's *offered* vs *decided* (the
secret-name/anti-name primitive and the SpeechBudget default are correctly punted to the
owner-questions section, not assumed). The one soft over-reach: the document repeatedly frames a
**nightly automatic self-rewrite of its own code** as faithful to "bold, always-latest" — but the
interview's round 17 is tagged *"ambitious; note the safety tension,"* i.e. flagged, not ratified.
Treating a flagged tension as a settled wish is the place the chair leans hardest past the record.

**(b) Are the inventions buildable on the shipped graph?** *The first-light set, yes — cleanly.*
The AutonomyGate inserts at the same Act chokepoint as the capability check; the EgressGuard mirrors
the positive-schema guard; the Recap renders from the (corrected) Remember model; undo reuses the
capability inverse-act path. Two buildability caveats: **guest-mode's "stop learning from non-owner"
and per-person privacy are blocked on the still-unpassed reconciler `context`** (my NEW-6 — `zone`/
`actor` are `None` in `build_daemon` today), so any "don't learn while X is present" rule can't be
honoured until that one wire lands. The autonomy *ladder* itself does **not** need it (its grain is
actuator-zone + hour + capability, all available) — only the *person*-attributed parts do.

**(c) Do the guardrails actually neutralise the four worries?** *Two yes, two partial.*
- **Privacy** — yes, and well-designed: one EgressGuard chokepoint + OS deny-by-default firewall +
  a Sealed-Network report *generated from the same allowlist it enforces* (so claim can't drift —
  the exact fix for the C6 docstring-lie). Solid, mechanical.
- **Nag** — yes *if* the SpeechBudget ships first (the red-team's whole correct point), but the
  mechanism has an internal contradiction (§4.1).
- **Reliability** — **partial and under-audited.** The dedicated reliability red-team *returned
  nothing* (provenance caveat). The degrade-and-announce + MemoryBundle + restore-drill are the
  right shape, but "the home is never dead" is asserted via visionary `risks` fields, not stress-
  tested by an adversary. This worry needs its red-team re-run.
- **Over-complexity** — **the weakest, and the irony is structural.** The over-complexity red-team
  *also returned nothing*, so the only force resisting sprawl was a single scope agent arguing
  inside a brainstorm — and it lost (24 inventions adopted). The guardrail against over-complexity
  was itself defeated by the brainstorm's over-complexity.

**(d) What did the chair drop or over-reach on?**
- **Over-reach:** adopting all 24 inventions instead of cutting to 3.13's six; treating the
  round-17 self-rewrite tension as settled; the rolling-score trust ladder for two capabilities.
- **Dropped/under-weighted:** the **owner-key-custody question** is the load-bearing one and it's
  buried in an open-question bullet (§4.4); the **"deferred-never-dropped" vs "lossy recap"**
  contradiction (§4.1) is left unresolved; and 3 of 4 red-teams are simply missing, so the
  synthesis is one-eyed on three of the four worries.

---

## 4. The contradictions to resolve before building

**4.1 — "Deferred, never dropped" vs the lossy capped recap.** The SpeechBudget says the (N+1)th
proactive line *"defers to the recap, never dropped."* The Recap Composer says the recap is hard-
capped in code (one Learned, one Watching) with *lossy* overflow (`+6 minor things`). These cannot
both hold: deferred speech has nowhere to land if the recap is also capped-and-lossy. **Resolution:**
drop the "never dropped" comfort — most proactive thoughts must simply *die unspoken*, which is the
correct behaviour for a silent-by-default home. A thought worth saying tomorrow wasn't worth saying;
a count is honest, "deferred" is not.

**4.2 — "Ask-once-then-act" (banked) vs "anticipation is silent magic, never announced" (adopted
cut).** The M7 decision *requires* an offer ("want me to warm the lights at 7?") before the first
autonomous act. The cut-list says *"CUT anticipation announcements … anticipation is silent magic,
never a live interruption."* Read literally these collide — the offer *is* an announcement.
**Resolution:** one offer, then silent. The first time a routine is confident, Homie asks once; on
a yes it acts silently forever after (logged, never re-announced). State this explicitly or the
builder will pick one and break the other.

**4.3 — R1 "announce-then-act" as transitional-only vs a resting tier.** The autonomy ladder lists
R1 (announce+undo) as a rung, but both the chair and red-team then say R1 must be *transitional
only, one capability at a time, never resting.* If R1 is never a resting state, it's not a rung —
it's a brief promotion artifact. **Resolution:** the resting states are exactly two — R0 (ask) and
R2 (silent); R1 is a 1-capability, time-boxed shakedown. Encode that as a constraint, not a tier,
or the ladder reads as three resting rungs and produces running commentary.

**4.4 — The self-signing-key illusion (the most important one).** This is where "bold self-
improvement inside strong rails" is either real or theatre, and the document blurs it. Agent 3.9
permits *"a Homie self-signing key the owner provisioned."* If Homie can sign its own code, the
signature gate — the entire NEW-3 defence — collapses: Homie authors, signs, and deploys its own
changes, and "signed" certifies nothing. **There is no safe version of "Homie autonomously authors,
signs, and deploys its own code nightly."** The most you can safely have is: *Homie proposes code,
the **owner** signs (key off-box, on a phone or hardware token), the pipeline deploys signed changes
with atomic rollback.* That still *feels* bold (always-latest, automatic deploy of approved changes)
but authorship/blessing stays human — which is what scope-agent 3.13 argued and the chair did not
fully adopt. **Make it binding: the signing key is owner-held only; Homie-self-signing is
excluded.** Otherwise the round-17 tension is "resolved" by an illusion.

---

## 5. The one thing

**Cut the 24 to the six, ship them, and run the three missing red-teams against the synthesis —
not the visionaries — before anything else.** The chair's instincts were right and its cuts were
right, but a brainstorm cannot be its own scope discipline: the artifact that contains a Complexity
Budget violated it. The highest-value next move is not another generative pass — it's a *subtractive*
one: re-run the privacy-leak, **over-complexity**, and reliability red-teams (the three that failed
validation) against the chair's synthesis, with an explicit mandate to delete inventions, and hold
the owner-key-custody line in §4.4. The soul is six things and ~80% built. The danger was never a
missing feature; it's the 24th one. Build the six, live with them for the month the chair correctly
prescribed, and let the lived-gap log — not the next wave — authorise the 7th.
