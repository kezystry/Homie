---
tags: [homie, plan]
---

# Bring-up

The order to make the software physical when you're at the hardware (full detail
in the repo's `BRINGUP.md`). The brain is built + tested (150 tests); these are
the edges that need the kit in front of you.

## Steps (each independently demoable)
1. **Validate the OS in a VM** (`nixos-rebuild build-vm`) — add the NVIDIA/CUDA config — before the real disk. See [[Always-on topology]].
2. **Pi core** runs today (`scripts/run.py`): bus + [[Remember]] + Supervisor + tiles. UPS + high-endurance SD.
3. **Home Assistant pillar** (mini-PC, wired): HAOS + Mosquitto + Dirigera integration; fill `deploy/act_map.toml` (map + never-touch). See [[Act]].
4. **Perception** (Pi): Frigate + Hailo + USB cam → `presence.*` events. See [[Security and Identity]].
5. **Mesh transport**: implement `NoiseLink` (Noise-IK) behind the [[Mesh]] `Link`.
6. **Reason**: serve the 8B abliterated model; novelty wakes it. See [[Reason]].
7. **Interface + gestures**: voice + nod/shake → confirm. See [[Consent and Gestures]].
8. **Nightly ritual**: systemd timer + `ritual.sh`. See [[Nightly ritual]].

## Stubs to fill (clean seams, fake-tested)
`HomeClient` (MQTT) · `NoiseLink` (mesh) · `Reason.decide` (LLM) · perception adapter ·
`ritual.sh`. Add vetted deps to a pinned requirements file; the in-process tile path stays stdlib.

## Answer first (gate the wiring)
Bulbs migrated to Dirigera? · never-touch entities · which abliterated model · which
camera location · BitLocker key saved + LUKS unlock method. (Full bank: [[Open questions]].)
