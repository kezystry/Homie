# Bring-up checklist — from code to a running home

What to do when you're at the hardware. The software brain is built and tested
(108 stdlib tests); this is the order to make it physical. Detail in `PLAN.md`,
OS steps in `os/INSTALL.md`, decisions in `obsidian/Decisions log.md`.

## 0. Buy / gather
- **Raspberry Pi 5, 8 GB** + **AI HAT+ (Hailo-8, 26 TOPS)** + active cooler + 27 W USB-C PSU + good A2 microSD.
- The **USB webcam** (confirm it does MJPEG/H.264 over UVC: `v4l2-ctl --list-formats-ext`).
- The **low-quality mini-PC** as the always-on Home Assistant pillar — **wire it by Ethernet**.
- Migrate the **Trådfri bulbs onto the Dirigera hub** (factory-reset + re-pair) and give the hub a **DHCP reservation**.
- The desktop (RTX 3060) — you'll dual-... no: **Homie-OS-only** (games via Proton). Check your library on ProtonDB first.

## 1. Validate the OS in a VM (before touching the real disk)
- `cp os/boot/*.nix ~/vmtest/`, add a stub `hardware-configuration.nix`, fill placeholders.
- `nix flake check` then `nixos-rebuild build-vm --flake .#homie` → `./result/bin/run-homie-vm`.
- Confirm: GRUB → LUKS prompt → getty autologin → `systemctl status homie` (put the repo at `/opt/homie` in the VM or the service ImportErrors).
- **Add the missing NVIDIA/CUDA config** to `configuration.nix` (the reasoning node is the 3060 — it ships with no GPU driver). Then real install per `os/INSTALL.md` (BitLocker key first, Fast Startup off, Secure Boot off, full backup).

## 2. Always-on floor: the Pi
- OS on the Pi (Pi OS or a NixOS image); repo at `/opt/homie`; set `HOMIE_TZ` (e.g. `Europe/Berlin`) and `HOMIE_STATE=/var/lib/homie`.
- `python3 scripts/run.py` already boots **bus + Remember + Supervisor + tiles** — runs today, no deps.
- A **UPS** on the Pi (it's now the 24/7 learning floor + perception SPOF). High-endurance SD card.

## 3. Home Assistant pillar: the mini-PC
- HAOS on the mini-PC (wired). Install the **Mosquitto** add-on (the MQTT seam).
- Integrate Dirigera via the community **`dirigera_platform`** (local API, real-time) — Matter bridge as fallback. Pair via the hub's action button.
- Fill **`deploy/act_map.toml`**: map Homie actuator names → HA entity_ids, and list **never-touch** entities (locks/heaters). This is the allowlist + the safety guard.

## 4. Code stubs to fill (each has a clean seam + fake-tested contract)
| Stub | What | Needs |
|------|------|-------|
| `core/act.py` `HomeClient` | real MQTT client (publish commands, subscribe `mqtt_statestream`) | `aiomqtt` (add dep) |
| `deploy/mesh/` `NoiseLink` | the `Link` transport: Noise-IK + mDNS + signed roster | a vetted Noise lib (`dissononce`/`noiseprotocol`) |
| `core/reason.py` `Reason.decide` | gate → catalog → local LLM → `validate_tool_call` → `call_function`/speak | llama.cpp/Ollama endpoint |
| `perception/` adapter | Frigate(MQTT) → normalized `presence.*` events; identity ladder L1–4 | Frigate + Hailo on the Pi |
| `scripts/ritual.sh` + systemd units | the 23:59 consolidation (decay→snapshot→heal→update→restart) | the OS |

Add deps deliberately to a pinned `requirements.txt` (your standing decision). The
in-process tile path stays stdlib; deps live in the edge clients.

## 5. Wiring order (each step is independently demoable)
1. **Pi core** runs (today). → `scripts/spine_demo.py` shows the loop.
2. **Act + HA**: implement the MQTT `HomeClient`, wire `Act` + `StateReconciler` into the Pi daemon → a real bulb reacts; a manual flip becomes friction.
3. **Perception**: Frigate on the Pi → `presence.*` events → Security + lighting react.
4. **Mesh**: implement `NoiseLink`, wire into `run.py` → Pi and desktop are one bus.
5. **Reason**: serve the 8B abliterated model on the desktop → novelty wakes the LLM.
6. **Interface + gestures**: voice I/O; nod/shake → `confirm.response`.
7. **Nightly ritual**: the systemd timer + `ritual.sh`.

## 6. Answer these first (gate the wiring) — from `PLAN.md` §9
- **Q17** Trådfri bulbs migrated to Dirigera yet? **Q18/Q22** which rooms/bulbs, and **never-touch** entities.
- **Q27** which abliterated model + quant (8B Q5_K_M target on 12 GB). **Q40** which single space the camera watches first.
- **Q49/Q52** BitLocker recovery key saved? LUKS unlock method (passphrase / TPM2 / initrd-SSH).

## 7. Config reference
- `HOMIE_TZ` — pin the home timezone (stable hour buckets). `HOMIE_STATE` — state dir (default `/var/lib/homie`).
- `HOMIE_COMPACT_THRESHOLD` / `HOMIE_COMPACT_INTERVAL` — log compaction cadence.
- `deploy/act_map.toml` — actuator map + never-touch. Mesh keys (one X25519 per node) live in `$HOMIE_STATE`, never committed.
