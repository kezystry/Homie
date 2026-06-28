# Homie — Progress (living status board)

*The execution scoreboard for [`docs/MASTERPLAN.md`](MASTERPLAN.md). The MASTERPLAN is
the **what & why**; this file is the **how it's going**. Updated every time a milestone
lands or a decision is taken.*

- **Branch:** `claude/homie-overview-bo4l8v`
- **Tests:** 595 passing (`python3 -m unittest discover -s tests`) — green on every push
- **Last updated:** 2026-06-28, after the **Camera foundation** (registry + positive zone-allowlist +
  go2rtc/Frigate config-gen + the edge adapter where frames die — see [`docs/CAMERA.md`](CAMERA.md)) and
  the **external-audit safety pass** (FIFO confirm queue + exact-match yes/no + the Coherence test that
  closes the speech-bypass). Prior: **Phase A** (the SpeechBudget muzzle), **M6** (serving discipline),
  the **HA adapter** (driving the owner's real DIRIGERA bulbs), **GIST slice 2**.

> **Updating the Homie box.** The box runs a git checkout at `/opt/homie`; update with
> `python3 scripts/update.py` (pulls + runs the suite as a health check, reports safe/not),
> then `sudo systemctl restart homie`. Roll back with `git reset --hard HEAD@{1}`. This is
> the channel the nightly self-upgrade (M11) builds on. Full steps: `os/INSTALL.md`.

> **Live status page.** This board is the source-of-truth prose; for an at-a-glance page
> that regenerates itself:
> - `python3 scripts/status.py --text` — **prints the board right in your terminal** (best
>   over SSH from a phone — no browser, no port-forward; add `--tests` for a live pass/fail).
> - `python3 scripts/status.py` — writes `status.html` to open in a browser any time.
> - `python3 scripts/status.py --serve` — an auto-refreshing live URL (tunnel it over SSH
>   with `ssh -L 8765:localhost:8765 <host>`, then open `http://localhost:8765`).
>
> Every load gathers fresh from git + disk: milestone board, branch, recent commits, an
> optional live test run, and — if a daemon state dir is present (`--state` / `$HOMIE_STATE`)
> — the event log's activity and the lessons Homie has actually learned.

---

## At a glance

```
M0   ✅ shipped   Pi-anchor chat fallback — a typed line never vanishes
M1   ✅ shipped   KEYSTONE: build_daemon — one graph for prod/demo/tests
M2   ✅ shipped   Synthetic-perception harness + real Perceive.run
M2.5 ✅ shipped   The clock — tick/timer seam + solar dusk
M3   ✅ shipped   Wake telemetry → calibrated surprise → enforced budget
M4   ✅ shipped   The hour-shaped lesson, spoken back
M5   ✅ shipped   Capability-gated act path — no faked commands (closes C2/C14)
M6   ✅ shipped   8B-on-3060 serving discipline — latency SLO, warm/cold, tool grammar
PA   ✅ shipped   Phase A — Self-pacing voice: one governor that LEARNS how chatty to be (anti-nag)
PB   ✅ core      Phase B — honest beliefs: prob∈[0,1] + mean-revert + nmin (fixes the >1.0 bug)
PC   ✅ done     Phase C — first win: "What Homie Knows" page ✅ · Agenda+Briefing+route ✅ ·
                 morning wiring ✅ (clock fires time.morning → ONE governed line + screen page) ·
                 live HA calendar/to-do/weather feed ✅ (agenda.external → folded into briefing)
PD   ✅ shipped   Phase D — the undo button: confirm gate ✅ (FIFO + exact-match, audit-hardened) ·
                 Friction Ledger ✅ · one-tap re-drive ✅ (instant; guarded domains ask first)
CAM  ✅ founded   Camera foundation — registry + positive zone-allowlist + go2rtc/Frigate config-gen
                 + edge adapter (frames die at the Pi) + the Coherence test. Box wiring next.
DUSK ✅ shipped   Dusk lighting offer-once-then-auto — first dusk ASKS, a yes locks in silent
                 auto, repeated declines settle to no (anti-nag). Owner's call.
SELF ◑ building  Self-sufficiency (Charter 8a/13a/22a/23a/25a/28a from a 5-pro council) — storage
                 Groundskeeper ✅ · GIST nightly memory S1 ✅: slices 4+5 (classifiers + counted-
                 absence fold + nmin promote + OFF-fence + bounded prune) · slice 6 prose brief
                 (tense=honesty) · slice 7 store+collector wired into the ritual (runs nightly,
                 persisted .ddn) · S1.5 earned persistence (Mechanism 2, 3-pro council: belief
                 fades fast, record lingers years). S2 self-cycle ✅: health-gated self-upgrade
                 (authority-freeze + auto-rollback + changelog) + sd_notify self-heal watchdog +
                 NixOS nightly timer. Next: S3 consent/gallery.
DESK ◑ building  Main-PC eyes+hands (3-pro council) — DesktopAdapter (X11 facts not frames) ✅ ·
                 full WatchLog + recommendation engine (titles + taste + predictions) ✅ · desktop
                 tile + safe capability-gated control (fixed verb allowlist, no exec) ✅. Next:
                 deploy wiring + auto-behaviors (dim on film-start) + the recommend page surface.
M7   ⏳ planned    Positive-schema privacy guard + Dream Journal (retrieval)
M8   ⏳ planned    Friction Ledger pane + one-key undo
M9   ⏳ planned    Deploy posture + confinement
M10  ⏳ planned    Visible posture + dream note + trust tiers
M11  ⏳ planned    Nightly self-refresh: hygiene · heal · upgrade · restart
```

Legend: ✅ shipped & pushed · 🔄 in progress · ⏳ planned · ⏸ blocked on a decision

---

## Now / Next / Later

- **Now (the six-thing soul, per [`docs/SCOPE.md`](SCOPE.md)):** the brainstorm + external audit
  reordered the work. Build order: **(A) ✅ the muzzle** → **(B) honest beliefs** (the 3 GIST stat
  fixes + `nmin` + crash-safe nightly fold — fixes a live bug, jumps the queue) → **(C) the first
  win** (morning recap + "What Homie Knows" page) → **(D) felt control** (one-key undo + Friction
  Ledger + the `confirm.response` producer) → **(E) lights+climate autonomy** (hand-set rungs, not a
  rolling-score engine). Then live with it a month and let the lived-gap log authorise the 7th thing.
- **Just shipped (Phase A — the muzzle):** `core/voice.py` + `core/speech_budget.py` — ONE global
  governor on `interface.say`. Tiles emit facts; the VoiceGate decides what the owner actually hears
  (`interface.spoken`, ~6 proactive lines/day, owner-chosen) vs what defers to the recap as a lossy
  count (`speech.deferred`). Safety/summons bypass the budget; an everyday `voice.mute` is the
  fastest nag-kill. The cockpit renders only the governed channel — a tile cannot reach the owner
  ungoverned. This is the first instance of the single-waist law the audit called the system's best idea.
- **Just shipped (M6 — serving discipline):** the cortex now decodes tool calls under their
  JSON-Schema grammar (fewer malformed-call drops), **times every model call against a latency
  SLO** and emits `reason.served` telemetry (latency, p95, met?), and keeps the GPU warm only
  around real activity via a `WarmPolicy` (so the 3060 sleeps for fast WoL yet doesn't re-pay
  cold-start mid-burst). The model choice is recorded in `deploy/MODEL.md`: an abliterated-then-
  healed Qwen3-8B as default, stock kept for A/B.
- **Just shipped (the real hand — Home Assistant adapter):** the `HomeClient` seam that was a
  `LoggingHome` stub is now a working **Home Assistant client** (`core/ha.py` over a stdlib
  WebSocket in `core/ws.py`). Homie drives real DIRIGERA/Tradfri lights via `call_service` and
  hears human switch-flips via `subscribe_events` — its own echoes suppressed through the one
  `ha_canonical`, so only *human* changes become friction. Reconnects with backoff; tests +20
  (offline, no live HA). Turn it on by setting `HOMIE_HOME_URL` + `HOMIE_HOME_TOKEN`.
- **Just shipped (GIST v2):** the daily-memory format revised by a 21-agent council into an
  integer-exact STATE block with human-readable renders — see `docs/MEMORY-GIST.md`.
- **Just shipped (M5):** Closed **C2** — `Act` no longer trusts the payload's
  priority/actuator; every command now carries a registry **capability handle** the trusted
  core mints (bound to tile+actuator+manifest-priority), and a forged raw `ctx.emit` is
  refused in-process *and* over the subprocess wire. Folded in **C14** (the
  `light.living` ↔ `light.living_room` name mismatch). Settled by a 6-agent panel first.
- **Later:** M7 retrieval/Dream Journal (the high-leverage learning upgrade, no weight
  tuning) → M8 felt control (undo) → M9 deploy hardening → M10 the visible payoff →
  M11 the self-sufficient nightly refresh.

---

## Shipped — milestone log

| M | Result | Closed | Tests | Commit |
|---|--------|--------|------:|--------|
| **M0** | `AnchorVoice`: chat is answered from Remember even with no cortex — a typed line never vanishes | proof-of-life | +6 | `1f75859` |
| **M1** | `build_daemon` keystone: production, demo, and tests drive **one** graph; Remember attaches last | C1, C4, C13 | +7 | `7f47434` |
| **M2** | Real `Perceive.run` intake + `SyntheticPerception` replay + scenario library | C11 intake | +7 | `986b5e8` |
| **M2.5** | The clock (`tick.*` + `timer.*`); lighting auto-off via timer; latitude-correct solar dusk; `HOMIE_TZ` pinned | N1, N4, N7 | +10 | `4ee4d99` `7c699bc` `6c2ab54` |
| **M3** | Wake governance: `WakeLedger` (asleep-fraction is a real number) → per-zone calibrated surprise → event-clocked token budget (safety/chat exempt, deferred-never-dropped, backoff) | C8 | +15 | `4404698` |
| **M4** | A freshly-formed `(room,hour)` lesson is spoken once ("…stop lighting the kitchen around 7pm") and survives a restart | felt | +1 | `aa0a20b` |
| **M5** | Registry-handle capability: a tile drives only what its manifest declares, at its declared priority — even a forged raw emit is refused, in-process and over the subprocess wire; C14 name mismatch fixed | C2, C14 | +13 | `M5 (1–4/4)` |
| **—** | **The real hand:** `HomeAssistantClient` over a stdlib WebSocket — drives real DIRIGERA/Tradfri via `call_service`, hears human switch-flips via `subscribe_events`, echoes suppressed through the one `ha_canonical`; reconnects with backoff | deploy seam | +20 | `e247c28` |
| **M6** | Serving discipline: JSON-Schema tool-grammar decode, a latency SLO with `reason.served` telemetry, and a warm/cold `WarmPolicy`; model card (abliterated Qwen3-8B default + stock A/B) | felt: quick | +13 | `M6` |

The throughline: M1 made the tested graph **be** the shipped graph; everything since grows
capability on that proof — a heartbeat (M2.5), an honest energy budget (M3), a felt voice
for what it learns (M4), and a real least-privilege gate on every action (M5).

---

## Open decisions / questions

- **M5 capability mechanism** — *decided & shipped.* Registry **handle** (not a payload
  token): a 128-bit opaque key into an in-process dict, never serialized over the wire.
  Honest caveat recorded in `core/capability.py`: this stops accidental escalation and
  hardens the subprocess boundary, but is **not** unforgeable against a malicious
  in-process tile (shared heap) — the answer there is running it as a subprocess.
- **Owner location/timezone** — `HOMIE_LAT`/`HOMIE_LON` left as fill-in placeholders in
  `os/boot/configuration.nix` (relocation pending); `HOMIE_TZ` defaulted to `Europe/Berlin`.
  Fill in on move-in to get latitude-correct dusk.
- **Topology — DECIDED by owner: keep the 3-machine design** (Pi + wired home-control box +
  GPU desktop, talking over the private network). Because they talk to each other, the
  cross-machine **privacy guard (M7) matters more** — raw camera/faces must never cross.
- **Fine-tune go/no-go** (M-later) — accumulate the friction dataset + measurement first;
  evidence authorizes a trainer, or kills it. Default: no weight tuning.
- **M11 nightly renewal — DECIDED by owner: at midnight Homie does BOTH** a full tidy-up/
  refresh AND installs real upgrades (two separate steps). Safety rails (panel): keep only a
  health-checked upgrade with automatic rollback, write down what changed, and never
  auto-grant new device power without the owner's yes.

---

## How this file stays honest

- Updated in the **same commit** as the milestone it reports (test count + commit hash).
- Status here must match the test suite: a milestone is ✅ only when its named acceptance
  test(s) pass and the change is pushed.
- Decisions move from *Open* to a recorded verdict in `docs/MASTERPLAN.md`; this board
  links to them rather than duplicating the reasoning.
