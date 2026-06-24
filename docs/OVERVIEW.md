# Overview

Private. Local-first. Headless. The big picture, and where to push next.

## What Homie is

Homie is a home intelligence that perceives a home, learns its pattern of life,
and acts on it — running entirely on hardware you own, on its own hardened
text-first OS, with nothing leaving your network. The mental model is an
**organism, not a program**: a deliberately minimal **core** (the loop, plus
Security) surrounded by a colony of self-contained **tiles** — living cells that
are self-learning, self-healing, and self-dependent. Everything reduces to one
five-part spine — **Perceive → Remember → Reason → Act → Interface** — where
*Remember* (Behavioral Analysis) is the heart and the *Interface* is voice-first.
It learns mostly by friction: silence is approval, a reversal is a correction, a
repeated manual action is a missing pattern, a spoken remark overrides all.
Success is the *declining rate of corrections*.

## Where it stands

The reasoning-side spine runs and is tested today — Python 3.11+, stdlib only,
**150 passing tests** plus an end-to-end `scripts/spine_demo.py`.

**Built and tested:**
- **Bus** (`core/bus.py`) — segment-aware glob pub/sub, per-subscriber bounded
  mailboxes (a slow/throwing handler harms only itself), priority arbitration
  (`SAFETY > SECURITY > AUTOMATION > CONVENIENCE > AMBIENT`, recency tiebreak),
  and an append-only durability log that replays on boot.
- **Remember** (`core/remember.py`) — pattern-of-life model: per `(topic, zone)`
  hour-of-day counts over distinct days, yielding a per-day rate and a `novel`
  flag. Bootstraps from the log, updates live, documents the evaluate-then-learn
  ordering contract.
- **Tile runtime** (`core/tile.py`) — manifest loader/validator (errors as
  values, never exceptions), `InProcessChannel` (default) and `SubprocessChannel`
  (JSON-over-stdio escape hatch), and a `Supervisor` with permission enforcement,
  per-dispatch timeouts, restart-with-backoff, and quarantine.
- **Friction attribution** — an `ActionRef` ledger stamps every act; reversals,
  repeats, and remarks are matched back to the responsible tile and delivered to
  its `learn()`, with remark > reversal > repeat precedence.
- **Tiles** — `personal` (reference: subscribes, intents, functions, local-only,
  learns to go quiet under friction) and `security` (graduated escalation against
  the pattern of life via `ctx.recall`).
- **Mesh bridge** (`core/mesh.py`) — node-transparent bridging with a
  default-deny topic allowlist, fail-closed `PrivacyGuard`, and `(origin, seq)`
  loop suppression.

- **Reason** (`core/reason.py`) — the cortex: a novelty-gated decide loop that
  wakes a local LLM (behind an injectable `LLMClient` seam) only when the moment is
  rare/novel, validates the proposed tool call structurally, and routes it to a tile
  function or a spoken line — it *proposes*, never drives an actuator.
- **Lighting** (`tiles/lighting/`) — presence-driven, after-dark room lighting at
  AMBIENT priority that learns to stay dark from reversals.
- **Ritual** (`core/ritual.py`) — the in-process half of the nightly 23:59
  consolidation: decay + snapshot + compaction, L4 sweep, self-healing, abort-gated.

**Stubbed / hardware-gated:** the real `LLMClient` (llama.cpp/Ollama on the 3060),
the `HomeClient` (MQTT/HA gateway — `Act` itself is built and tested behind it),
`Interface` (voice), `Perceive`, the Noise-IK transport + mDNS discovery, and the
systemd side of the ritual are deploy/edge concerns gated on the hardware.

In short: the **brain** (route, remember, supervise, learn, decide, arbitrate) is
real and tested; the **outward edges** (the model weights, speak, sense, transport)
are contracts waiting on the kit.

## How the pieces fit

**The spine.** Perception turns thermal/radar/camera into clean events; Remember
accumulates them into "what's normal"; Reason weighs *now* against *normal*; Act
carries out the decision through Home Assistant; Interface is the voice window in
and the friction channel back. Today the loop runs without Reason or a real
Interface: Security consults Remember directly via `ctx.recall`, and friction is
injected by the Supervisor.

**Core + tiles.** The core never imports a tile — it discovers folders, reads each
`tile.toml`, and routes. The Supervisor's loader is the only place tile code is
imported, into a task it can kill, restart, and quarantine. Permissions are
enforced on every message, not by convention.

**The mesh.** A `MeshBridge` per node mirrors allowlisted events across the colony
so a tile sees `presence.arrived` regardless of which node produced it. The
transport is abstracted behind a `Link`; the bridging logic is pure and tested.

**Key decisions** (see [`INTERNALS.md`](INTERNALS.md)): Python core + all tiles,
Rust only on the Pi perception daemon; in-process asyncio bus (no broker);
app-layer Noise-IK mesh (not WireGuard); in-process tiles with a manifest-selected
subprocess escape hatch.

## What's next

The brain is ahead of the edges; the near-term work closes the loop outward.

1. **Act** — the Home Assistant gateway behind `actuator.requested`. The bus
   already arbitrates and the ledger already stamps; Act drives HA and confirms,
   completing the reversal-detection path.
2. **Interface** — voice in/out plus the classifier that turns real reactions (a
   light flipped back, a repeated manual toggle, a spoken "stop") into the
   `reversal`/`repeat`/`remark` signals the Supervisor already consumes. This is
   what makes friction learning real rather than injected.
3. **Reason** — the local LLM that consumes Remember's `Expectation` and the live
   event, decides, and calls tile functions / requests actuators.
4. **Edge / transport** — the Noise-IK `Link` + mDNS discovery, and the Rust
   perception daemon as a Noise peer and event producer (not a tile), with raw
   frames/crops/faceprints rejected at the source.

## Open questions & ideas

A genuine brainstorm — problems worth thinking through before they calcify:

1. **How Reason consumes Remember.** `Expectation` is a single per-`(topic, zone,
   hour)` rate, with no notion of *transitions* or *sessions*. Does richer
   structure (sequences, deltas, multi-zone context) live in Remember, or in a
   Reason-side feature builder?
2. **Multi-resident friction.** Attribution is global today; if two residents
   disagree, friction thrashes. Does it need per-identity scoping, and how does
   that square with the deliberately identity-light recognition ladder?
3. **The repeat/manual path has no producer.** `note_manual` is tested but
   nothing emits "a human did X by hand" yet — that needs Act + HA state. What's
   the cleanest manual-vs-Homie signal that avoids a feedback loop?
4. **Backup / restore / portability of the pattern of life.** The log *is* the
   memory. How is it backed up across the encrypted mesh without exposing it, and
   what's the migration story when the event schema evolves?
5. **Tile marketplace + WASM.** The manifest gates in-process vs subprocess+netns.
   Do third-party tiles argue for **WASM** as a third channel behind the same
   `TileChannel` protocol — and what's the signing/review model?
6. **Failure & degradation UX.** Quarantine is a log line. In a voice-first home,
   how does a quarantined tile surface, and how does Homie distinguish "I chose
   silence" from "I'm broken and silent"?
7. **Arbitration beyond priority+recency.** Context (guest mode, sleeping, away)
   should reweight conflicts. Should priority be situational, and who owns that
   context — a tile, the core, or Reason?
8. **Gate Reason by Remember.** MoE inference on the GPU is the biggest power
   draw. Should the big model only wake when *now* diverges from *normal* —
   cheap by default, expensive only when something is genuinely novel?
9. **Evaluate-then-learn under live load.** With multiple consumers reading the
   same instant, how is ordering guaranteed on the real bus so an event never
   masks its own novelty?
10. **Returning-unknown across nodes.** Faceprint vectors never cross the mesh
    (correct), so "the same unknown returned" is a per-node fact. Is that
    acceptable, or is a privacy-preserving cross-node match worth designing?
