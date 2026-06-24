# Internals

How Homie is built under the hood. The concept is in [`DESIGN.md`](DESIGN.md);
this is the engineering, and the decisions behind it.

## Decisions

| Area | Decision | Why |
|------|----------|-----|
| **Language** | Python for the core and all tiles; Rust only on the Pi perception daemon | The core is I/O-bound glue over compute that already lives in C/LLM/Hailo. The Pi is the one hot, network/camera-exposed, separately-deployed surface where Rust earns its keep — and it's already a separate node, so it adds no new seam. |
| **Bus** | In-process asyncio + MeshBridge; append-only event log behind `publish()`; heartbeat + last-will; MQTT only at the Home Assistant edge | No broker is warranted at ~3 nodes. The log gives durability across the regular immutable-image reboots and is the substrate Remember reads. Presence (last-will) is what makes self-healing real. |
| **Mesh** | App-layer Noise-IK via a vetted library — not WireGuard | Runs unprivileged in-process; no kernel module / `NET_ADMIN`, no phone VPN profile. Keeps WireGuard's one good property (one Curve25519 key = one cell's identity, no CA). Crypto is never hand-rolled. |
| **Isolation** | In-process async tasks by default; out-of-process (JSON-stdio) as a manifest-selected escape hatch | Self-healing is achievable in-process (`TaskGroup` + timeouts + restart/quarantine). Heavier isolation only when a tile declares `network = egress`, ships a flaky C-extension, or is third-party. |

## The bus

One asyncio `Bus` per node; the only referee.

- **Event** — immutable: `topic` (dotted, e.g. `presence.arrived`), `payload`
  (JSON-safe dict), `ts`, `source`, `id`, `origin`, `ttl`.
- **Pub/sub** — `publish` fans out to glob subscribers (`presence.*`,
  `sensor.**`); each subscriber has a bounded mailbox and its own drain task, so
  a throwing or slow handler harms only itself.
- **Arbitration** — competing actuator requests resolve by priority
  (`SAFETY > SECURITY > AUTOMATION > CONVENIENCE > AMBIENT`), then recency. The
  bus is the one place this is decided.
- **Durability** — an append-only log sits behind `publish()`; events replay on
  boot and feed Remember.
- **Presence** — the MeshBridge emits heartbeats and a last-will, so a dropped
  node/tile is *declared* down as a bus event the colony can react to.

## The tile runtime

The canonical tile boundary is the **wire protocol** in [`PROTOCOL.md`](PROTOCOL.md),
not a Python base class. This is the pivot that keeps "the core never imports a
tile" honest and keeps tiles polyglot.

- **`TileChannel`** — the Supervisor talks to every tile through one interface
  (`send_event`, `deliver_friction`, `check_health`, `start`, `stop`).
  - `InProcessChannel` (default) runs the protocol short-circuited in memory; the
    Supervisor's loader imports the tile into an isolated, killable task — core
    proper never imports it.
  - `SubprocessChannel` (escape hatch) speaks line-delimited JSON over stdio to a
    child process, with a network namespace to enforce `local`-only.
- **Manifest selects the channel** — `network = "local"` → in-process;
  `egress:<host>` / third-party / declared-unsafe → subprocess + netns.
- **Supervision** — per-dispatch timeouts, restart with exponential backoff, a
  stability reset, and quarantine after repeated failure (crash-looping is a
  fault worth surfacing, not hiding).
- **Friction attribution** — every act is stamped with an `ActionRef` into a
  short rolling ledger; a reversal/repeat/remark is matched back to the tile
  whose action it corrects and delivered to that tile's `learn()`. Remark
  overrides reversal overrides repeat.

## Perception

Runs on the Pi (Rust daemon). Radar and thermal run continuously and **gate the
camera** (privacy + power). The identity ladder (SECURITY.md levels 1–4) runs
entirely at the edge. Only **normalized events** cross the mesh — a central
`assert_emittable` guard rejects any raw frame, crop, bounding box, or faceprint
vector. The daemon is a Noise peer and event producer, **not a tile**.

## Mesh

App-layer Noise-IK. Each cell holds one static Curve25519 keypair (its identity);
trust is a gossiped, signed roster — no CA, no accounts. mDNS handles LAN
discovery (endpoints only; trust stays in the roster). The `MeshBridge` makes the
bus node-transparent via a **default-deny** topic allowlist and `(origin, seq)`
loop suppression; reconnect uses a **state snapshot**, not event replay. A
fail-closed `PrivacyGuard` guarantees raw imagery and faceprints never traverse
the wire.
