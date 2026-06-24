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
- [`INTERNALS.md`](INTERNALS.md) — the engineering decisions: language, bus,
  mesh, isolation.
- [`PROTOCOL.md`](PROTOCOL.md) — the tile wire protocol.
- [`SECURITY.md`](SECURITY.md) — the privacy, encryption, and identity model.
- [`ROADMAP.md`](ROADMAP.md) — the build order.

## Running it

The reasoning-side spine runs today (Python 3.11+, stdlib only):

```sh
python3 -m unittest discover -s tests   # the test suite
python3 scripts/spine_demo.py           # the loop end to end on one node
```

The demo boots the bus, Behavioral Analysis, and the Supervisor with the real
Personal and Security tiles, then shows presence flowing through the loop —
Personal offering the agenda, Security flagging a novel late-night visitor, and
friction teaching Personal to go quiet.

Status: early — the reasoning-node spine is taking shape; the sensor head is next.
