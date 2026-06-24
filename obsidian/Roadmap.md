---
tags: [homie, plan]
---

# Roadmap

Build order (full detail in the repo's `PLAN.md`). Each phase ships something usable.

0. **Buy & prep** — Pi 5 8 GB + AI HAT+ ([[Hardware]]); migrate Trådfri bulbs onto Dirigera; pick the anchor.
1. **Validate the OS in a VM** (`nixos-rebuild build-vm`) before the real disk; add NVIDIA/CUDA.
2. **Home Assistant + first light** — HA + Mosquitto on the mini-PC; the [[Act]] gateway; a real bulb turns on.
3. **Perception v1** — Frigate + Hailo + USB cam on the Pi → normalized `presence.*` events.
4. **[[Mesh]] transport** — the Noise-IK `Link` + mDNS + roster, so the Pi and cortex talk.
5. **Friction loop** — the StateReconciler + a `lighting` tile. *(loop core already built)*
6. **[[Reason]]** — serve the LLM; the gate + tool-calling decide loop.
7. **Interface (voice) + gestures** — and the QLoRA fine-tune loop from friction.
8. **Hardening/ops** — encrypted backup, Nix-packaged app, LUKS-unlock, the sensor head.

## Built & tested today (83 tests)
[[Bus]] · [[Remember]] · tile runtime · Personal + Security tiles · friction loop
([[Act]] + StateReconciler) · tool-call schemas ([[Reason]]) · [[Consent and Gestures]] · [[Mesh]] bridge.
