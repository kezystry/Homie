# Architecture

Seven pillars compose into one system, sharing a common core: **Behavioral
Analysis** models the household's pattern of life; **Home Assistant Control** is
the actuation layer.

## Compute split

- **Perception node** — Raspberry Pi + Hailo accelerator. All vision and sensor
  inference at the edge (Frigate, object detection).
- **Reasoning node** — desktop with discrete GPU. All LLM reasoning.

Heavy perception stays at the edge; heavy reasoning stays at the GPU.

## Sensor head ("Schauender Kopf")

Ceiling-mounted, disguised as a smoke detector, powered and networked over a
single PoE cable.

| Subsystem | Component |
|-----------|-----------|
| Power     | PoE+ splitter (5 V / 5 A) |
| Sensing   | Thermal camera, mmWave radar, wide-angle camera |
| Inference | Hailo accelerator |
| Motion    | Feetech STS3215 servo (~200° pan) |

A flexing cable service loop replaces a slip ring, trading full rotation for a
fraction of the cost.
