# Homie

> Self-hosted, local-first home intelligence.

Homie is one ambient system that **perceives a home, learns its patterns of
life, and acts on them** — all on your own hardware. The household's data never
leaves the local network unless you explicitly permit it.

The guiding idea is borrowed from *The Machine* in *Person of Interest*: a
quiet, ever-present intelligence that watches over and protects — reimagined as
something personal and private. Homie favours presence- and pattern-based
sensing (thermal, radar) over intrusive cameras, and is designed to disappear
into the home both physically and operationally.

## Core principles

- **Local-first** — all perception and reasoning run on-premises; no cloud
  dependency for core functions.
- **Privacy by design** — thermal and radar sensing are preferred over
  conventional cameras, and data stays on the local network.
- **Ambient, not intrusive** — the system hides in the home; the sensor head is
  disguised as a smoke detector.
- **Modular** — seven independent pillars compose into one intelligence.

## The seven pillars

1. **Self-Learning** — builds and refines models of the household's routines
   over time.
2. **Home Assistant Control** — the actuation layer; lights, climate, and
   devices via Home Assistant.
3. **Personal Assistant** — calendar, reminders, and day-to-day tasks.
4. **Werkstatt** — a business module for Pokémon card analysis and restoration,
   integrating Shopify through a custom MCP server.
5. **Kitchen Assistant** — recipes, inventory, and cooking support.
6. **Security & Threat Escalation** — presence detection, anomaly flagging, and
   graduated alerting.
7. **Behavioral Analysis** — pattern-of-life modeling; the analytical backbone
   shared across all pillars.

## How it runs

Homie splits work across two nodes. A **perception node** (Raspberry Pi with a
Hailo accelerator) handles all vision and sensor inference at the edge, while a
**reasoning node** (a desktop with a discrete GPU) runs all LLM reasoning. The
principle is simple: heavy perception stays where the sensors are, and heavy
reasoning stays where the GPU is.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full compute split and the
"Schauender Kopf" sensor-head build.

## Status

Active development. The hardware build is in progress.

## License

TBD.
