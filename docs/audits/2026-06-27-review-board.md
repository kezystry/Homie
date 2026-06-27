# Homie External Review Board — Synthesis Memo (2026-06-27)

*Produced by a 19-agent audit workflow: 7 subsystem mappers, 6 role-played domain
auditors (distributed systems, ML/LLM research, security/privacy red-team,
embedded/NixOS, software architecture, product/vision), 4 brainstorm sets, an
adversarial red-team, and a chair synthesis. Every load-bearing claim was verified
against the code at `claude/homie-overview-bo4l8v` — not taken on the docs' word.*

---

## 1. Verdict

Homie is an **exceptionally well-engineered torso with no senses, no hands, and no
voice, that has never been assembled and run as a single living system.** The
reasoning spine — `core/bus.py`, `core/tile.py`, `core/remember.py` — is genuinely
strong, disciplined, stdlib-only software with 225 behavior-asserting tests (the docs
undercount this as 169). But the production daemon `scripts/run.py` and the thing that
is actually tested-as-alive, `scripts/spine_demo.py`, are **different programs**. Act,
StateReconciler, Mesh, and Ritual are wired only in the demo. Perception in
(`core/perceive.py:46` — `run` is `...`) and voice in/out (`core/interface.py:11-17` —
three `...` bodies) are stubs. There is no `HomeClient` implementation, only a
Protocol. Boot `run.py` on real hardware and walk through your front door: nothing
perceives, nothing acts, nothing learns, and a typed message into the Pi floor returns
silence. The code is honest — its comments admit fragility the prose hides. The **docs
are written in the present indicative of an organism that exists only in a demo script
with a `FakeHome`.** That tense gap is the central finding of this review.

---

## 2. What's genuinely strong (protect this)

- **Crash-safe durability.** `DurabilityLog.compact` (`core/bus.py:197-221`) is
  textbook: rotate → write snapshot to `.tmp` → fsync → atomic `os.replace` → fsync
  dir → *then* unlink the covered segment. Generation-numbered recovery means a crash
  at any point neither loses nor double-counts.
- **Tile isolation that actually isolates.** Throwing handlers harm only their own
  mailbox (`bus.py:334-342`); the Supervisor's windowed fault→restart→quarantine→
  `drop_owner` is a proper supervision tree; `InvalidManifest`-as-value means one bad
  tile never aborts discovery. The "core never imports a tile" invariant holds.
- **The untrusted-model boundary is placed correctly.** `validate_tool_call`
  (`core/reason.py`) rejects hallucinated names/args before execution; Reason holds no
  actuator path of its own; `deploy/llm.py` collapses *every* failure to `Proposal()`
  (do nothing) and is stdlib-only so the Pi anchor never imports network code.
- **Echo-canonicalization as a single injected source of truth.** `ha_canonical` is
  shared (not copied) into `CommandLog`; record-before-drive (`act.py:185`) closes the
  echo-beats-record race. `PrivacyGuard.FORBIDDEN` is *imported* by `perceive.py` and
  `cockpit_bridge.py`, not duplicated.
- **Cockpit security posture.** Default-deny both directions; inbound restricted to
  exactly `chat.message` with `source` forced to `cockpit`; 0600 unix socket;
  no-shell-anywhere launcher (fixed argv, asserted by test). A malicious local client
  genuinely cannot drive an actuator.
- **The topology split is one clean env var.** No `HOMIE_LLM_URL` → `deploy.llm` is
  never imported. The Pi floor carries zero serving dependency.

---

## 3. Top risks, ranked (code-backed only)

| # | Risk | Severity | Where | The fix |
|---|------|----------|-------|---------|
| 1 | **The production daemon runs no friction loop, no Act, no perception.** `run.py` wires Bus+Remember+Consent+Supervisor+Reason+Cockpit and stops. A tile's `ctx.act` publishes `actuator.requested` with **no consumer**; no `StateReconciler` means **no human reversal is ever observed → no tile ever learns**. The headline "learning home" is demo-only. | **Critical** | `scripts/run.py:80-110` vs `scripts/spine_demo.py:80-86` | Refactor wiring into one `build_daemon(bus)`; `run.py` and `spine_demo.py` both call it. One end-to-end test on the production graph. |
| 2 | **`ctx.emit` bypasses the actuator permission gate entirely.** `TileContext.act` checks `actuator in manifest.actuators` (`tile.py:214-217`); `TileContext.emit` (`tile.py:220`) applies **no topic filter**. Any in-process tile can `emit(Event('actuator.requested', …, {'actuator':'light.bedroom','priority':'safety'}))`. Act authorizes only on the act-map and reads `priority` straight from the payload (`act.py:162`) — so a tile can drive **any mapped actuator at any priority, including self-escalating to SAFETY** to win arbitration. The manifest allowlist is decorative. | **Critical** | `tile.py:220`, `act.py:162` | Mint a per-act capability token in the Supervisor's `ctx.act` (HMAC over actuator+tile+priority+nonce, key held only by the Supervisor); Act rejects any request lacking a valid token or whose token's tile/priority don't match the owning manifest. |
| 3 | **Drop-OLDEST backpressure can silently discard a SECURITY/SAFETY event under load.** On `QueueFull`, `publish()` evicts the head and keeps the newest (`bus.py:254-256`), incrementing only a `dropped` int. Arbitration is priority-aware; mailbox eviction is **priority-blind**. A motion-storm into a slow consumer evicts an older `security.alert` in favor of newer ambient noise. | **High** | `bus.py:254-259` | Drop **lowest-priority** queued event, never SECURITY/SAFETY in favor of AMBIENT; emit a rate-limited `bus.backpressure` event so loss is visible in the cockpit. |
| 4 | **Evaluate-then-commit ordering is a comment on an unordered primitive — and `run.py` gets it backwards.** Remember must commit *after* anomaly consumers evaluate, or an event masks its own novelty. `run.py:85` calls `remember.attach(bus)` **before** `sup.start_all()` (`:89`), so Remember drains first — Security recalls a history that already includes the current event. | **High** | `remember.py:215-224`, `run.py:85-89` | Cheap correct fix first: attach Remember *last*, with a test asserting order. Do **not** build a two-phase bus barrier yet. |
| 5 | **Subprocess "isolation" provides no confinement and loses the safety affordances.** `SubprocessChannel.start` spawns an ordinary child with full env (`tile.py:468`), unrestricted network, full FS read of HOMIE_STATE. No netns/seccomp; `egress:<host>` is parsed but never enforced. Meanwhile `tile_harness._make_ctx` stubs `recall()`/`confirm()` to raise — so the egress/untrusted tiles that most need the consent gate **can't reach it**. | **High** | `tile.py:458-469`, `tile_harness.py:52-56` | Build one confinement layer (bubblewrap or `systemd-run --user` transient unit). Reuse it for Stremio (risk #7). Forward `recall`/`confirm` over the harness stdio protocol. |
| 6 | **PrivacyGuard is a keyword+bytecount heuristic sold as "impossible by construction."** Blocks only FORBIDDEN words as topic segments / top-level payload keys + a 4096-byte cap. A 128-float embedding under `payload['features']` (key not forbidden, under 4 KB, nested dicts not recursed) **passes** both the mesh guard and `assert_emittable`. | **High** | `mesh.py:52-68`, `perceive.py:27-42` | Replace denylist with a **positive per-topic schema** enforced at the perception source and the mesh boundary. A faceprint has no schema → cannot be expressed. Fix the docstring now regardless. |
| 7 | **Stremio renderer is an unconfined RCE foothold as the data-owning user.** `apps.nix:49-50` exports `QTWEBENGINE_DISABLE_SANDBOX=1` + `--no-sandbox`. Embedded Chromium renders attacker-controllable addon/stream content as the `homie` user — the same user that owns the pattern-of-life log and is in `wheel`. | **High** | `os/boot/apps.nix:49-53` | Confine `homie-watch` under the §5 sandbox: distinct low-priv uid, no HOMIE_STATE, seccomp. |
| 8 | **The novelty wake gate inverts under cold-start and sparsity.** `should_wake` (`reason.py:123`) returns True on `novel OR rate < 0.1`. Every unseen `(topic,zone)` is novel → on a fresh box for ~a month the GPU wakes on essentially **every** event. No rate limiter, no budget, no cooldown. The "GPU asleep 95%" claim is asserted, never measured. | **High** | `reason.py:71,119-123` | Continuous `surprise = -log(smoothed P(event|topic,zone,hour))` with a cold-start prior; gate on a self-calibrating percentile tuned to a nightly wake budget; emit wake-rate telemetry. |
| 9 | **Autologin + bootstrap password-SSH + homie-in-wheel = passwordless path to a burglary-grade log.** `configuration.nix:58` autologins `homie` on tty1; `ssh.nix:24` leaves `PasswordAuthentication = mkForce true`; `ssh.nix:28` puts homie in `wheel`. Once booted+unlocked, brief physical access hands over the full presence log. | **Medium** | `configuration.nix:53-58`, `ssh.nix:24-28` | Drop autologin or add a console idle-lock; split the media/cockpit user from the daemon's data-owning user; startup warning when bootstrap password-SSH is still on. |
| 10 | **Mesh inbound trusts peer frame structure; no schema, no origin-authenticity.** `_on_remote` does `Event(**frame['event'])` (`mesh.py:131`) with zero validation. Rests entirely on a Noise-IK transport **that does not exist in the repo.** Single-hop star, `ttl` never decremented, no store-and-forward. | **Medium** | `mesh.py:102-135` | Defensive parse + positive schema at the mesh boundary; bind each node to a topic namespace. **But first ask whether the mesh is needed at all.** |

**Hygiene (first hour):** delete `tests/__pycache__/test_llm_TEMP.cpython-311.pyc` (no
source); fix the test count to **225** in `README.md`, `CLAUDE.md`, `docs/OVERVIEW.md`,
`docs/BACKLOG.md`; `act_map.toml` maps `light.living_room` but the tile drives
`light.living` — every lighting command would be refused the moment Act is wired.

---

## 4. The gap between dream and build

- **"Homie learns / notices / sleeps and dreams"** (present tense) → the entire
  perceive→remember→reason→**act**→learn loop has **never executed against the real
  bus.** It lives only in `spine_demo.py` with a `FakeHome`.
- **"Voice-first I/O"** → `interface.py` is three `...` bodies. The `remark` signal —
  the docs' strongest correction channel — has **zero producers anywhere.**
- **"Continuous lightweight learning" + PLAN Phase 7 "QLoRA fine-tune"** → grep for
  qlora/finetune/dpo/adapter returns **nothing.** "Learning" is exclusively a decayed
  event-frequency histogram. The model weights never change.
- **The 4-tier identity ladder (SECURITY.md headline)** → **zero code.** The only
  enforcement is the FORBIDDEN denylist.
- **Ritual — the nightly "sleep" beat** → `core/ritual.py` claims a systemd timer fires
  `scripts/ritual.sh`. **That file does not exist.** `run.py`'s `_housekeep` does a
  lesser inline decay+compact. Two divergent consolidation paths, one tested-but-dead.
- **`StateReconciler.context` (per-person learning + guest-exclusion)** → wired
  end-to-end but never passed in `run.py` or the demo, so `zone`/`actor` are always
  `None`. The "never train on a guest" rule has no actor to exclude.
- **Three non-reconciled phase schemes** across ROADMAP / WALKTHROUGH / STAGES. The
  cockpit (5 test files, shipped) is **invisible** to OVERVIEW/DESIGN/ARCHITECTURE.

---

## 5. The brainstorm — best 8 ideas

1. **Synthetic Senses (`HOMIE_FAKE_PERCEPTION=1`) wired into the *real* daemon.** The
   single highest-leverage move. Forces `run.py` and `spine_demo.py` to reconverge and
   becomes the acceptance harness for when real perception lands.
2. **The hour-shaped lesson, said back to you.** `lighting/learn.py` already writes the
   *hour* into `state['suppressed'][room]`. Have it speak the boundary of the rule it
   learned: *"You've switched the living-room light off the last two evenings around
   nine — I'll stop turning it on then, but keep the mornings."*
3. **The Friction Ledger — a "Homie learned" feed you can shove back on.** A cockpit
   margin: one calm sentence each time the loop mutates tile state; Enter = UNDO.
4. **Calibrated surprise budget replacing the binary wake gate.** Fixes risk #8 and
   turns "GPU asleep" into a measured SLO.
5. **The asleep-fallback: never let a typed line vanish.** A stdlib Pi-floor responder
   that answers from Remember directly and queues hard questions for the big model.
6. **Dreams: the morning-after note from nightly consolidation.** Wire the orphaned
   `consolidate()` into production; diff pre/post-decay Remember to surface one quiet
   line of what Homie *forgot* while you slept.
7. **🌶️ WILD — The Dream Journal.** During Ritual's nobody-home window, replay the
   day's log and write back natural-language *episodes* to `episodes.jsonl`; next day's
   chat retrieves from it. Exploits the one thing the cloud throws away: a complete,
   private, crash-safe local log the model is allowed to read in full. **Retrieval, not
   weight training** (per the dissent).
8. **🌶️ WILD — Trust Tiers for the household, expressed as behavior not faceprints.**
   Each resident full/limited/guest; a guest's events are observed for security but
   excluded from learning — finally populating the `zone/actor` context the reconciler
   already carries but nobody passes.

---

## 6. If I had 2 weeks

- **Day 1 — hygiene + honesty:** delete the stale `.pyc`, fix `169→225` everywhere, fix
  `act_map.toml` `light.living_room→light.living`, rewrite the false "impossible by
  construction" docstring to "defense-in-depth heuristic."
- **Days 1–4 — one body, one breath (keystone):** extract `build_daemon(bus)`; wire
  Act, StateReconciler (with a real `context`), and `consolidate()` into it; add
  `HOMIE_FAKE_PERCEPTION=1` into the real daemon; **write the one missing test** —
  resident walks in → tile acts → Act drives a `FakeHome` → reconciler observes a
  reversal → tile state on disk shows it learned. *Until this is green, nothing else
  matters.*
- **Days 4–6 — make the floor real:** Remember-attached-last ordering fix (risk #4);
  priority-aware backpressure (risk #3); Pi-floor chat fallback (idea #5).
- **Days 6–9 — close the two authority holes:** capability-token actuator authority
  (risk #2); per-topic positive payload schema (risk #6).
- **Days 9–12 — legible learning + measurable brain:** hour-shaped lesson + Friction
  Ledger; surprise telemetry (observe phase only).
- **Days 12–14 — deploy honesty + ethos:** pin the NVIDIA driver build + commit
  `flake.lock`; `nix flake check`; drop autologin / add console lock; wire Ritual into
  production with the morning-after note.

**Explicitly deferred (the dissent earns its place):** no two-phase bus barrier (the
one-line "Remember last" fix is the whole correct fix); no QLoRA loop (the friction
dataset is a trickle of noisy, unattributed labels — the histogram is the right tool
for this data regime; ship the Dream Journal retrieval instead); no CRDT mesh / Noise
transport yet — **first answer the open question the design assumed away: why three
nodes?** A single mini-PC-plus-GPU eliminates the entire partition/relay/ordering
problem class. Decide it in a panel before investing in distributed-systems machinery.

---

## 7. The one thing

**Highest-leverage move:** Collapse `run.py` and `spine_demo.py` into one
`build_daemon()`, wire `HOMIE_FAKE_PERCEPTION=1` into the *real* daemon, and write the
**single** end-to-end test that walks a synthetic resident through the front door and
asserts a real light turned on and a real reversal was learned — *on the production
graph.* The pieces all exist and are individually tested; **nothing proves they
compose.** That one green test converts Homie from "tested in pieces, assembled in a
demo" into "the production graph is the tested graph," and makes `run.py`/`spine_demo.py`
drift impossible by construction.

**The thing the project is lying to itself about:** that it is *a working system with
integration gaps*, when it is *a beautifully-tested set of components that has never run
as a system even once.* The lie is not in the code — the code is honest, often more
honest than the prose. **The lie is in the verb tense.** The honest one-sentence status
the docs refuse to write:

> *Homie is an exceptionally well-engineered torso with no senses, no hands, and no
> voice, that has never been assembled and run as a single living system — and we are
> debating CRDT mesh layers and nightly QLoRA dreams for an organism that cannot yet
> turn on a light when you walk in the door.*

Write that sentence into `OVERVIEW.md`. Then go make the test in §7 green. The torso is
exquisite. Give it one breath before you teach it to dream.
