---
tags: [homie, decision]
---

# Decisions log

Significant decisions, each reached in a **panel of expert/scientist agents** then
chaired to a synthesis (the standing working rule).

- **Language** — Python for the core + all tiles; **Rust only on the Pi perception daemon**.
- **Bus** — in-process asyncio, no broker; durability log; MQTT only at the HA edge. → [[Bus]]
- **[[Mesh]]** — app-layer **Noise-IK** (vetted lib), not WireGuard; one key per cell, no CA.
- **Isolation** — in-process tiles by default; subprocess (JSON-stdio) escape hatch by manifest.
- **[[Always-on topology]]** — Pi = 24/7 learning floor; mini-PC = wired HA pillar; desktop =
  Homie-OS-only on-demand LLM cortex (Proton gaming). Continuous learning is lightweight.
- **Log compaction** — generation-based snapshot + segment rotation; crash-safe; saves the SD card. → [[Bus]]
- **Friction producer** — Act + StateReconciler; echoes suppressed, human changes → learning. → [[Act]]
- **Tool-calling** — rich function schemas + `tool_catalog()`; structural `validate_tool_call` gate. → [[Reason]]
- **Autonomy** — **mixed by risk**, highly autonomous; confirm bigger actions by **head nod/shake**;
  non-response = No; confirmations decay as trust accrues. → [[Consent and Gestures]]
- **[[Reason]] wake gate** — novelty + when addressed.
- **[[Security and Identity]]** — local recognition only; no internet identification of strangers.
- **Dependencies** — stdlib-first; add vetted libs deliberately (pinned) when a real need lands.
