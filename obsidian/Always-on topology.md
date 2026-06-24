---
tags: [homie, hardware, decision]
---

# Always-on topology

A dual-boot PC runs one OS at a time, so it can't be the always-on brain. The
decided split (see [[Decisions log]]):

- **Pi (24/7) — the learning floor + perception.** Runs Frigate + Hailo *and* the
  lightweight core (bus, [[Remember]], Security, simple automations). Continuous
  learning lives here and never stops — it's [[Remember|featherweight]]. Holds the
  canonical durability log.
- **Mini-PC — the pillar.** Home Assistant + Mosquitto, kept off the privacy-critical
  Pi. **Wire it (Ethernet), not WiFi** — latency/mDNS, not bandwidth, is the risk.
- **RTX 3060 desktop — the on-demand cortex.** Homie-OS-only (games via Proton, since
  they run), serving the LLM ([[Reason]]) when on, gated to novelty. No Windows gap.

Connected as encrypted [[Mesh]] peers, never a shared disk partition.

Caveats: SD-card wear → log compaction ([[Bus]]) + high-endurance card; a UPS on the Pi;
validate the game library on ProtonDB; isolate the LLM/core from the gaming session.
