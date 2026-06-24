---
tags: [homie, hardware]
---

# Hardware

## Perception node (the watching head)
- **Raspberry Pi 5, 8 GB** — not the 4 GB; the Hailo attaches over PCIe (Pi 5 only).
- **Hailo-8 (26 TOPS)** via the AI HAT+ — *not* the 8L (no headroom) or 10H (its LLM
  feature is redundant with the 3060). The Pi does **vision only**.
- USB camera → plug into the **Pi** (keeps raw frames at the edge). Active cooler + 27 W PSU.
- ~€230–290. Later: the ceiling "smoke-detector" head with thermal + mmWave radar + PoE.

## Reasoning node
- Desktop: **i5-12400F, RTX 3060 12 GB, 32 GB**. Serves the 8B abliterated LLM ([[Reason]]).

## Home control
- IKEA **Trådfri** bulbs + **Dirigera** hub, via Home Assistant ([[Act]]).

See [[Always-on topology]] for where each runs, and [[Roadmap]] for the build order.
