# Architecture

Homie is an organism: a minimal core and a colony of tiles, running on its own
OS across hardware you own.

## The OS

Homie runs on a hardened, **text-first** Linux base — an immutable, stripped
image that boots straight into the system. No desktop, no bloat; the console is
the only screen. It is designed to **dual-boot** alongside an existing OS.

- Full-disk encryption; encrypted state; no telemetry, no accounts, no cloud.
- The only imagery on screen is pulled in on demand — camera frames and
  recognized faces — never a UI for its own sake.

## The mesh

Homie is distributed across your devices as an **encrypted peer mesh** — the
perception node, the reasoning node, and optionally a laptop or phone. Each
device is a cell; peer links are encrypted; the colony self-heals if one drops.
No central server.

## Compute split

- **Perception node** — Raspberry Pi + Hailo accelerator. All vision and sensor
  inference at the edge (Frigate, detection).
- **Reasoning node** — desktop with a discrete GPU. All LLM reasoning (MoE
  models for hybrid CPU/GPU inference).

Heavy perception stays at the edge; heavy reasoning stays at the GPU.

## Sensor head

Ceiling-mounted, disguised as a smoke detector, powered and networked over a
single PoE cable.

| Subsystem | Component |
|-----------|-----------|
| Power     | PoE+ splitter |
| Sensing   | Thermal camera, mmWave radar, wide-angle camera |
| Inference | Hailo accelerator |
| Motion    | Pan servo (~200°) |

A flexing cable service loop replaces a slip ring.

## Repo layout

```
homie/
├── core/         # the minimal substrate: perceive, remember, reason, act, interface, bus
├── tiles/        # the colony — one folder each (manifest, handlers, learn, health, state)
├── perception/   # perception-node code (edge): sensor drivers, Frigate
├── os/           # the hardened image build
├── deploy/       # per-node configs, mesh keys, secrets handling
└── docs/         # README, DESIGN, ARCHITECTURE, SECURITY, ROADMAP
```

Rule: **the core never imports a tile.** It discovers tiles, reads each
manifest, and routes. Adding capability is dropping in a folder; a broken tile
cannot take down the core.
