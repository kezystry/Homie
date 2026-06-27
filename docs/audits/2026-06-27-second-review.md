# Homie — Second External Review (independent Claude, 2026-06-27)

*An independent Claude cloned `kezystry/Homie@main` (the ORIGINAL codebase, 225 tests —
before this branch's M0–M2 work), read the spine in full, ran the suite green on Python
3.12, and verified every claim at file:line. It concurs with the first audit, corrects it
in three places, and adds eleven findings plus a brainstorm. Recorded here verbatim-faithful;
the milestone mapping is in MASTERPLAN's "Second-review addendum".*

## Verdict
Concurs with the torso-with-no-breath framing and sharpens it: several pillars are built,
tested, then **never wired into `scripts/run.py`** — tested-but-unreached. Adds a class the
first audit missed: **Homie has no notion of time passing** — purely event-reactive, no
scheduler/tick/timer at the tile layer, so every "after N minutes / at dusk" behavior
depends on unrelated future events (and in a truly empty room the auto-off never fires).

## Corrections to the first audit
1. **Compaction IS built and wired** (`run.py` `_housekeep` → `bus.maybe_compact`; boot folds
   only uncovered segments). Strike it from the gap list.
2. **OS default posture is hardened**; the risk is the **opt-in `ssh.nix`** (password SSH +
   `homie` in wheel + LAN:22), not the base config. Real for this deployment, but flagged.
3. The suite is genuinely green at 225 on Python 3.12 (newer than the pinned 3.11).

## New findings (not in the first audit)
- **N1 [High] No scheduler / no notion of time passing.** Lighting auto-off only re-checks
  elapsed time when another event for the zone arrives; in an empty room the light never
  turns off. Structural — touches auto-off, security cool-downs, dusk, the whole "ambient"
  premise. Fix = a `clock` producer emitting `tick.*` + a `timer.set/fired` seam.
- **N2 [High] Self-healing unwired in production.** `supervisor.reload()` lives only in
  `consolidate()`, which `run.py` never calls (it ran the lesser inline `_housekeep`); and
  even there the heal is fenced behind abort gates. A quarantined tile never recovers until
  a full restart. *(Closed on this branch: M1's `build_daemon` wires `consolidate()` into
  `_housekeep`; decoupling heal from the disruptive-tail gates remains.)*
- **N3 [High] `emit` bypass also defeats SubprocessChannel containment, and emit-driven acts
  are invisible to friction.** `_forward` routes a child's emit through `ctx.emit`; only
  `ctx.act` writes the friction ledger, so an emit-driven act is unauthorized AND
  unattributable (a reversal finds no ledger entry → spurious `note_manual`). The capability
  fix must be **topic-scoped**: `security.alert` emits legitimately; only `actuator.requested`
  from `emit` needs the token.
- **N4 [Med] Hardcoded 18:00 dusk is wrong for the latitude.** At Kiel (~54.3°N) civil dusk
  is ~22:00 in June, ~16:00 in December; the "only when dark" gate is decorative half the
  year. Fix = solar dusk/dawn from lat/long (stdlib).
- **N5 [Med] Friction mislearns from dimming transitions.** `CommandLog.take_echo` matches
  exact canonical value; a bulb's intermediate ramp echoes match nothing → fall through to
  `note_manual`/`note_reversal`, manufacturing phantom friction. Fix = tolerance band /
  suppress non-terminal transitions / reconcile only on settled state.
- **N6 [Med] Friction path uses wall-clock, breaking replay determinism.** `reconcile`,
  `ctx.act`'s ledger, and `Act.confirm` use `time.time()`, a different clock domain than
  Remember's injected-`event.ts` law. Thread an injected/event-derived clock through friction.
- **N7 [Med] Three notions of "hour" can disagree.** Remember buckets in the `HOMIE_TZ`-pinned
  zone; Lighting/`learn.py` use host-local `datetime.fromtimestamp`; `run.py`/the unit never
  set `HOMIE_TZ`. Centralize hour-of-day on one pinned zone; set `HOMIE_TZ` in the unit.
- **N8 [Med] Mesh bridge is single-hop, contradicting the star topology.** `_on_local`
  forwards only events whose origin is None/self; a relayed remote event keeps the remote
  origin, so an anchor won't forward a Pi event onward to the desktop. As drawn (Pi→anchor→
  desktop) it doesn't work; as required (full mesh) it's the complexity to avoid for 3 nodes.
- **N9 [Med] The opt-in SSH module is a LAN-reachable, password-guessable path to a wheel
  account that owns the presence log, and the box autologins to an unlocked console.** Fix is
  bigger than flipping a flag: split the data-owning daemon user from the login/maintenance
  user; put SSH behind WireGuard/Tailscale, not open LAN:22.
- **N10 [Med] Consent is a guaranteed 30s dead-end.** `Consent.request` awaits
  `confirm.response`, which nothing produces (gesture/voice are stubs). Any `ctx.confirm()`
  waits 30s then fails safe to "don't act". Needs a response producer (even a cockpit Y/N).
- **N11 [Low–Med] Out-of-order events corrupt the decayed mass.** A late event (ts < last) is
  added at full weight with no decay; only happens across a mesh with no global clock. Another
  cost the single-box design avoids for free.
- **Hygiene confirmed:** `act_map.toml` `light.living_room` vs tile `light.living`;
  `scripts/ritual.sh` doesn't exist; `interface.friction_from` remark channel has no producer.
- **Chat bug:** the cortex chat path sends only `{"chat": text}` (no Remember context), so it
  can't answer "is anyone home?". *(On this branch M0's AnchorVoice answers pattern-of-life
  from Remember on the anchor; the cortex path still needs context threaded in.)*

## Brainstorm (16 ideas) — highlights
1. A "golden days" replay corpus (normal/weekend/vacation-empty/3am-intrusion/guest) reused
   for the e2e test, a `--dry-run`, and wake-budget regression. *(Partly shipped: M2's
   `core/scenarios.py`.)*
2. **Time as a first-class event** — the `clock`/`tick` + `timer` seam (fixes N1).
3. Solar dusk/dawn from lat/long (fixes N4).
4. The reversal gets a reason captured in the moment ("too bright / wrong time") → structured
   preference store, not just an hour.
5. Confidence-gated autonomy using `Expectation.days` (act where confident, ask where low,
   observe where novel) — makes the cold-start month tolerable.
6. Rhythm fingerprinting — a tiny Markov model of room transitions/dwell; catches an intruder
   who trips living-room motion before any entry, even when each event is individually common.
7. **Stranger-by-behavior, not by face** — classify household-like vs stranger-like from time/
   sequence/dwell, zero biometrics. Ship this rung before any faceprint ladder.
8–9. KartenWerk as an egress, subprocess-isolated tile (the Werkstatt's ambient ledger);
   two-factor reality for money-touching actions (LLM proposal + physical confirm, logged).
10. A move-in "cold-start kit": answer the PLAN question bank → seed weak priors → warm start.
11. Floor-plan-aware zones + adjacencies from the Polycam scans → prior for plausible movement.
12. The cockpit "why" pane (every act shows its because).
13. A panic / privacy hard switch enforced at `assert_emittable` (stop emission, suspend
    actuation, mark the window never-learned).
14. A three-tier model cascade (tiny always-warm anchor model between the predicate and the
    8B) — GPU sleeps more, chat still answers while the desktop games.
15. The Dream Journal as the memory the model reads — local-only retrieval vectors are fine
    (PrivacyGuard forbids `vector` on the MESH; local retrieval never touches that boundary).
16. 🌶️ "Tells" — a strictly-opt-in, strictly-local self-baseline mirror; and the house writes
    its own nightly changelog paragraph.

## The one thing
Same keystone as the first audit — one `build_daemon`, one e2e test on the production graph —
**plus: wire the clock in the same commit.** The daemon-in-the-house is a strict subset of the
daemon-in-the-tests, and that subset has no sense of time passing. *(On this branch the
`build_daemon` keystone is shipped — M1; the clock/tick producer is the open structural item,
captured as M2.5.)*
