---
tags: [homie, concept]
---

# Core and Tiles

Homie is an **organism, not a program**: a minimal **core** and a colony of
self-contained **tiles**.

## The core (fixed)
The [[Spine]] plus **Security**, which emerges for free once Remember + Reason exist.
The core never imports a tile — it discovers folders, reads each `tile.toml`, and routes.

## Tiles (open slot — living cells)
A tile is any capability that plugs into the spine. Each is:
- **Self-learning** — runs its own friction loop.
- **Self-healing** — recovers from its own faults, degrades quietly.
- **Self-dependent** — owns its state, config, secrets; needs no other tile.

The tile contract (`tile.toml`): **Subscribes · Provides** (voice intents +
LLM-callable functions, see [[Reason]]) **· Acts · Permissions · Friction · Living**.

Isolation is a manifest switch: in-process by default, a subprocess (JSON-stdio)
escape hatch when a tile declares `network = egress`, ships a flaky native lib, or
is third-party. Reference tiles: **Personal**, **Security**.
