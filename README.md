# Homie

Private. Local-first. Headless.

Homie is a home intelligence that perceives a home, learns its pattern of life,
and acts on it — running entirely on hardware you own, on its own hardened OS,
with nothing leaving your network. The inspiration is *The Machine* from
*Person of Interest*: quiet, resilient, ever-present — reimagined as something
personal and private.

## The loop

Five steps: **Perceive → Remember → Reason → Act → Interface.** *Remember*
(Behavioral Analysis) is the heart; the *Interface* is voice-first.

## Shape

A minimal **core** (the loop, plus Security) and an open set of self-contained
**tiles**. The core never depends on a tile. Tiles are living cells —
self-learning, self-healing, self-dependent.

## Principles

- **Local-first** — perception and reasoning run on your hardware; data stays
  on your network.
- **Private by default** — encrypted at rest, no cloud, no accounts, no
  telemetry.
- **Ambient** — headless and text-first; it disappears into the home.
- **Resilient** — runs as an encrypted mesh across your devices; losing one
  doesn't stop it.
- **Modular** — capability is added as tiles, never by touching the core.

## Docs

- [`DESIGN.md`](DESIGN.md) — why it works this way: the loop, friction learning,
  the tile contract.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how it's built: the OS, the mesh, the
  nodes, the layout.
- [`SECURITY.md`](SECURITY.md) — the privacy, encryption, and identity model.
- [`ROADMAP.md`](ROADMAP.md) — the build order.

Status: early — building the sensor head.
