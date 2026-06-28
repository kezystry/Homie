# The Gerüst — Homie's binding charter

**This is the constitution. Everything here is a REQUIREMENT, not an aspiration.**

- A **law** (Parts I–II, IV) must be *true at all times*. A change that breaks one is the change
  that is wrong — revert it.
- A **must-exist feature** (Part III) must either already work or stay on the committed roadmap.
  It may be *sequenced* later, but it can **never be silently cut, weakened, or compromised.**
  Removing or watering one down requires the owner's explicit say-so, written here.

Each item says **what**, **why it can't be compromised**, and **where it lives** so it is checked,
not just believed. Status tags: ✅ built · 🔜 committed-next · 🅿️ committed-deferred · 🧱 needs hardware.

---

## I · Inviolable laws (never traded away, for any feature or convenience)

1. **The model is untrusted; safety is the architecture's, not the model's.** Every effect is
   mediated by tiles + a capability gate + a priority bus, so what the brain *says* can never
   become an unauthorised action. *This is what makes an uncensored local model safe.* ✅
   — `core/capability.py`, `core/act.py`, `core/tile.py`.
2. **Nothing leaves the machines without an asked, logged, owner-aware decision.** Local-first,
   no cloud, no telemetry. The one sanctioned exception is an emergency image to police/display,
   EMERGENCY-rung-only and logged. ✅ policy · 🅿️ the single `EgressGuard` chokepoint enforces it.
3. **Never go online without asking** (until trusted), and then only safely (allowlist; VPN/Tor
   for sensitive). Pre-approved: weather, card-prices, lookups. ✅ rule · 🅿️ enforced with #2.
4. **Mum's flat is OFF-LIMITS and unrepresentable by construction.** Only the front door + the
   owner's own entrance are ever watched; an off-limits zone can produce no event, render, or
   clip. ✅ (design rule) — positive zone-allowlist at perception ingest.
5. **Owner-only credentials are never held in plaintext.** The **secret name is a password** —
   hash-verified, never stored, logged, or asked for. Encryption only the owner can unlock; a
   reversible **panic-lock** and a separate irreversible **duress-wipe**. ✅ rule — `docs/SECURITY.md`.
6. **Raw faces/audio and identity vectors never cross a wire and are never stored as identifiers.**
   Security *clips/photos* may be stored locally (encrypted); faceprints/voiceprints stay on-device.
   🅿️ — the positive-schema privacy guard.
7. **The four nevers.** Never **deceive**, never **manipulate**, never **put anyone above the
   owner**, never **hide what it's doing.** Honesty is fixed; only warmth is free. 🔜 a signed,
   immutable CHARTER module the personality cannot edit.
8. **Always obey the owner; a real character comes later.** A hard obedience floor independent of
   any learned tone. Mum's safety may override only in a genuine emergency. ✅ stance.

## II · Architecture invariants (must always hold)

9. **One keystone wiring** — `build_daemon()` assembles the whole graph; production, demo, and
   tests drive the *same* wiring. A green suite proves the *shipped* daemon works. ✅ `core/daemon.py`.
10. **Capability-gated actuation + the priority floor** safety > security > automation >
    convenience > ambient. A forged command is refused, even over the subprocess wire. ✅
    `core/capability.py`, `core/bus.py`.
11. **The single-waist law** — every owner-facing channel has exactly ONE governor; tiles emit
    *facts*, the waist renders. N features, one voice — no tile grows its own mouth or egress. ✅
    (speech) `core/voice.py`; the pattern repeats for egress + actuation.
12. **Determinism where it counts** — memory, wake budget, and the voice are event-clocked
    (never wall-clock/randomness); replaying a log reproduces bit-identical state. ✅
    `core/remember.py`, `core/wake_ledger.py`, `core/speech_budget.py`.
13. **Tested code IS the shipped code.** A milestone is "done" only when its named acceptance
    test passes. ✅ `tests/`.

## III · Must-exist features (these ARE Homie — built or committed, never cut)

*The owner asked for "everything" — guardian + companion + butler + second brain. These are the
capabilities that define it. Sequencing is the roadmap's job; existence is non-negotiable.*

**Knows-me (the soul):**
14. A **pattern-of-life model** that knows his routines, honestly (true probabilities, fades when
    a habit stops). ✅
15. The **"What Homie Knows" page** — everything it believes, in plain words, correctable. ✅
    (read) · 🔜 (one-tap correct).
16. The **morning surface** — a **recap** (yesterday) + a **day briefing** (today: agenda, due
    items, the sensible errand order, weather woven), capped so it never floods. ✅.
17. A **self-pacing voice** that learns how chatty to be and is never a nag; + an everyday mute. ✅.
18. **Adaptive personality** (warmth/humour/verbosity) as render-time only — zero authority over
    what it knows or does. 🅿️.

**The hands & the guardian:**
19. **Drives the real home** through Home Assistant (lights ✅ live; climate, scenes, more 🔜🧱).
20. **Guardian**: intrusion **full-deterrence** (lights+alarm+record+alert+stage-police), **hazard
    sensors** (smoke/CO/water/gas), **emergency calling** (confirm-first; auto only on no-response),
    **active network defense** (alert-first → earned teeth). 🅿️🧱.
21. **Presence/stranger awareness** at the two watched entrances; quiet-log, speak-only-if-odd. 🧱.

**Memory & control:**
22. **Distilled cross-day memory** (live day = full; next day = GIST) reaching years as wisdom; a
    nightly "what changed/improved" note. 🔜🅿️.
23. **Pin & forget** — make something stick forever or erase it everywhere (backups, logs, summaries). 🔜.
24. **Full timeline undo** + a **real yes/no confirm** — every act reversible in one keystroke. 🔜 (Phase D).
25. **Master controls** — a full **off switch**, a one-tap **guest mode**, and **per-person
    privacy** (control what's recorded/visible per person). 🅿️.

**Autonomy & trust:**
26. The **earned-autonomy ladder** — tight leash → trusted solo (lights+climate first); **money &
    irreversible actions always ask**, permanently. 🔜.

**Resilience & renewal:**
27. **The home is never dead** — basic functions + memory survive any one machine dying; told
    immediately; auto-heal + rollback; layered encrypted backups. ◑ (degrade/heal partial) → 🅿️.
28. **Nightly self-renewal** — tidy + heal + a **gated self-upgrade** (owner-signed → sandbox →
    atomic switch → auto-rollback → changelog). Bold but never self-grants device power or egress;
    **signing key owner-held only.** 🅿️ (M11).

**Reach, voice, business:**
29. **Voice** — wake-word ("Homie") + best local voice; + all other inputs (screen, type, "it just
    acts"). 🅿️🧱 (HA Assist is the near-term path).
30. **Reach the owner** — phone notifications + remote access (HA Companion app ✅ today; a
    Homie-native channel later). ◑.
31. **Butler / second brain** — life-admin (parcels, bills, appointments, notes), and **KartenWerk**
    (inventory, pricing, orders/shipping, grading, deal-spotting) via an **Outbox** (draft→approve;
    buying/selling always approved). 🅿️.

**The north star:**
32. **Camera human-reading** — presence → mood → distress, **each rung gated and proven before the
    next**; deception/intent is a named horizon, never promised on a date. 🅿️🧱.

## IV · Behavioral laws

33. **Learns by friction** — silence = approval, a correction = a lesson. No rules to write. ✅.
34. **Honest by construction** — never overclaim, honest-empty, a coincidence is never a fact. ✅.
35. **Silent by default; it learns how much to speak.** No hand-set cap. ✅.
36. **Reversibility beats correctness** — forgiving, undoable, trust earned slowly and lost on one
    correction. 🔜.
37. **Effortlessness is the felt goal**, and **reliability is the #1 trust earner.** ✅ stance.

## V · The guardrails & method (how we keep the above true)

38. **Guard hardest against the four worries** — a **privacy leak**, **unreliability**, **becoming a
    nag**, **over-complexity.** Every design is checked against all four.
39. **Build the soul first; lived gaps authorise the rest.** Every ADD names a CUT. — `docs/SCOPE.md`.
40. **Big decisions go through a council** + a chaired synthesis.

---

*The roadmap (`docs/SCOPE.md`, `docs/PROGRESS.md`) says **what to build next**; this charter says
**what must remain true and must exist** while building it. When the two conflict, this wins.*
