# Homie — Progress (living status board)

*The execution scoreboard for [`docs/MASTERPLAN.md`](MASTERPLAN.md). The MASTERPLAN is
the **what & why**; this file is the **how it's going**. Updated every time a milestone
lands or a decision is taken.*

- **Branch:** `claude/homie-overview-bo4l8v`
- **Tests:** 280 passing (`python3 -m unittest discover -s tests`) — green on every push
- **Last updated:** 2026-06-27, after M4; M5 in flight (capability panel)

> **Live status page.** This board is the source-of-truth prose; for an at-a-glance page
> that regenerates itself, run `python3 scripts/status.py` (writes `status.html` — open it
> any time) or `python3 scripts/status.py --serve` for an auto-refreshing live URL. It
> gathers everything fresh from git + disk: milestone board, branch, recent commits, an
> optional live test run (`--tests`), and — if a daemon state dir is present — the event
> log's activity and the lessons Homie has actually learned.

---

## At a glance

```
M0   ✅ shipped   Pi-anchor chat fallback — a typed line never vanishes
M1   ✅ shipped   KEYSTONE: build_daemon — one graph for prod/demo/tests
M2   ✅ shipped   Synthetic-perception harness + real Perceive.run
M2.5 ✅ shipped   The clock — tick/timer seam + solar dusk
M3   ✅ shipped   Wake telemetry → calibrated surprise → enforced budget
M4   ✅ shipped   The hour-shaped lesson, spoken back
M5   🔄 building   Capability-gated act path (panel deciding the token mechanism)
M6   ⏳ planned    8B-on-3060 serving discipline
M7   ⏳ planned    Positive-schema privacy guard + Dream Journal (retrieval)
M8   ⏳ planned    Friction Ledger pane + one-key undo
M9   ⏳ planned    Deploy posture + confinement
M10  ⏳ planned    Visible posture + dream note + trust tiers
M11  ⏳ planned    Nightly self-refresh: hygiene · heal · upgrade · restart
```

Legend: ✅ shipped & pushed · 🔄 in progress · ⏳ planned · ⏸ blocked on a decision

---

## Now / Next / Later

- **Now (M5):** Close **C2** — `Act` trusts `payload["priority"]`/`["actuator"]`, so any
  tile can forge a `safety`-priority command on any mapped actuator via raw `ctx.emit`.
  This is the gate that eventually fronts the lock, so the token mechanism is being
  settled in a **panel** (capability-security, object-capability, OS-sandbox, bus, and an
  adversarial red-teamer, then a chair) before code. Also folds in **C14** (the
  `light.living` ↔ `light.living_room` name mismatch).
- **Next (M6):** Give the real 8B-on-3060 cortex a serving discipline — grammar-constrained
  tool decoding, a latency SLO, warm/cold policy chosen from **M3's measured wake cadence**.
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

The throughline: M1 made the tested graph **be** the shipped graph; everything since grows
capability on that proof — a heartbeat (M2.5), an honest energy budget (M3), and a felt
voice for what it learns (M4).

---

## Open decisions / questions

- **M5 capability mechanism** — *being settled now by panel.* Per-call nonce vs
  static per-`(tile,actuator,priority)` token; how it crosses the subprocess JSON wire
  without the child being able to forge it; the honest in-process-shared-memory caveat.
- **Owner location/timezone** — `HOMIE_LAT`/`HOMIE_LON` left as fill-in placeholders in
  `os/boot/configuration.nix` (relocation pending); `HOMIE_TZ` defaulted to `Europe/Berlin`.
  Fill in on move-in to get latitude-correct dusk.
- **Topology ratification** (recorded, not yet ratified) — collapse the brain to one
  always-on node, keep the Pi as a privacy-edge camera only. **M3's wake-cadence data is
  the input** that confirms or flips this; see MASTERPLAN §5.
- **Fine-tune go/no-go** (M-later) — accumulate the friction dataset + measurement first;
  evidence authorizes a trainer, or kills it. Default: no weight tuning.
- **M11 self-upgrade trust model** — update channel, who authorizes, unattended vs approve —
  a **panel decision before that path is built** (owner directive: self-sufficient, but gated).

---

## How this file stays honest

- Updated in the **same commit** as the milestone it reports (test count + commit hash).
- Status here must match the test suite: a milestone is ✅ only when its named acceptance
  test(s) pass and the change is pushed.
- Decisions move from *Open* to a recorded verdict in `docs/MASTERPLAN.md`; this board
  links to them rather than duplicating the reasoning.
