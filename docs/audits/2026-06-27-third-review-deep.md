# Homie — Deep Audit of the Working Branch (`claude/homie-overview-bo4l8v` @ `e8450b3`)

*Third external review. The prior two audited `main` / the original 225-test codebase; their
findings are now mostly closed and that work is real. **This audits the ~5,900 lines of new
code those reviews never saw** (M0–M5 + the Home Assistant adapter), verifies every prior
finding's status at file:line, and reports what is now the weakest link. Suite: **325 green,
Python 3.12.** Minimal by intent — every line is load-bearing.*

---

## 1. Closure ledger — every prior finding, verified

`C#` = first audit's risk register; `N#` = second review. Status checked in code, not docs.

| ID | Finding | Status | Evidence |
|----|---------|--------|----------|
| C1 | run.py/spine_demo divergence (Act/reconciler/ritual unwired) | **Closed** | `core/daemon.py` is the one graph; `test_golden_loop` fails if any is unwired |
| C2 | `Act` trusts payload actuator+priority (escalate via raw emit) | **Closed** | `act.py:165-184` resolves a registry handle, ignores payload; forged/missing `cap` refused. Honest in-process caveat documented in `capability.py:16-21` |
| C3 | Priority-blind drop-oldest backpressure | **Open** | `bus.py` untouched on this branch; head-drop still priority-blind |
| C4 | Evaluate-then-commit ordering (Remember must lag) | **Closed** | `daemon.py:143-145` attaches Remember last; `test_daemon_wiring` asserts it |
| C5 | Subprocess channel: no OS confinement | **Open (M9)** | handle hardens the emit-forward, but no netns/seccomp yet |
| C6 | PrivacyGuard denylist heuristic (non-recursive) | **Open (M7)** | positive-schema guard is planned, not built |
| C7 | Stremio renderer unconfined RCE as `homie` | **Open (M9)** | `apps.nix` flags unchanged |
| C8 | Wake gate inverts on cold start, never measured | **Closed** | `wake_ledger.py`: per-zone calibrated `SurpriseGate` + event-clocked `WakeBudget` + `WakeLedger` (asleep-fraction is a real number) |
| C9 | Autologin + opt-in password-SSH + `homie`∈wheel | **Open (M9)** | base config hardened; `ssh.nix` still the risk for this deployment |
| C10 | Mesh inbound no schema; Noise transport absent | **Open** | `mesh.py` untouched |
| C11 | Perception is a stub | **Partial** | intake seam real (`Perceive.run` + `SyntheticPerception`, M2); the **live camera/Frigate adapter is still unbuilt** |
| C13 | Two divergent consolidation paths; `ritual.sh` missing | **Closed** | `daemon.py:167-186` runs `consolidate()` in-process; no second writer |
| C14 | `act_map` `light.living_room` vs tile `light.living` | **Closed** | `ROOM_ACTUATOR` alias (`lighting/handlers.py:28`) + map fixed |
| N1 | No scheduler → empty-room auto-off never fires | **Closed; reopens on restart** | `clock.py` timer seam; lighting arms `timer.set` (`handlers.py:107-112`). But timers are in-memory (`clock.py:53`) → a restart drops them (see NEW-5) |
| N2 | Self-heal unwired in production | **Closed; gating critique stands** | `consolidate()` now wired; but heal is still fenced behind the abort gates (`ritual.py:113-134`), so a quarantined tile in an occupied home still won't recover until empty |
| N3 | emit bypass defeats subprocess containment + invisible to friction | **Closed** | a capless `actuator.requested` is refused, so it can't drive at all — the invisibility concern is moot |
| N4 | Hardcoded 18:00 dusk wrong at 54°N | **Fixed in code; DORMANT** | `sun.py` correct; but `HOMIE_LAT/LON` are commented out (`configuration.nix:102-103`) → `_location()` returns None → the box runs the 18:00 fallback **today** |
| N5 | Friction mislearns from dimming transitions | **Open — now live** | `take_echo` still exact-match (`act.py:127-130`); HA emits `state_changed` per attribute, so every ramp intermediate is a phantom human change for the 4 mapped lights |
| N6 | Friction path uses wall-clock (breaks replay determinism) | **Open** | `reconcile.py:52`, `tile.py` act-sink, `act.py:222` still `time.time()` |
| N7 | Three notions of "hour" | **Closed by config; latent in code** | unit sets `HOMIE_TZ` (`configuration.nix:98`); but `lighting`/`learn` still use host-local `datetime.fromtimestamp` (`handlers.py:36`, `learn.py:16`) — agrees **only while `time.timeZone == HOMIE_TZ`** |
| N8 | Mesh single-hop, contradicts the star topology | **Open — now a blocker** | `mesh.py` untouched; owner **kept 3 nodes** (MASTERPLAN §5), so a hub that can't relay is no longer deferrable |
| N9 | LAN password-SSH → wheel acct owning the log | **Open (M9)** | unchanged |
| N10 | Consent is a 30s dead-end (no response producer) | **Open** | gesture/voice still stubs; `AnchorVoice` answers *chat*, not `confirm.response` |
| N11 | Out-of-order events corrupt decayed mass | **Open** | `remember.py` observe-path unchanged; now also corrupts the wake budget (NEW-8) |

Net: **C1, C2, C4, C8, C13, C14, N1, N2, N3 closed; N4/N7 closed-but-fragile; the rest map to M6/M7/M9 or are untouched.** The two worst findings (C1, C2) are genuinely dead.

---

## 2. New findings — in the code no review has seen

Ranked. All verified at file:line on this branch.

| # | Finding | Sev | Where | Fix |
|---|---------|-----|-------|-----|
| **NEW-1** | **`drive()` reports false success on an HA-level failure.** `HomeAssistantClient.drive` sends `call_service` and returns without awaiting HA's `result` (`ha.py:160-177`); `_dispatch` drops every non-`event` message (`ha.py:249-251`), so the `result` is discarded. Act's failure branch only fires if `drive` **raises** (`act.py:207-215`). So if HA rejects the call (entity unavailable, bad service), no exception → Act records the command in the CommandLog as driven, emits no `actuator.failed`, and the (absent) echo never matches → the command is silently swallowed. **The home didn't change; Homie believes it did, and the friction loop is none the wiser.** | **High** | `ha.py:160-177, 249-251`; `act.py:207-215` | Correlate the `call_service` `id`; on `result.success == false`, raise (or emit `actuator.failed`). Keep a pending-by-id map. |
| **NEW-2** | **No liveness heartbeat → silent deafness on a half-open socket.** `ws.py:recv_text` blocks on `readexactly` with no timeout; the client only *answers* HA's pings, never sends its own (`ws.py:179-183`); `_run` reconnects only when `recv()` **raises** (`ha.py:214-219`). A half-open TCP (router reboot, NAT idle-timeout, HA host sleep — none send FIN/RST) blocks `recv()` forever, no exception, **no reconnect.** Homie stops hearing human switch-flips with no recovery short of a daemon restart — and the whole reconnect-with-backoff machinery is never reached. | **High** | `ws.py:171-188`; `ha.py:214-231` | Send HA's app-level `{"type":"ping"}` every ~30s; reconnect if no `pong` inside a deadline. Minimum: `wait_for(recv())` + `SO_KEEPALIVE`. |
| **NEW-3** | **Nightly self-update defends against bugs, not a compromised upstream.** `selfupdate.decide` gates a restart on the **pulled code's own** test suite passing (`selfupdate.py:29-42`). An attacker who can push to the branch (or a supply-chain compromise) controls both the new code and the tests that bless it — ship a trivially-green suite and "healthy" means nothing. M11 auto-runs this nightly. Running arbitrary new *code* is itself the largest authority grant (new code can rewrite the act-map, disable the privacy guard, exfiltrate the log) — which contradicts the local-first/human-in-the-loop ethos more than any device action does. | **High (M11)** | `selfupdate.py:29-42`; MASTERPLAN M11 | Verify a signed tag/commit against the owner's key before running; update only to signed releases; keep code updates human-gated (the test-gate handles accidental breakage only). Also: roll back to the captured `before` hash, not `HEAD@{1}` (`selfupdate.py:41` — fragile if the reflog moved). |
| **NEW-4** | **N4's fix is dormant.** Because `HOMIE_LAT/LON` are commented out, the running box uses the 18:00–07:00 fallback **right now** — the exact bug N4 named, still live until move-in. | **Med** | `configuration.nix:102-103`; `handlers.py:54-57` | Set the coordinates (the box is pre-move; flag it on the move checklist). |
| **NEW-5** | **Timers don't survive a restart → the nightly self-restart drops in-flight auto-offs.** `Clock._timers` are in-memory tasks cancelled on `stop()` (`clock.py:53, 62-71`); lighting's `_armed` set is explicitly ephemeral (`handlers.py:75-82`). A room mid-vacancy-countdown at the M11 midnight restart keeps its light on until it is **next re-vacated**. N1 holds in steady state but reopens precisely when the system restarts itself. | **Med** | `clock.py:53`; `handlers.py:75-82` | Persist pending timers as `(deadline, key, data)`; on boot, re-fire past-due and re-arm the rest. |
| **NEW-6** | **The reconciler still gets no `context` even in `build_daemon`.** `StateReconciler(sup, commands, act_map.reverse, on_echo=act.confirm)` (`daemon.py:243`) passes no `context=`, so `zone`/`actor` are `None` everywhere. Per-person learning, the guest-exclusion in `learn.py:33`, and the M10 trust tiers are all still blocked on this one argument. | **Med** | `daemon.py:243`; `reconcile.py:43-56` | A `context(entity)→(zone, actor)` resolver from the act-map zone + current presence. One wire, three features. |
| **NEW-7** | **Dimming-transition phantom friction is now live end-to-end.** `state_event_to_value` forwards every HA `state_changed` (`ha.py:61-77`); HA fires one per attribute during a ramp; `take_echo`'s exact-match consumes only the terminal value, so each intermediate brightness for the 4 mapped lights becomes a `note_manual`/`note_reversal` candidate. N5, confirmed against the real adapter. | **Med** | `ha.py:61-77`; `act.py:127-130` | Reconcile only settled state (debounce ~300ms after the last change for an entity), or match within a brightness tolerance band. |
| **NEW-8** | **Out-of-order event timestamps corrupt the wake budget.** `WakeBudget._refill` advances only when `ts > _last_ts` (`wake_ledger.py:118-124`) and the daily ceiling keys on `int(ts//86400)` (`:134-136`); an earlier-than-`_last_ts` event (mesh reordering, N11) skips refill and can flip `_day` backward, **resetting the daily wake counter**. Mesh-only, but it defeats the cap exactly when a 3-node deployment is added. | **Low–Med** | `wake_ledger.py:118-136` | Clamp `day`/`ts` to monotonic, or buffer-sort per source. |
| **NEW-9** | **`AnchorVoice` overclaims safety.** `_status_line`/`_defer_line` say "everything looks normal" / "it's been quiet" from `pattern_count()` alone — no live-state or active-alert check (`anchor_voice.py:119-133`). With a live `security.alert` the anchor would still report normal. | **Low** | `anchor_voice.py:119-133` | Phrase from what it actually checked; or consult a live "any open alert" flag. |
| **NEW-10** | **Sundries.** `ws.py` reads a 64-bit frame length and `readexactly`s it uncapped (`ws.py:154-166`) — unbounded alloc on a hostile/buggy server (low risk for trusted HA). Timer keys are a global namespace with replace-semantics (`clock.py:97-102`) — any tile can rearm/cancel another's timer. `tick.hour` fires on the **UTC** hour boundary (`clock.py:81`), not local. The golden-loop keystone test drives the bus directly (`perception=None`, `test_golden_loop.py`), so the strongest form — `SyntheticPerception` → the real daemon (MASTERPLAN idea #1) — is proven only in `test_synthetic`, not the headline arc. | **Low** | as cited | cap frame length; namespace timer keys per owner; document the UTC tick; add one golden test with `perception=SyntheticPerception`. |

---

## 3. The topology decision survives, but it makes two open items load-bearing

The owner kept the 3-node design (MASTERPLAN §5) for a sound reason: raw frames stay on the Pi. Fine — but that choice **promotes, not defers, two findings**:

- **N8 (mesh can't relay through a hub)** becomes a correctness blocker: as drawn (Pi→anchor→desktop) presence never reaches Reason, because `_on_local` forwards only locally-originated events (`mesh.py:106-107`). Either make the bridge relay (re-forward remote-origin events with a decremented hop count) or commit to full pairwise links and say so.
- **C6 (positive-schema privacy guard, M7)** becomes the actual privacy guarantee, not a nicety — three machines means the denylist's non-recursive hole (a faceprint under a nested key) is the difference between "raw biometrics can't cross" and "probably won't."

Both are already on the map (M7); the topology decision just raised their priority.

---

## 4. What is genuinely excellent (protect it)

Stated once, briefly. **The keystone discipline** — one `build_daemon`, with `test_golden_loop` making the C1 regression structurally impossible — is the single best decision in the project and it held. **The capability docstring's honesty** (`capability.py:16-21`: "not unforgeable against a malicious in-process tile") is exactly the right epistemics. **The wake ledger is event-clocked and replay-deterministic**, turning an asserted "95% asleep" into a falsifiable number — and it kept both `fired/total` and `surprising` so the metric can't be gamed by inflating the denominator. **Stdlib-only held** even for the WebSocket. And the PROGRESS/MASTERPLAN pair is an unusually honest execution record.

One logical caveat on the wake design: the *budget* (hard cap) is what delivers the asleep guarantee; the *calibrated surprise* is a prioritizer feeding that cap, and it flags a fixed ~20% quantile of known patterns — so a *more regular* home raises the bar and can flag moderate-rate events as "rare relative to this home." Defensible, but the docstring slightly credits calibration with the sleeping that the budget actually does.

---

## 5. Brainstorm — ideas, upgrades, improvements

Fresh set, tuned to where the system *is* now (HA wired, capability/clock/budget done) — not a re-run of the prior 16.

**Make the home's I/O truthful (the current frontier):**
1. **An intent ledger.** Persist every `actuator.requested → done | failed | (timed-out)` as a queryable local timeline. It (a) gives `drive` a real ack by correlating HA results (fixes NEW-1), (b) becomes the cockpit "what just happened / why" pane, and (c) is the tamper-evident audit trail the KartenWerk money-actions need. One structure, three payoffs.
2. **A reusable liveness wrapper.** Generalize the HA heartbeat (NEW-2) into a `KeepAlive(seam, ping, pong_deadline)` that any external connection (HA, a future MQTT broker, the mesh link) wraps. Liveness becomes a property of *every* seam, not a per-adapter afterthought.
3. **Durable, schedulable intents.** Persist `(deadline, key, data)` timers (fixes NEW-5) and expose `at(when)` as well as `after(seconds)`. Now "turn the porch light off at civil dawn," "remind me each Tuesday," and "re-check this in 6h" survive restarts — and the nightly self-restart stops dropping auto-offs.

**Close the learning loop the design promised:**
4. **The context resolver (highest-leverage one-liner).** A `context(entity)→(zone, actor)` from the act-map zone + current presence, wired into the reconciler (NEW-6). Unblocks per-person learning, guest-exclusion, and trust tiers in a single wire.
5. **Settled-state reconciliation.** Debounce HA `state_changed` per entity (~300ms) before reconciling (fixes NEW-7) — kills phantom friction *and* tames the HA firehose. Pairs naturally with #1's intent ledger.
6. **The reversal captures a reason.** On a reversal, optionally ask one cheap question ("too bright / wrong time?") and store the tag, turning the hour-suppression map into a structured preference store and giving the Dream Journal (M7) real episodes to retrieve.

**Security & sovereignty (the things M9/M11 actually need):**
7. **Signed-release self-update.** Verify a signed tag against the owner's key before running pulled code (fixes NEW-3). This is the difference between "auto-update is convenient" and "auto-update is a backdoor," and it's the one place the local-first ethos is currently contradicted.
8. **A privacy heartbeat.** Turn the privacy guarantee into a *continuously verified* invariant: periodically assert (and log) that no forbidden payload has crossed the boundary, and surface the streak in the cockpit. A guarantee you can watch beats one you asserted once — and it's the honest companion to the positive-schema guard (M7).
9. **A panic/look-away switch enforced at `assert_emittable`.** One physical/cockpit toggle that stops perception emission, suspends actuation, and marks the window never-learned. For a camera in the home, an enforced (not LLM-polite) "Homie, look away."

**The behavioral pillar (the owner's actual interest), now with infra to support it:**
10. **Rhythm fingerprinting + dwell.** The clock+timer seam finally makes dwell-time and inter-event timing first-class. A tiny Markov model of room transitions catches an intruder who trips living-room motion *before* any entry event — anomalous even when each event is individually common.
11. **Stranger-by-behavior feeds the `actor` field.** Classify household-like vs stranger-like from time/sequence/dwell, zero biometrics, and write the result as the reconciler's `actor` — closing the loop with #4. Ship this rung before any faceprint ladder.
12. **Floor-plan adjacency from the Polycam scans.** Derive zone adjacency from the geometry you already have; a transition that violates physical adjacency (living→bedroom with no connecting event) is anomalous. The floor plan becomes the prior for plausible movement.

**Operability & felt experience:**
13. **Promote `AnchorVoice` from honest-deferral to warm tier.** It already answers from Remember; give it the simple ops answers ("is anyone home" — *actually* checked, fixing NEW-9) and let it escalate only the reasoning-shaped questions to the GPU. The three-tier cascade, using a component that already exists.
14. **Counterfactual replay.** Run a new tile or a new lesson against the scenario library and *diff* its behavior vs current ("shipping this would change 3 of today's 47 actions"). Regression test and trust-builder in one — and it reuses M2's scenarios.
15. **The cold-start kit, operationalized.** A `homie seed` command that takes the PLAN question-bank answers and writes weak priors into Remember (and now: a wake-budget warm start), so move-in is a warm start, not a month of false alarms. Timely.
16. **🌶️ The house's nightly changelog — now it has real content.** The wake ledger (asleep-fraction, surprising moments), the lessons (`learn.py` narrations), and the intent ledger (#1) together make the morning note concrete: *"Tuesday. Out 9–18. Stayed asleep 96%; woke twice (an unfamiliar 20:00 rhythm at the approach — likely a delivery). Lit the kitchen, you corrected the hallway (now suppressed evenings)."* Legible learning as narrative, assembled from data that now exists.

---

## 6. The one thing

The two worst architectural findings (C1, C2) are dead, and the live risk has moved **out of the brain and into the home seam.** The single highest-leverage move now is to **make `drive` truthful**: correlate the HA `call_service` result (NEW-1) and add a liveness heartbeat (NEW-2). Everything M3–M5 built — the friction loop, the wake budget, the capability gate — silently assumes that Homie *hears what the home does* and *knows whether its commands landed*. Today it can be confidently wrong (false success) or silently deaf (half-open socket), and a learning loop that mislearns from a home it can't reliably observe is worse than no loop. Fix the senses of the hand before teaching it anything new.

The brain is, at this point, genuinely well-built. Give the hand a reliable sense of touch before the next milestone.
