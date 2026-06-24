---
tags: [homie, component, built]
---

# Act

`core/act.py` — the single gateway to the physical home, and (with the
StateReconciler) the producer that **closes the friction loop**.

- An injected **`HomeClient`** (real MQTT/Home Assistant later, fake in tests) hides the broker.
- Consumes `actuator.requested`, maps a Homie actuator → a home entity via
  `deploy/act_map.toml` (the allowlist **and** the never-touch guard), drives the home,
  and emits `actuator.done` on the confirming echo.
- A shared **`CommandLog`** records what Homie drove, with a short *reconciliation window*.

## StateReconciler (`core/reconcile.py`)
Every home state change Homie did **not** cause is a human action:
- Echoes of Homie's own commands are suppressed.
- A genuine change → `note_reversal` (a tile's act was undone) or `note_manual`.

So a person flipping a light back teaches the tile — with zero Supervisor changes.
IKEA Trådfri + Dirigera, via Home Assistant on the [[Always-on topology|mini-PC pillar]].
