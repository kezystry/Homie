---
tags: [homie, component, built]
---

# Bus

`core/bus.py` — the only referee. Tiles never call each other; they publish and
subscribe through the bus.

- **Events** — immutable, dotted topics (`presence.arrived`), small JSON payloads.
- **Pub/sub** — segment-aware glob (`presence.*`, `sensor.**`); bounded per-subscriber
  mailboxes, so a slow/throwing handler harms only itself.
- **Arbitration** — competing actuator requests resolve by priority
  (`SAFETY > SECURITY > AUTOMATION > CONVENIENCE > AMBIENT`), then recency. The safety floor.
- **Durability** — an append-only log; the pattern of life ([[Remember]]) is rebuilt from it.
- **Compaction** — generation-based snapshot + segment rotation keeps the log bounded and
  the Pi's SD card alive (crash-safe; see [[Decisions log]]).

Carried across nodes by the [[Mesh]]. Consumed by [[Remember]], [[Act]], [[Consent and Gestures]].
