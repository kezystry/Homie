# Homie

> Self-hosted, local-first home intelligence. Private. Headless. Runs on your own hardware.

Homie perceives a home, learns its pattern of life, and acts on it — entirely on
hardware you own, on its own hardened OS, with nothing leaving your network. The
inspiration is *The Machine* from *Person of Interest*: quiet, resilient,
ever-present — reimagined as something personal and private.

## The idea

A minimal **core** and a colony of self-contained **tiles** (living cells:
self-learning, self-healing, self-dependent), composing one five-part loop:

**Perceive → Remember → Reason → Act → Interface**

*Remember* (Behavioral Analysis) is the heart; the *Interface* is voice-first.
Homie learns by friction — silence is approval, a reversal is a correction — and
aims to need you less over time.

## Principles

- **Local-first** — perception and reasoning run on your hardware; data stays on
  your network.
- **Private by default** — encrypted at rest, no cloud, no accounts, no telemetry.
- **Ambient** — headless and text-first; it disappears into the home.
- **Resilient** — an encrypted mesh across your devices; losing one doesn't stop it.
- **Modular** — capability is added as tiles, never by touching the core.

## Install

### Run the spine

Python 3.11+, standard library only — no dependencies.

```sh
git clone https://github.com/kezystry/homie.git && cd homie
python3 -m unittest discover -s tests   # the test suite (44 tests)
python3 scripts/spine_demo.py           # the loop, end to end on one node
python3 scripts/run.py                  # the daemon (bus + Remember + tiles)
```

### Install as its own OS (dual-boot)

Homie ships a hardened, text-first NixOS profile that **dual-boots alongside your
existing OS** on a LUKS-encrypted partition and boots straight into the daemon.
Your existing OS is preserved and chainloaded from the boot menu; Homie never
writes to it.

See **[os/INSTALL.md](os/INSTALL.md)** for step-by-step dual-boot installation.

## Status

The reasoning-node spine runs and is tested: the bus, Behavioral Analysis, the
tile runtime, the Personal and Security tiles, friction learning, and the mesh
bridge. The outward edges — LLM reasoning, Home Assistant control, voice — are
next. See [`OVERVIEW.md`](OVERVIEW.md).

## Docs

- [`OVERVIEW.md`](OVERVIEW.md) — the big picture and roadmap
- [`PLAN.md`](PLAN.md) — the build plan for real hardware (always-on topology + question bank)
- [`DESIGN.md`](DESIGN.md) — why it works this way
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how it's built
- [`INTERNALS.md`](INTERNALS.md) — the engineering decisions
- [`PROTOCOL.md`](PROTOCOL.md) — the tile wire protocol
- [`SECURITY.md`](SECURITY.md) — privacy, encryption, identity
- [`ROADMAP.md`](ROADMAP.md) — the build order

## License

TBD.
