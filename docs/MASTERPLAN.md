# Homie — The Master Plan

*Chief architect's document. Audience: the owner (solo builder, SSH-from-phone) and
the next Claude who executes this. Written 2026-06-27 against a tree of 225 passing
tests. Supersedes nothing in `docs/` — it sequences it.*

---

## 1. North star (the honest version)

Homie is **one organism wired exactly once.** A single assembler — `build_daemon(home,
perception, *, config)` — constructs the whole living loop (bus → perceive → remember →
tiles → act → reconcile → friction → reason), and the production daemon, the spine demo,
and every test all drive *that same graph*, differing only in which `HomeClient` and which
perception source are injected. When the suite is green, that is a literal proof the
shipped home works — because there is no second, untested wiring for production to diverge
into. On top of that proven loop, Homie **spends GPU compute in proportion to genuine,
measured surprise**, learns the household from its own private append-only log via
**retrieval, not weight-tuning**, and makes its four felt promises — *it listens, it
remembers the shape of your days, it owns its mistakes out loud, and it can always be
corrected* — properties you can **see or hear on demand**, not sentences in a docstring.

The honest part: today none of that is true in production. `scripts/run.py` wires
`Bus + Remember + Consent + Supervisor + (optional) Reason + CockpitBridge` and **nothing
else**. Actuation (`Act`), corrective learning (`StateReconciler`), the mesh, and the
nightly ritual are real, tested code that production never instantiates. The spine demo
(`scripts/spine_demo.py`) wires the *full* loop — against a `FakeHome` — and asserts
nothing. So we have a tested organism and a shipped organism, and they are not the same
organism. **This plan's entire job is to make them the same organism, then grow it.**

---

## 2. Guiding principles

1. **One graph, injected seams.** There is exactly one wiring of Homie. Production and
   tests differ only by injection (`HomeClient`, perception source, `LLMClient`,
   `MeshTransport`). A passing test is a proof about production *only* if production runs
   the tested graph. Two wirings is the root cause of the worst finding (C1); we never
   create a second one again.
2. **stdlib where feasible.** Python 3.11+, standard library only unless a dependency
   earns its place by a panel decision. No vector DB, no training framework, no web app
   stack pulled in for convenience. `unittest`, `asyncio`, `json`, `sqlite3` are the
   palette. The reasoning model is an *external* process behind a Protocol seam
   (`core/reason.py:LLMClient`), never an in-process import.
3. **Decide significant things in a meeting.** Architectural forks (topology, capability
   mechanism, fine-tune go/no-go, identity model) are settled by a role-played panel of
   actual domain professionals debating honestly, then a chaired synthesis — never solo.
   This document records the verdicts; re-open one only with a new panel.
4. **Privacy floor is a boundary, not a vibe.** Raw frames/embeddings/faceprints never
   cross a wire. On a single brain node the privacy guard is a sanity check; the moment
   anything goes multi-node it becomes a hard control and must be a *positive schema*
   (declared-emittable), never a name/size blocklist. "Impossible by construction" must be
   true by construction or the words come out.
5. **Earn every GPU wake.** No unmeasured "95% asleep." Instrument first, calibrate
   against the home's own distribution, then enforce a budget. A claim the code never
   checks is a lie waiting to be found.
6. **Felt over internal.** Every milestone should produce a sensation the owner can point
   at — a reply that lands, a light that obeys, a spoken lesson, an undo, a morning note —
   not only a capability a test can see. Plumbing exists to make a moment possible.
7. **Reversibility beats correctness.** Trust comes from being able to overrule Homie
   frictionlessly, not from Homie being right. Ship the undo before the cleverness.
8. **Keep the suite green; let it ratchet.** Every milestone lands with the test(s) named
   in its acceptance row. The count only ever goes up. Docs that cite a count get corrected
   in the same change.

---

## 3. The keystone move (everything hinges on this)

> **Extract `build_daemon(home, perception, *, config) -> Daemon` as the single assembler
> of the whole graph, and rewrite `scripts/run.py` and `scripts/spine_demo.py` into thin
> callers of it.**

Why this and nothing else first:

- It **kills C1 by construction.** `build_daemon` wires `Act`, `StateReconciler`, and the
  in-process ritual *unconditionally*. There is no longer a production path that "forgot"
  to instantiate the corrective loop, because there is only one path.
- It **structurally fixes C4.** The Remember-attached-last ordering is decided *once*,
  inside `build_daemon`, and shared by everyone. The novel-event-masks-its-own-novelty bug
  cannot reappear per-entrypoint because there are no per-entrypoint orderings left.
- It is the **test substrate for everything after it.** The synthetic-perception harness,
  the wake-budget meter, the security regression tests, and the felt-experience moments all
  want to assert against *the real production graph*. If `build_daemon` doesn't exist, every
  one of those tests is written against a demo graph production doesn't run — which is
  exactly the trap we're climbing out of.
- It is **pure topology collapse — no new behavior.** Lowest-risk possible first move:
  every line already exists in `spine_demo.py` (`Act`, `CommandLog`, `ActMap`,
  `StateReconciler`, lines 80–85) and `run.py`; we are relocating wiring into one function,
  not inventing logic.

Three sub-decisions baked into the keystone (panel-settled, see §5/§6):
- **Reason is always wired**, with a `NullLLMClient` injected when `config.llm_url` is
  unset — so the proposer path is present and tested everywhere, and the *only* difference
  between the Pi-anchor and the desktop is whether a real model answers. This removes the
  "production has a code path no test exercises" hazard that birthed C1.
- **Mesh is a `MeshTransport` seam**, defaulting to **loopback** (in-process, no
  serialization, no NoiseLink). Multi-node is a config flag, not a rewrite (see §5).
- **Perception is one injected intake seam** that both `SyntheticPerception` (harness) and
  the live MQTT/mesh adapter implement. The synthetic harness is *not* a test-only fork; it
  is the same seam production uses — or we recreate the run.py/spine_demo divergence one
  layer down.

**Acceptance for the keystone itself** (this is M1 below): a grep of the production
entrypoint shows it constructs *nothing* directly except `build_daemon(...)` plus injection
of the real `HomeClient` and perception source; `spine_demo.py` does the same with
`FakeHome` + a synthetic source; the two share **>90%** of their wiring through
`build_daemon`.

---

## 4. Phased milestones

Effort key: **[hours]** a sitting · **[days]** a focused day or three · **[weeks]** a
multi-session epic. Each milestone names its goal, concrete tasks (with file paths), the
**exact** acceptance test name(s), effort, and what it unblocks. Test names are the
contract — write the test, make it fail on the bug, make it pass on the fix.

Ordering rule encoded below: **proof-of-life and the single graph come before any
hardening or cognition**, because a hardened or clever system wired wrong is worth less
than a plain one wired right.

---

### M0 — The typed line never vanishes (Pi-anchor chat fallback) · [hours]

**Goal.** The cheapest perceivable proof-of-life, and a fix for a silent failure that
would poison every later trust moment: today on a bare Pi (`HOMIE_LLM_URL` unset) the
cockpit accepts a chat line, publishes `chat.message`, and **nothing subscribes** — the
owner types into a void.

**Why first.** A home that eats your words is dead, not alive. It needs nothing new built —
`Remember`, the bus, and the TUI chat pane already exist; it needs one guaranteed
responder. It also makes the tiering *honest*: the anchor speaks for itself instead of
pretending the cortex is present.

**Tasks.**
- Add a tiny stdlib `AnchorVoice` subscriber (new `core/anchor_voice.py`) that subscribes
  to `chat.message` and **always** publishes `chat.reply`. It answers status and
  pattern-of-life questions from `Remember` ("the back door normally opens around 17:40;
  last seen 18:02"), and on anything reasoning-shaped says so plainly: "I'm the anchor right
  now — the thinking node is asleep; here's what I know: …". Never silence, never a
  fake-smart answer.
- Wire it in `build_daemon` (so it's present whether or not Reason has a real LLM). When a
  real LLM *is* present, Reason still handles reasoning-shaped lines; `AnchorVoice` only
  guarantees the *floor* of always-a-reply.

**Acceptance.** `tests/test_anchor_voice.py::test_chat_always_replies_without_llm` —
with `NullLLMClient` injected, publishing `chat.message{"text":"are the doors locked?"}`
and `{"text":"when does the back door usually open?"}` each yields a `chat.reply` within
~1s; a reasoning-shaped question yields an explicit deferral line, never silence.

**Unblocks.** Establishes the "never silent" contract every later spoken moment rides on.

---

### M1 — The keystone: one `build_daemon` graph + wiring/ordering contract tests · [days]

**Goal.** Collapse the two wirings into one assembler; lock the C1/C4 invariants with tests
that *fail* if the bugs return.

**Tasks.**
- Create `core/daemon.py` with `build_daemon(home, perception, *, config) -> Daemon`. It
  wires, unconditionally and in this order: `Bus` → `Consent` → `Supervisor` → `Act(home,
  CommandLog, ActMap)` → `StateReconciler(sup, commands, reverse_map, on_echo=act.confirm)`
  attached to `home` → `Reason` (with real or `NullLLMClient`) → `AnchorVoice` →
  `CockpitBridge` → **`Remember.attach(bus)` LAST**. `Remember.bootstrap(bus)` still runs
  early (rebuild from snapshot); only the *live attach* is last so evaluation precedes
  commit.
- Add `NullLLMClient` to `core/reason.py` (implements the `LLMClient` Protocol; `propose`
  returns a no-op `Proposal`).
- Add the `MeshTransport` seam (`core/mesh.py`): a `LoopbackTransport` default that is a
  no-op (single process needs no wire). Do **not** build NoiseLink.
- Rewrite `scripts/run.py` to: read `config` from env, build the real MQTT `HomeClient`
  (gated on `HOMIE_HOME_URL`; `FakeHome` fallback so the bare anchor still runs the loop),
  build the perception source, and call `build_daemon(...)`. Nothing else constructed
  directly.
- Rewrite `scripts/spine_demo.py` to call `build_daemon(FakeHome(), SyntheticPerception(...),
  config=demo_config)` — same assembler, different injection. (SyntheticPerception lands in
  M2; until then inject a trivial scripted source.)
- Move the nightly `ritual.consolidate()` call **in-process** into `_housekeep` on a nightly
  schedule (the daemon already holds `events.jsonl` open — no second-process race; this
  closes C13's hold without a systemd timer). Keep the interval compaction floor.

**Acceptance.**
- `tests/test_daemon_wiring.py::test_act_subscribes_actuator_requested` — the graph from
  `build_daemon` has a subscriber on `actuator.requested`; **fails** if `Act` is removed.
- `tests/test_daemon_wiring.py::test_remember_attached_last` — `Remember` is the **last**
  `Bus` subscription registered; **fails** if Remember attaches before the Supervisor.
- `tests/test_daemon_wiring.py::test_novel_event_not_self_masked` — under the live-attached
  production graph, the first sighting of a genuinely-novel `(topic,zone)` is evaluated as
  `novel` by Security/Reason **before** Remember commits it (novel-rate does not collapse to
  ~0). **Fails** on the old Remember-first ordering.
- `tests/test_daemon_wiring.py::test_entrypoints_share_graph` — asserts `run.py` and
  `spine_demo.py` both route through `build_daemon` (construct nothing else of substance).
- `tests/test_golden_loop.py::test_arrival_drives_reversal_makes_tile_quiet` — replays a
  presence trace through the real `build_daemon` graph against `FakeHome` and asserts: a
  lighting tile drives the fake bulb on arrival, the home's echo is **suppressed** (not read
  as reversal), and a subsequent human reversal delivers a `FrictionSignal` that makes the
  tile go quiet on the **next** identical arrival. This is `spine_demo` converted from
  print-statements into enforced invariants.

**Unblocks.** Everything. After M1, "the tested graph" and "the shipped graph" are one
sentence.

---

### M2 — Synthetic-perception harness + real `Perceive.run` · [days]

**Goal.** A deterministic test substrate for *all* behavior — the whole graph (including
Reason and friction) runs with no camera, no Pi, no GPU. Closes the C11 intake stub.

**Tasks.**
- Implement `Perceive.run(self, bus)` in `core/perceive.py` as the real intake loop (it is a
  `...` stub today). It pulls normalized events from an injected source and publishes them.
  The privacy guard `assert_emittable` (already real) gates emission.
- Add `SyntheticPerception` (new `core/synthetic.py`) implementing the same intake seam:
  replays scripted/recorded normalized event traces (`presence.arrived`/`unknown`, `motion`,
  `occupancy`, with zones + timestamps) into the bus at controllable speed.
- Ship a small named-scenario library (`tests/scenarios/`): `normal_weekday`,
  `novel_visitor_3am`, `holiday_drift`, `sensor_flap_storm`.

**Acceptance.** `tests/test_synthetic.py::test_scenario_replays_deterministically` —
replaying a fixed scenario twice yields bit-identical bus traffic and ledger counts
(consistent with Remember's deterministic-replay contract).
`tests/test_perceive.py::test_run_is_the_intake_seam` — `SyntheticPerception` and a fake
live adapter are driven through the identical `Perceive.run` path.

**Unblocks.** M3 (wake budget needs replayable days), the felt-experience tests, and the
security regression tests — all want deterministic full-graph replay.

---

### M3 — Wake telemetry → calibration → enforced budget · [days]

**Goal.** Turn C8's unmeasured "~95% asleep" into a measured, *enforced* bound. Three steps,
in order: **see it, calibrate it, cap it.**

**Tasks.**
- *See it.* Add a `WakeLedger` (`core/wake_ledger.py`) recording every `Expectation`
  evaluation `(topic, zone, hour, rate, novel, should_wake, fired)` to a rolling counter and
  the event log; emit a `wake.decision` event. Surface wake-rate, novel-rate, and
  decisions/hour in the cockpit. No behavior change yet.
- *Calibrate it.* Replace the static `novel or rate < 0.1` predicate in `core/reason.py`
  (`should_wake`, `WAKE_RATE=0.1`) with a **per-zone calibrated surprise score**: a running
  quantile of recent rates, so "rare" means rare-relative-to-this-home, not below a magic
  global constant. Keep a global floor as a safety net only. Calibrate against the
  `WakeLedger`'s real distribution — *after* M1's C4 fix, so novelty numbers are honest.
- *Cap it.* Add a token-bucket budget on wakes (N decisions/hour, M/day) with **safety and
  chat topics exempt**, plus exponential backoff when the model returns do-nothing
  repeatedly for a `(zone,topic)`. Wakes over budget are logged as **deferred, never
  silently dropped**; lowest-surprise candidates shed first. The current `_inflight` set
  (reason.py:166–178) only coalesces concurrent bursts — it is not a budget.

**Acceptance.**
- `tests/test_wake_ledger.py::test_ledger_counts_are_replay_stable` — replaying a fixed log
  yields bit-identical ledger counts.
- `tests/test_wake_budget.py::test_cold_start_flood_is_bounded` — a synthetic cold-start
  flood of N novel events produces **at most** the configured wakes/hour; every shed wake is
  recorded as deferred (**zero silent drops**); safety/chat wakes are never shed; the real
  measured asleep-fraction is reported as a number.

**Unblocks.** The topology decision (§5) — you cannot honestly choose node count without a
real wake cadence — and the serving warm/cold policy (M6).

---

### M4 — The hour-shaped lesson, spoken back · [days]

**Goal.** The first genuine goosebumps moment: the home audibly admits it learned a
specific, hour-shaped thing about *this* household.

**Tasks.**
- When a tile's `learn()` commits a suppression (e.g. `tiles/lighting/learn.py` writes
  `state["suppressed"][room].add(hour)`), emit **one** plain `interface.say` / `chat.reply`
  line at the moment it changes its mind: "Got it — I'll stop lighting the kitchen around
  7pm." Add a small "lesson narration" hook so a learned suppression announces itself
  **once** (repeats get summarized later, in the dream note — see M7).
- Speak the **first** time a given `(room,hour)` lesson forms; do not narrate every
  histogram tick.

**Acceptance.** `tests/test_lesson_narration.py::test_learn_commit_emits_one_line` — after a
reversal teaches lighting to suppress `(kitchen, 19:00)`, exactly one `interface.say`/
`chat.reply` line is emitted **naming the room and the hour**, and the suppression persists
across a daemon restart.

**Unblocks.** Converts the invisible histogram into a felt relationship; sets the voice
pattern the dream note (M7) reuses.

---

### M5 — Capability-gated act path (close C2) · [weeks]

**Goal.** Make least-privilege *true*: a tile can only drive what its manifest declares, at
the priority its manifest declares — even via a raw `ctx.emit`. Close C2 at the **consumer**,
not the producer, so the `SubprocessChannel._forward` raw-emit path (tile.py:533) is covered
too.

**Why now and not at M1.** M1 wires the act loop; the instant it's live, C2 is exposed — any
in-process tile can forge `Event(topic="actuator.requested", payload={"priority":"safety"})`
and Act will honor it (it reads `priority`/`actuator` straight from the payload; the only
check is the act-map). The disciplined rule (panel verdict, §5): **never wire the open path
and harden later.** M1 is allowed to ship the loop on a *single, non-safety actuator* (a
light) to keep blast radius tiny; M5 closes the gate before any second actuator — and
absolutely before the lock — is wired.

**Tasks.**
- In `core/tile.py`, have `ctx.act` mint a per-call **capability token**: an unguessable
  value bound to `manifest.name` + the specific declared actuator + `manifest.priority_for
  (actuator)`. The Supervisor populates a token registry from manifests at tile load.
- In `core/act.py`, `_on_request` **stops trusting** `event.payload["priority"]` and
  `["actuator"]`; it verifies the token against the registry and refuses anything without a
  valid one. The act-map remains the hard outer boundary (never-touch stays).
- Fix C14 in the same change: align `tiles/lighting/tile.toml`'s `light.living` with
  `deploy/act_map.toml`'s `light.living_room` (one token, including the `[acts.priorities]`
  table and the `light_room` param example).
- (Recorded follow-on, not this milestone: the object-capability end state where
  `ctx.act` returns pre-authorized closures and there is no "request an actuator by string"
  channel at all. Ship the token registry first — testable, low-churn; treat the obj-cap
  rewrite as a later refactor. Do not let the perfect block the urgent.)

**Acceptance.** `tests/test_act_capability.py::test_forged_safety_emit_refused` — a tile that
constructs `Event(topic="actuator.requested", payload={"priority":"safety", "actuator":
<not in its manifest>})` and calls `ctx.emit()` is **refused** by Act (no valid capability),
while the same tile's `ctx.act()` on a *declared* actuator **succeeds** — asserted for both
`InProcessChannel` and `SubprocessChannel`.

**Unblocks.** Safe rollout to additional actuators (and eventually the lock) and to the
Friction Ledger's one-key undo (M8), which issues inverse acts.

---

### M6 — 8B-on-3060 serving discipline · [weeks]

**Goal.** Make the desktop cortex's serving path real, bounded, and tested — the inference
*plumbing* (`LLMClient` Protocol, `deploy/llm.py`) is clean and defensive, but the serving
*discipline* (quant, grammar constraint, latency SLO, warm/cold policy) is undocumented and
untested against a real model.

**Tasks.**
- Pin `llama-server` with a **grammar / JSON-schema-constrained** tool-decoding config so the
  abliterated 8B cannot emit malformed tool calls in the first place; keep
  `validate_tool_call` as defense-in-depth.
- Set a concrete latency budget: sub-second ambient (small KV-cache + short context), ~2s
  chat. Add a `/health` probe.
- Decide warm-keepalive vs cold-load **empirically from M3's cadence telemetry** (panel
  prior: cold-load-on-demand with a short warm-keepalive window after a wake — a resident 8B
  burns power against the very premise of the tiering). Do not default to resident-for-latency.
- Golden-prompt regression harness against `parse_completion` with recorded real completions.

**Acceptance.** `tests/test_serving.py::test_grammar_rejects_malformed_tool_call` (server-side
rejection precedes `validate_tool_call`) + `tests/test_serving.py::test_latency_slo_p50_p95`
(measured p50/p95 from recorded completions meet the documented SLO) + a `/health` probe test.

**Unblocks.** The Dream Journal (M7) needs a working, latency-bounded model to generate and
consume summaries.

---

### M7 — Positive-schema privacy guard + the Dream Journal (retrieval) · [weeks]

**Goal.** Two things that must land together because the Journal's embeddings are *exactly*
the C6 leak vector. First make the privacy guard true; then give Homie recall.

**Tasks (guard first — it is a prerequisite).**
- Replace **both** guards (`core/mesh.py:PrivacyGuard.permits`,
  `core/perceive.py:assert_emittable`) with a **positive per-topic payload schema**: an
  allowlist of `{topic -> declared field set + types + bounds}`. The guard walks the **whole
  payload tree** recursively and rejects undeclared keys, oversized arrays, and
  float-vector-shaped values **regardless of key name or nesting depth**. The 4096-byte cap
  stays as a coarse backstop, not the primary control. Anything not declared emittable is
  refused — accept that a new meshable topic now costs a one-line schema declaration; that
  friction is the feature.

**Tasks (then the Journal).**
- Nightly (the in-process ritual from M1, reading a **read-only snapshot** to avoid the
  compaction race), distill the day into a small set of natural-language **episode summaries**
  with embeddings, stored **locally on the reasoning node only**, never mesh-forwarded.
- At `decide()` time, retrieve top-k relevant past episodes and inject them into
  `build_context`. The model now reasons *with* the household's history, not a single event's
  rate. Use a small local embedder on the 3060; stdlib-friendly top-k over compact embeddings
  — **no vector DB, no external service** (that would violate the stdlib/privacy floor and
  create a new exfiltration surface for the exact data C6 fails to contain).

**Acceptance.**
- `tests/test_privacy_schema.py::test_features_and_nested_faceprint_rejected` — `{"features":
  [<128 floats>]}` and `{"data":{"faceprint":[...]}}`, both under 4096 bytes, are **rejected**
  by both guards; a declared in-spec event of the same topic passes. Property-style:
  `test_no_float_vector_of_any_keyname_crosses` asserts no float-vector-shaped value of any
  key name or nesting depth can cross.
- `tests/test_dream_journal.py::test_retrieval_changes_a_decision` — a seeded night produces
  episode summaries whose retrieval **measurably changes at least one decision** in an
  end-to-end test, and **no embedding passes the privacy guard** with a forbidden shape.

**Unblocks.** Most of what people imagine fine-tuning would buy (M9's verdict). This is the
bridge from today's histogram to any future weight-tuning.

---

### M8 — The Friction Ledger pane + one-key undo · [weeks]

**Goal.** A visible place to see what Homie did and a frictionless way to overrule it. Trust
comes from reversibility, not correctness.

**Tasks.**
- Add a third column to the cockpit TUI rendering the live act/reversal/lesson stream as
  human sentences: "6:58pm — turned on hallway light · you turned it back off · I'll
  remember." Each row selectable.
- A keypress issues the **inverse act** (via the M5 capability path) **and** records a
  **remark-grade** correction (the strongest tier — an explicit undo is the clearest possible
  signal of intent). Make the teaching visible in the row ("· I'll remember").
- Persist the ledger so it survives a restart. `ActionRef`/`FrictionSignal` already exist
  in-memory; this surfaces and persists them.

**Acceptance.** `tests/test_ledger_tui.py::test_undo_emits_inverse_act_and_remark` — a key
sequence over the ledger pane emits the inverse act **and** a remark-grade correction visible
in the same pane; the ledger survives a daemon restart.

**Unblocks.** The friction *dataset* (M9) — undo and reversal are the preference-pair signal.

---

### M9 — Deploy-posture + confinement hardening · [days–weeks]

**Goal.** Harden the *box*, not just the brain. Close C7, C9, and the subprocess-tile
isolation gap with **one reusable confinement profile**.

**Tasks.**
- **C7:** stop shipping Stremio with `--no-sandbox` and `QTWEBENGINE_DISABLE_SANDBOX=1`
  (`os/boot/apps.nix:47–54`). Re-enable the QtWebEngine sandbox. Run Stremio as a **dedicated
  unprivileged user** with **no read access** to `/var/lib/homie` or `/opt/homie`.
- **Confinement:** one hardened systemd-based profile (the deploy is already NixOS+systemd;
  the daemon's `ProtectSystem=strict` exists) parametrized by what each consumer needs to
  see, applied to **both** subprocess tiles and the Stremio renderer. A compromised tile
  cannot read the event log or other tiles' state. (Panel verdict: systemd over a second
  bubblewrap stack — Stremio needs a real session, not a transient sandbox; avoid two sandbox
  stacks.)
- **C9:** remove tty1 autologin (`configuration.nix:57–61`) or add a console idle-lock; split
  the daemon user from the login user so physical/console access does not hand over the
  pattern-of-life log. Make the opt-in `os/boot/ssh.nix` **key-only and wheel-less** by
  default (today, when imported, it puts `homie` in wheel with password auth — a LAN
  password login to a sudo account).

**Acceptance.**
- `tests/test_deploy_posture.py` (or a Nix eval check) `::test_stremio_sandbox_enabled_and_user_split`
  — the booted image runs Stremio with the QtWebEngine sandbox **enabled**, as a user whose
  id **cannot stat/read** `/var/lib/homie` or `/opt/homie`; a subprocess tile attempting to
  open `/var/lib/homie/events.jsonl` **fails**.
- `::test_no_tty1_autologin_shell_to_log` — a fresh boot does not yield a shell with read
  access to the pattern-of-life log without authentication; if `ssh.nix` is imported, the
  login user is not in wheel and auth is key-only.

**Why here.** It is independent of the application-layer work and cheap, but it must land
**before** the visibility features (M10) — there is no point publishing a "what Homie knows"
view while the console trivially exposes the raw log.

---

### M10 — Make the posture VISIBLE (truthfully) + the morning-after dream note + trust tiers · [weeks]

**Goal.** The payoff. Surface the now-*true* guarantees, and give Homie an inner life that
spans days.

**Tasks.**
- **"What Homie Knows"** — a read-only cockpit projection of the pattern-of-life model and
  recent decisions. Low-risk surface reuse of the existing capability-scoped cockpit socket
  (run.py:92).
- **"Sealed Network"** — a generated, testable report enumerating exactly which topics may
  cross the mesh, generated from the **same schema registry the mesh guard enforces against**
  (one source of truth — so the displayed promise and the runtime behavior cannot drift, the
  exact drift that made C6's docstring a lie).
- **Dream note** — the in-process nightly `ritual.consolidate()` (already wired in M1) writes
  **one** short human-readable note the owner finds each morning: what it noticed, learned,
  and is unsure about ("Last night was quiet. I learned you don't want the porch light after
  11. I saw an unfamiliar pattern at the side gate at 2am — flagging, not acting."). **Template-
  first** so the note exists every morning regardless of whether the cortex woke; the desktop
  may optionally rewrite it more warmly when already awake.
- **Trust tiers** — a coarse identity ladder (household / known / guest / unknown), a
  **per-zone presence label, not faceprints**. Lessons learn only from household actors (the
  exclusion logic already exists in `learn.py`); the cockpit shows the current tier of who's
  home; **identity vectors never touch the bus or mesh.**

**Acceptance.**
- `tests/test_sealed_network.py::test_report_matches_guard_allowlist` — the report's claimed
  allowable-topic set is **byte-identical** to the guard's actual allowlist (no drift between
  promise and enforcement).
- `tests/test_dream_note.py::test_note_written_without_llm` — after a seeded night,
  `consolidate()` produces a non-empty, structured note naming at least one learned lesson and
  one uncertainty, generated even with no LLM.
- `tests/test_trust_tiers.py::test_guest_correction_does_not_learn` — a correction attributed
  to a `guest` actor does **not** mutate any tile's learned state, while a `household`
  correction does.

**Why last.** A visibility feature that renders an *unenforced* claim is worse than nothing —
it manufactures false confidence. Only after M5 (capability), M7 (positive schema), and M9
(confinement) are real can "Sealed Network" make a true statement.

---

### M11 — Nightly self-refresh: the home that maintains itself · [weeks]

**Goal (owner's standing wish).** At the end of every day, in the nobody-home / asleep window,
Homie runs ONE self-maintenance pass and wakes lighter, healthier, and up to date by morning:
it throws out what it no longer needs, heals what broke, upgrades itself when a vetted update is
ready, and restarts fresh on the latest healthy build. Self-sufficient, self-learning,
self-healing, self-upgrading — without the owner babysitting it.

**Why this is mostly completion, not invention.** `core/ritual.py::consolidate()` already
(decays + prunes the pattern of life, rotates/compacts the durability log, sweeps expired L4
faceprints, self-heals QUARANTINED/DEGRADED tiles, and returns an advisory `restart_decision`),
all behind abort gates (someone home / security live / gaming). M1 wired it in-process nightly.
M10 added the morning "what I learned / forgot" note. M11 finishes the loop: file/memory hygiene,
a real self-upgrade path, and actually enacting the end-of-day restart.

**Tasks.**
- **Hygiene — throw out the unnecessary.** Extend the consolidation pass to prune scratch/cache/
  temp files and orphaned tile state, vacuum the durability log, and drop fully-decayed memory
  keys — each bounded by an EXPLICIT retention rule, and each discard logged (the dream note
  already says "what I forgot"; this extends it to files). Never delete data without a named rule
  and a recorded line.
- **Self-heal.** Keep the existing reload sweep for quarantined/degraded tiles; add a health gate
  so an unrecoverable tile is left quarantined and surfaced in the morning note instead of
  crash-looping the daemon.
- **Self-upgrade (gated; panel-decided before building).** In the maintenance window, fetch the
  vetted update channel, BUILD the new system closure, and switch atomically ONLY if it builds and
  passes a smoke gate (the test suite + a boot/health probe) — else stay put. On Homie-OS (NixOS)
  this is uniquely safe: rebuilds are atomic and every prior generation is a bootable rollback, so
  a bad upgrade cannot brick the always-on brain (`nixos-rebuild switch` + generation rollback).
- **End-of-day restart.** Enact the Ritual's `restart_decision` (soft reconfigure or reboot) in the
  abort-gated window, so each day starts on the latest healthy build with a clear head.

**Key decisions (panel before building the upgrade path — `CLAUDE.md` rule):**
- Update channel + trust: signed git tag / pinned flake rev; who authorizes; unattended vs
  manual-approve. (Auto-pulling and running code on the home's brain is the one genuinely
  dangerous power here — the smoke gate + atomic rollback are what make it acceptable.)
- Smoke gate definition: exactly what must pass before a generation is committed.
- Cadence + abort gates: reuse `RitualGates` so maintenance never disrupts an occupied/secure/
  gaming home.

**Acceptance.**
- `tests/test_ritual_hygiene.py::test_prunes_decayed_and_reports` — a seeded night prunes
  fully-decayed memory keys + designated scratch files, reports what it discarded, and retained
  data survives a restart.
- `tests/test_self_upgrade.py::test_failing_build_leaves_generation_unchanged` — a failing build/
  smoke gate leaves the running version untouched (no in-place half-upgrade); a passing one is
  staged atomically.
- `tests/test_ritual.py::test_restart_only_when_gates_clear` — a restart is advised/enacted only
  when home/security/gaming gates are all clear.

**Anti-goals.** No fully-unattended pull-and-run without the smoke gate + rollback; no upgrade or
restart while the home is occupied, a security event is live, or the desktop is gaming; no deleting
data without an explicit retention rule and a logged record.

**Unblocks.** The "set it and forget it" promise — the home is a quiet appliance that keeps itself
correct, not a project the owner maintains.

---

## 5. The topology decision: why not three nodes (and the tripwire that flips it)

**The fork.** Keep `Pi(perception) + miniPC(HA anchor) + desktop(on-demand GPU cortex)`, OR
collapse the *brain* to one always-on node and keep the Pi only as a privacy-edge camera that
emits normalized events.

**Verdict (panel-settled): collapse the brain to one node. Keep the Pi ONLY as a privacy-edge
camera.** Run HA + the full Homie graph + the LLM on a single always-on Linux box — PLAN
Option 3 (Proton-on-the-3060) if your games allow, else a mini-PC anchor with the 3060 as a
wake-on-LAN GPU peer.

**Rationale.** The three-node mesh is the *source of the entire hard problem class the audit
found*:
- **C3** (priority-blind drop-oldest on the `**` mesh forwarder) — exists because there *is* a
  cross-node forwarder co-queueing safety with ambient.
- **C6** (the privacy guard has to be perfect) — exists *only because faceprints/embeddings
  cross a wire.* Single node → they never serialize → the guard degrades from a security
  boundary to a sanity check.
- **C4-style ordering races, partition/last-will/snapshot-reconnect complexity**, and an entire
  `deploy/mesh/` stack (NoiseLink / mDNS discovery / signed roster) that **is not yet built.**

A single brain node makes **mesh = loopback**: events never serialize, never cross a trust
boundary, never get dropped under backpressure. **You delete an unbuilt subsystem AND a class
of confirmed bugs in one move.** The cost is honest and small: the Pi still keeps raw frames at
the edge (the one privacy property genuinely worth a wire), and you lose "reasoning survives
while the desktop is in Windows" — which the **M3 wake-budget data tells you whether you
actually need.**

The keystone makes this reversible, not baked in: `build_daemon` assembles one in-process
graph; the `MeshTransport` seam means a config flag — *not* a rewrite — would switch to
multi-node.

**The tripwire that flips the decision** (any one, sustained):
1. **M3 wake cadence shows the GPU must be effectively always-resident** to meet the latency
   SLO (wakes are frequent and un-clustered), *and* the 3060 box must also be your gaming
   Windows box often enough that Proton-on-the-3060 can't hold the always-on role → then you
   need the cortex on a *separate* always-on node and the mesh wire returns.
2. **A second physical location / second home** enters scope (genuinely distributed presence).
3. **A second resident's privacy requires** that one node never sees another's raw stream →
   real cross-node isolation, real wire, real positive-schema guard as a *security* control.

If the tripwire fires: build `deploy/mesh/` (NoiseLink + discovery + signed roster), **and**
upgrade the M7 positive-schema guard from "sanity check" to "enforced security boundary"
(it is already the right shape — that is why M7 builds it now even on one node). Until then,
**do not build the transport.**

---

## 6. Learning roadmap: histogram → retrieval → maybe-never fine-tune

**The honest thesis.** For a single household, **retrieval + prompt-level preferences capture
~90% of the value at a fraction of the risk** of weight-tuning. Build the measurement; let it
earn the trainer — or kill it on evidence.

**Stage A — Histogram (exists, works).** `core/remember.py`'s `PatternModel` is a per-
`(topic,zone)` 24-element decayed event-mass vector with a 30-day half-life; `expectation()`
returns an events/day rate. Plus per-tile friction-driven suppression in the `learn.py`
handlers writing to tile state. **Both are real learning. Neither touches LLM weights.** This is
"continuous lightweight learning" and it is correct as-is. M1 fixes the C4 ordering so the
histogram's novelty signal is *honest*; M3 calibrates the wake gate against the histogram's real
per-home distribution instead of a magic constant.

**Stage B — Retrieval (M7, the Dream Journal).** The highest-leverage learning upgrade, and it
touches **no weights.** Turn the append-only log into recall: nightly episode summaries +
embeddings, top-k retrieval injected into `build_context`. Most of what people imagine
fine-tuning would buy is actually retrieval. Stored local-only, gated by the *fixed* privacy
guard (embeddings are the canonical leak vector — which is why M7 fixes the guard first).

**Stage C — The friction dataset PIPELINE, not the trainer (post-M1, accumulates over months).**
Once Act + StateReconciler are live (M1) and the ledger persists (M8), passively log every
`(proposal, action, reversal/remark, context)` tuple as candidate DPO-style preference pairs
into a curated, human-inspectable dataset with provenance. Ship a dashboard reporting pair
count and a noise metric. **Do NOT train anything.** Just accumulate and measure signal density.

**Stage D — Fine-tuning: a verdict, not a default.** The friction dataset is sparse (reversals
rare, remarks rarer), noisy, and confounded. Committing to a trainer now would overfit a handful
of ambiguous events and degrade a working base model. The disciplined position: **QLoRA/DPO is
justified ONLY if the dataset shows stable, repeated, low-noise preference pairs that retrieval
demonstrably fails to satisfy** — measured over months. Produce a written go/no-go from that
data, with the explicit, defensible option to **never train.** It stays on the roadmap (docs
already frame it as future Phase 7), off the critical path.

---

## 7. Risk register (tied to validated findings)

| ID | Finding (validated severity) | Risk if unaddressed | Mitigation milestone | Residual |
|----|------------------------------|---------------------|----------------------|----------|
| **C1** | Act/StateReconciler/Mesh/Ritual never wired in production; actuation + corrective loop dead (**critical**) | Homie cannot drive the home and never learns from reversals in production, while all tests pass | **M1** (`build_daemon` wires them unconditionally) | None once contract tests in M1 are green |
| **C2** | `ctx.emit` lets any in-process tile forge `actuator.requested` at any priority; only the act-map gates it (**high**) | A benign-looking tile silently asserts SAFETY priority or drives the lock | **M5** (capability tokens; Act verifies, stops trusting payload priority) | In-process trusted code only; obj-cap end state deferred |
| **C3** | Bus backpressure drops priority-blind (drop-oldest) on the `**` mesh forwarder (**high**) | A queued security/safety event silently evicted for newer ambient | **§5 topology collapse** removes the `**` forwarder entirely | Re-opens only if tripwire → multi-node; then revisit |
| **C4** | `run.py` attaches Remember *before* Supervisor → novel event masks its own novelty (**high**) | Security/Reason novelty detection silently defeated on first sighting | **M1** (Remember attached LAST) + `test_novel_event_not_self_masked` | None; locked by test |
| **C6** | Privacy guards are name+size blocklists; nested/non-blocklisted embeddings pass "impossible by construction" (**high**) | A faceprint/embedding crosses a wire | **M7** (positive per-topic schema, recursive) | On single node it's a sanity check; the *boundary* version exists for the tripwire |
| **C7** | Stremio ships `--no-sandbox` + `QTWEBENGINE_DISABLE_SANDBOX=1` as the data-owning `homie` user (**high**) | Renderer RCE from a malicious addon lands with full read of the pattern-of-life log | **M9** (sandbox re-enabled, dedicated unprivileged user, confinement profile) | Honest residual: confinement ≠ neutralizing unsandboxed-Chromium RCE; future fork = move renderer off the box |
| **C8** | Wake gate has no rate limiter/budget; "~95% asleep" never measured (**high**) | Cold-start wake-storm for weeks; the always-on energy premise is unfalsifiable | **M3** (WakeLedger → calibrated quantile → enforced token-bucket budget) | Bounded + reported as a real number |
| **C9** | tty1 autologin as `homie`, no lock; console reads `/var/lib/homie` (**medium**) | Brief physical access after boot → presence log | **M9** (remove autologin / idle-lock; user split; key-only wheel-less ssh) | None for console path |
| **C10** | Mesh issue at mesh.py:118–135 (**medium**) | Cross-node defect | **§5 collapse** defers; revisit only on tripwire | Deferred |
| **C11** | `Perceive.run`, `Interface.say/listen/friction_from` are `...` stubs; remark has no production producer (**high**) | The entire sensory-in / voice-in edges are unwired in production | **M2** (`Perceive.run` real intake); voice ships as text on `chat.reply` (M0/M4/M10); `friction_from` later | Real audio is hardware-gated, deferred |
| **C12** | No weight-learning anywhere; "fine-tuning" is docs-only (**low**) | Gap vs vision, *not a bug* | **§6** keeps it future; M7 retrieval captures most value | Intentional |
| **C13** | Nightly ritual + systemd timer don't exist; richer `consolidate()` wired only to tests (**medium**) | Headline "nightly reflection" feature unwired in production | **M1** (in-process nightly `consolidate()` — no second-process log race) + **M10** (the dream-note artifact) | None; the documented data-loss race is avoided by design |
| **C14** | `light.living` (tile) vs `light.living_room` (act-map) mismatch (**low**) | Living-room light command refused once Act is live (1 of 4 rooms) | **M5** (one-token alignment, in the same change as the capability work) | None |
| **C15** | Docs say "169 tests"; true count 225 (**low**) | Cosmetic doc drift | Corrected **in each milestone** that touches a doc citing the count | None |

---

## 8. Anti-goals / deferred (do NOT do these now)

- **Do NOT build `deploy/mesh/` (NoiseLink, mDNS discovery, signed roster).** It is unbuilt,
  it is the source of the C3/C6/partition problem class, and the single-brain topology removes
  the need until the tripwire fires. Building it now commits to three-node complexity before
  the M3 wake data justifies it.
- **Do NOT begin QLoRA/DPO/any weight tuning (C12).** Sparse, noisy, confounded data; training
  now overfits a handful of ambiguous reversals and degrades a working base model. Build the
  dataset + measurement (Stage C); let evidence authorize a trainer — or kill it.
- **Do NOT ship a separate-process nightly ritual (`ritual.sh` + systemd timer).** It
  re-introduces the documented `events.jsonl` second-process data-loss race. The in-process
  `consolidate()` (M1) achieves the feature without the race.
- **Do NOT add a priority-aware delivery path / priority field to `Event` to chase C3/C4
  generically.** The cheap correct fixes dominate: attach Remember last (M1), collapse the `**`
  forwarder out of existence by going single-node (§5). A priority-typed bus is a large rewrite
  solving a problem the topology decision erases.
- **Do NOT make the privacy guard cryptographically complete on a single node beyond the
  positive schema (M7).** On one brain node, embeddings never cross a wire; over-hardening a
  control whose threat model you're deleting is wasted effort. The schema is the right shape and
  ready for the tripwire — that's enough.
- **Do NOT keep the 8B resident in VRAM 24/7 "for latency."** That silently re-creates the
  always-on power cost the tiering exists to avoid. Let M3's measured cadence justify any
  warm-residency; never assume it.
- **Do NOT enforce the wake budget on safety-topic or chat wakes.** A budget that can starve a
  safety evaluation or leave a direct question unanswered is worse than no budget.
- **Do NOT build a general-purpose tile permission UI / policy DSL.** The manifest/TOML is the
  single grant surface; per-actuator capabilities + per-topic schemas reuse it. A policy
  language is over-engineering before a second consumer needs it.
- **Do NOT let the "What Homie Knows" / "Sealed Network" views ship before their enforcement is
  real (M5/M7/M9 first).** A view that displays an aspirational guarantee converts an honest gap
  (a docstring) into a confident lie (a UI).
- **Do NOT add voice I/O, faceprint recognition, or richer Remember structures (sequences/
  sessions) for the felt arc.** Ship spoken moments as text on `chat.reply`; coarse presence
  labels for trust tiers; the existing per-`(topic,zone,hour)` rate carries the dream note. Let
  the dream note reveal which structure is actually missing.
- **Do NOT chase C15 doc drift as its own task.** Correct it inline whenever a milestone edits a
  doc that cites the count.

---

## 9. The felt-experience arc (first goosebumps → magical)

The owner should feel, within a week of living with it, that Homie **listens, remembers the
shape of their days, owns its mistakes out loud, and can always be corrected** — and can prove
each of those four feelings with something they can see or hear.

| When | The moment | Milestone | What the owner feels |
|------|-----------|-----------|----------------------|
| **First** | **The typed line never vanishes.** Type "are the doors locked?" on the bare Pi and get an honest reply in ~1s — status from memory, or "I'm the anchor right now; the thinking node is asleep — here's what I know." | **M0** | *It listens.* Never silence, never fake-smart. The floor of aliveness. |
| Then | **The light obeys, and the undo lands.** A tile drives one real light on arrival; you flip it back; the reversal flows home as friction. | **M1** | *It acts — and I'm in control.* The loop is live, blast radius is one light. |
| **Goosebumps** | **The hour-shaped lesson, spoken back.** After you've corrected it a couple times: "Got it — I'll stop lighting the kitchen around 7pm." | **M4** | *It remembers the shape of my days.* The home audibly admits it learned a specific thing about *this* household. The first magical moment. |
| Then | **The Friction Ledger + one-key undo.** A scrollable column of plain sentences — "6:58pm — turned on hallway light · you turned it back off · I'll remember" — one keypress overrules and teaches. | **M8** | *It owns its actions, and I can always overrule it.* Trust from reversibility. |
| Then | **The morning-after dream note.** Each morning, one short note: what it noticed, learned, and is unsure about. Written even if the GPU slept. | **M10** | *It was thinking about us.* An inner life that spans days — reactive gadget becomes household member. |
| Last | **Trust tiers, surfaced.** The note and ledger say *who*; lessons learn only from household actors; the cockpit shows who's home and at what tier. Coarse labels, no faceprints, no vectors on the wire. | **M10** | *It knows the household — and respects its limits.* Personal without being invasive. |
| Ongoing | **The nightly self-refresh.** Each night, unseen, it tidies (throws out what it no longer needs), heals broken tiles, upgrades itself when a vetted build is ready, and restarts fresh — then tells you in the morning note what it cleaned, fixed, and updated. | **M11** | *It takes care of itself.* You wake to a home that is lighter, healthier, and newer than you left it — a quiet appliance, not a project you maintain. |

Design rules for the arc (panel-settled): the anchor answers **immediately from Remember** for
status/pattern questions and **explicitly defers** reasoning-shaped ones — felt honesty beats
latent cleverness. Speak the **first** time a `(room,hour)` lesson forms; summarize repeats in
the dream note. An explicit undo counts as a **remark-grade** (strongest) correction, and the
owner **sees** the teaching happen ("· I'll remember"). The dream note is **template-first** so
it exists every morning regardless of whether the cortex woke; the desktop may rewrite it more
warmly when already awake. Identity is a **coarse presence label**, earned-up only if coarse
labeling visibly fails. And every "spoken" moment ships as text on `chat.reply` first — real
audio rides the **same** `interface.say` events later without redesign.

---

## Second-review addendum (2026-06-27)

A second independent Claude reviewed **`main`** (the pre-keystone codebase) and the full
memo is at `docs/audits/2026-06-27-second-review.md`. It confirmed the first audit's core and
the keystone, and added eleven findings. How they slot in:

- **Already closed on this branch:** the `run.py`/`spine_demo` divergence + missing Act/
  reconciler (the reviewer's "one thing") — **M1**; C4 attach-order — **M1** (plus the
  one-tick commit defer the reviewer's note didn't anticipate); self-heal now has a production
  caller via `consolidate()` in `_housekeep` (N2) — **M1**; a golden-days corpus (N-brainstorm
  #1) — **M2** (`core/scenarios.py`).
- **New, scheduled below as M2.5 (the clock):** N1 (no scheduler/tick), N4 (hardcoded dusk).
- **Folded into existing milestones:** N3 (emit bypass also hits SubprocessChannel + is
  unattributable; capability token must be **topic-scoped**) → **M5**; N5 (echo exact-match
  mislearns dimming transitions → tolerance band) → **M5-adjacent**; N6 (friction wall-clock
  breaks replay determinism) + N7 (three "hour" notions; set `HOMIE_TZ` in the unit) →
  **M2.5/M5** clock-domain unification; N10 (Consent is a 30s dead-end — needs a cockpit Y/N
  `confirm.response` producer) → **M8**; N9 (split daemon/login users, SSH behind WireGuard) →
  **M9**; N8 + N11 (mesh single-hop contradicts the star topology; out-of-order decay skew) →
  **§5** evidence that the mesh as drawn doesn't even work — *answer "why three nodes" first*.
- **Brainstorm adopted into the roadmap:** confidence-gated autonomy via `Expectation.days`
  (#5), rhythm fingerprinting + stranger-by-behavior (#6/#7, the security pillar's first rung
  before any faceprint), the cockpit "why" pane (#12, extends M8's Friction Ledger), a panic/
  privacy hard switch at `assert_emittable` (#13), the three-tier model cascade (#14, refines
  M6), and threading Remember context into the **cortex** chat path (a real bug — M0's anchor
  already answers from Remember, the cortex path does not).

### M2.5 — Time as a first-class event: the clock the system lacks · [days]

**Goal.** Give Homie a heartbeat. Today it is purely event-reactive: every "after N minutes /
at dusk / each morning" behavior secretly depends on an *unrelated* future event arriving — and
in a genuinely empty room none does, so the lighting auto-off never fires (N1). This is
structural, not a tile bug, and it underlies auto-off, security cool-downs, and dusk (N4).

**Tasks.**
- A stdlib `Clock` producer (new `core/clock.py`) wired in `build_daemon`: emits `tick.minute`/
  `tick.hour` and serves a `timer.set(after=…)` → `timer.fired` seam so a tile can schedule
  future work without polling. Injectable time source so tests stay deterministic.
- Solar `sun.dusk`/`sun.dawn` events from the home's lat/long (a ~30-line stdlib sun-position
  calc — no deps); Lighting subscribes instead of hardcoding 18:00 (N4).
- Unify the clock domain (start): set `HOMIE_TZ` in the systemd unit and centralize hour-of-day
  on the one pinned zone so Remember, Lighting, and `learn.py` can't disagree (N7); begin
  threading an event-derived time through the friction path so it's replay-deterministic (N6).
- Rework Lighting's auto-off to a `timer.set` on vacancy (fires even in a silent room).

**Acceptance.**
- `tests/test_clock.py::test_timer_fires_in_empty_room` — arm an auto-off via `timer.set`; with
  NO further zone events, `timer.fired` arrives and the light goes off (the exact N1 bug).
- `tests/test_sun.py::test_dusk_tracks_latitude` — dusk for a summer vs winter date at ~54°N
  differs by hours; Lighting's dark-gate follows it, not a constant.

**Unblocks.** Auto-off, cool-downs, dusk, "each morning" behaviors, and the dream-note cadence —
all the time-shaped behavior the rest of the plan assumes exists.

## Sequence at a glance

```
M0  [hours]      Pi-anchor chat fallback (never silent)            → proof-of-life
M1  [days]       KEYSTONE: build_daemon + contract/golden tests    → C1, C4, C13(in-proc)
M2  [days]       Synthetic-perception harness + Perceive.run       → C11 intake; test substrate
M2.5[days]       The clock: tick/timer + solar dusk                → N1, N4 (time passing)
M3  [days]       Wake telemetry → calibrate → enforced budget      → C8; topology input
M4  [days]       Hour-shaped lesson, spoken back                   → first goosebumps
M5  [weeks]      Capability-gated act path                         → C2, C14
M6  [weeks]      8B-on-3060 serving discipline                     → cortex SLO
M7  [weeks]      Positive-schema guard + Dream Journal (retrieval) → C6; learning Stage B
M8  [weeks]      Friction Ledger pane + one-key undo               → felt control; dataset feed
M9  [days–wks]   Deploy posture + confinement                      → C7, C9
M10 [weeks]      Visible posture + dream note + trust tiers        → C13 artifact; the payoff
M11 [weeks]      Nightly self-refresh: hygiene·heal·upgrade·restart → self-sufficient appliance
```

**The one rule to remember if you forget everything else:** there is exactly one wiring of
Homie, it lives in `build_daemon`, and a green suite is a proof the shipped home works *only*
because production runs that same graph. Protect that invariant above all.
