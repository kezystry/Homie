# SCOPE — the Complexity Budget (near-term, binding)

*The master-vision brainstorm invented a "Complexity Budget" (every ADD must name a CUT;
the solo owner must be able to operate every subsystem over an SSH phone session) — and then,
as the [external audit](audits/2026-06-27-brainstorm-external-audit.md) caught, never ran its
own output through it: it adopted **24 inventions** and a **12-phase roadmap** to build a
**six-thing product**. This file is that filter, applied. It is the near-term scope of record;
where it disagrees with the brainstorm's roadmap, this file wins until the owner says otherwise.*

## The rule

1. **Every ADD names a CUT.** No new subsystem ships unless it serves *knows-me* or
   *effortless* **this quarter** AND the solo owner can run it from an SSH phone session.
2. **The next roadmap is authored from the lived-gap log, not the want-map.** Build the six,
   live with them for a month, and let what the owner actually reaches for authorise the 7th.
3. **A "lean" verdict cannot be re-opened into a "cathedral" verdict** without a named
   requirement. (This is how "go lean" became an HMAC codec last time. Not again.)

## KEEP — the true first-light set (the soul, ~80% already built)

This is the *whole* near-term build. Everything else is deferred.

1. **The 3 GIST stat fixes in `remember.py`** + the `nmin` evidence floor — *fixes a live bug*
   (present_days makes confidence exceed 1.0 today), so this jumps the queue.
   - ✅ **FIX-1 (the live bug) + FIX-2 + `nmin` shipped:** `Expectation.prob ∈ [0,1]` (decayed
     present-days at this hour ÷ a GLOBAL active-day denominator), so a stopped routine
     mean-reverts in days and a belief can never be more certain than possible; `firm` gates
     on `NMIN_DAYS`. `rate` is unchanged (the cortex's rarity signal). v2→v3 migration + a
     determinism/round-trip suite (`tests/test_prob.py`).
   - ⏳ **FIX-3 (day-type axis `{wd, we, aw}`) pending** — so a weekend lie-in can't poison the
     weekday schema. Deferred to the next slice (it changes the key shape; kept separate to stay
     reviewable).
2. **The crash-safe nightly fold** (fsync the distilled notes via temp+atomic-rename BEFORE
   rotating the raw log) + a replay/determinism test. ⏳ pending.
3. **The Recap Composer** — a deterministic, template-first morning note (Yesterday / Learned /
   Watching / Tidied), caps enforced *in code* (one Learned, one Watching, honest-empty),
   overflow collapsed lossily, written even with no LLM.
   - ➕ **Day Briefing (owner-added) + the smart organizing system** — a design council
     (`tasks/wetqnn944`) specified ONE typed **Agenda** with two renders (backward recap,
     forward briefing). ✅ **Core shipped:** `core/agenda.py` (typed `AgendaItem` + temporal
     union + pure `AgendaView` with deterministic dedup/merge, fact-beats-routine + HA
     calendar/todo/weather + `beliefs()` adapters), `core/route.py` (honest **offline**
     errand-sequencer — fixed appointments immovable, conflicts flagged, zone-ordinal
     proximity via owner-authored `deploy/zones.toml`; live map-routing is the gated
     `cost()`-seam upgrade), `core/briefing.py` (frozen-cap render: timeline≤3, due≤2,
     route≤1, weather woven, honest-empty, ONE budgeted spoken line). Tests:
     `tests/test_agenda.py`.
   - ✅ **Wired into the daemon:** the clock fires `time.morning` once/day (`morning_hour`);
     the `personal` tile assembles the Agenda from `ctx.beliefs()` (new Context capability) +
     the owner's tasks, builds the Briefing, SPEAKS exactly ONE budgeted line through the
     VoiceGate, and emits the full page on `briefing.ready` (cockpit-visible). Quiet day → it
     stays silent but still renders an honest page. Tests: `tests/test_briefing_wiring.py`.
   - ✅ **Backward recap line:** `core/recap.py` — a pure, capped, honest-empty composer of
     yesterday in one plain line (weekday + presence + ≤1 did + ≤1 correction + quiet-held
     count). Wired above the briefing; renders an honest weekday line today, enriched as the
     nightly fold composes richer facts.
   - ⏳ **Next:** live HA calendar/weather/todo source adapters wired to real entities; the
     nightly fold composing rich recap facts (presence windows, corrections, quiet-held); and
     on-page correction (`memory.overlay` + the three one-tap actions).
4. **The "What Homie Knows" page + `memory.overlay`** — plain rows from the GIST brief, each
   with a confidence word + provenance ("from 32 days" vs "from 3 days"), three one-tap
   actions ([that's me] / [not quite] / [lock]).
   - ✅ **The read-only page shipped:** `core/journal.py` renders `Remember.beliefs()` (firm,
     above-floor beliefs only) as plain sentences with a calibrated confidence WORD + a
     provenance chip; honest-empty before it has learned; never leaks an internal event name.
     Surfaced on the status page (`scripts/status.py --text`, the SSH-from-phone path) in text
     and HTML. Tests in `tests/test_journal.py`.
   - ⏳ **Correction (`memory.overlay` + the three one-tap actions) pending** — the next slice
     (it needs the cockpit write-path, not just a read render).
5. **One-key undo + the Friction Ledger pane** — every act a selectable plain-sentence row,
   reversed in one keystroke via the capability inverse-act path.
6. **Lights + climate autonomy** — silent action *after a clean record*, the owner's chosen
   first solo. (See the simplified AutonomyGate below.)

Plus the one real prerequisite the audit flagged:

- ✅ **`confirm.response` producer SHIPPED** — `core/confirm_responder.py`: a plain chat yes/no
  now answers a pending confirmation (only while one is open + recent, so normal chat is never
  hijacked). Consent is answerable at last; the cockpit shows the question, the trusted core does
  the translation. Tests in `tests/test_confirm.py`. This was the prerequisite without which no
  guarded action could ever actually be approved — now unblocked.

## KEEP THE LAW, not the apparatus

- **The single-waist law + a Coherence CI test** (no tile speaks / egresses / acts except
  through its waist). The *invariant* is worth everything; the eight inventions hung off it
  (AliveState, ToneState, register state machine, the orb, …) are deferrable. Ship the CI test
  and fill the waist with one Voice now; defer the rest.
- **Shipped (Phase A):** the SpeechBudget waist (`core/voice.py` + `core/speech_budget.py`)
  is the first instance of this law — one global governor on `interface.say`, CI-tested that
  raw speech never reaches the cockpit.

## KEEP-BUT-SIMPLER

- **AutonomyGate / TrustLedger:** for **two** actuator classes (lights, climate) do NOT build
  a per-(capability, zone, hour-class) rolling-score auto-promotion engine. Smallest correct
  version: a **hand-set rung per capability** the owner flips from the trust page, plus
  **auto-demote-on-reversal**. Add the rolling score when there is a third and fourth
  capability to promote — not before. (Auto-promotion scoring for two capabilities is the
  scope agent's exact failure mode.)

## Binding resolutions (the four contradictions the audit found)

- **§4.1 — overflow is lossy, not "never dropped."** Over-budget proactive lines defer to a
  *lossy count* in the recap; most die unspoken. A count is honest; a "never dropped" promise
  is not. *(Already corrected in `core/voice.py` / `core/speech_budget.py`.)*
- **§4.2 — ask once, then silent.** The first time a routine is confident, Homie offers once
  ("warm the lights at 7?"); on a yes it acts **silently forever after** (logged, never
  re-announced). The one offer is not a standing announcement.
- **§4.3 — R1 is a constraint, not a tier.** The resting autonomy states are exactly two:
  **R0 (ask)** and **R2 (silent)**. "Announce-then-act" (R1) is a time-boxed, one-capability-
  at-a-time shakedown — never a resting rung, or it becomes running commentary.
- **§4.4 — the signing key is owner-held only; Homie-self-signing is EXCLUDED.** There is no
  safe version of "Homie autonomously authors, signs, and deploys its own code." The most we
  allow: *Homie proposes code → the **owner** signs (key off-box, phone or hardware token) →
  the pipeline deploys signed changes with atomic rollback.* Authorship/blessing stays human.
  This is the load-bearing rail that makes "bold self-improvement" real and not theatre.
  **Owner confirmation wanted on key custody (phone vs hardware token, and a backup signer).**

## DEFERRED / CUT (correct shelves — do not build until a tripwire names them)

GIST codec/HMAC/DP/varint/two-rate/reservoir · three-node mesh transport (seam-as-flag;
run single-brain-in-practice) · autonomous cyber-defense → alert-only · camera intent/
deception reading → north-star only · delights / MusicDJ · QLoRA fine-tuning · remote-wipe /
off-site backup (LUKS + panic-lock/duress-wipe + local & cross-machine backup is the
worst-case baseline) · the rolling-score trust engine · AliveState/orb/ToneState apparatus.

## Known blocker (carried)

Per-person privacy and guest-mode's "stop learning from non-owner" are blocked on the
unpassed reconciler `context` (`zone`/`actor` are `None` in `build_daemon` today — audit
NEW-6). The autonomy *ladder* does NOT need it (its grain is actuator-zone + hour +
capability); only the *person*-attributed rules do. Land that one wire before those.

## Still open (subtractive pass, owner's call)

The audit's "one thing" is to re-run the **three red-teams that failed validation**
(privacy-leak, reliability, **over-complexity**) **against the chair's synthesis** — with an
explicit mandate to *delete* inventions — before building further. Adopting this SCOPE file
already performs most of that subtraction; the dedicated re-run remains available if the owner
wants the adversarial check on reliability and privacy specifically.
