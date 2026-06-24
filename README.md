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
- **Safe by structure** — a priority floor (safety > security > automation >
  convenience > ambient) is enforced by the bus, not by any one tile's good behaviour.

## Quickstart

Python 3.11+, standard library only — no dependencies to run the spine.

```sh
git clone https://github.com/kezystry/homie.git && cd homie
python3 -m unittest discover -s tests   # the test suite (108 tests)
python3 scripts/spine_demo.py           # the loop, end to end on one node
python3 scripts/run.py                  # the daemon (bus + Remember + Supervisor + tiles)
```

## Install as its own OS (dual-boot)

Homie ships a hardened, text-first NixOS profile that **dual-boots alongside your
existing OS** on a LUKS-encrypted partition and boots straight into the daemon.
Your existing OS is preserved and chainloaded from the boot menu; Homie never
writes to it. See **[os/INSTALL.md](os/INSTALL.md)**.

## Status

The reasoning-node spine runs and is tested (**108 stdlib tests**). Built and
working today: the asyncio event bus with priority arbitration and a crash-safe
durability log, Behavioral Analysis (the pattern-of-life model, with decay), the
tile runtime (in-process + subprocess isolation, supervision, self-healing), the
Personal and Security tiles, the friction-learning loop, tool-call validation, the
confirmation gate, and the encrypted mesh bridge.

The outward edges are next, and gated on hardware in front of you: local LLM
reasoning, Home Assistant control, voice + gestures, the perception/camera head,
the Noise mesh transport, and the nightly consolidation ritual. The order is in
[docs/BRINGUP.md](docs/BRINGUP.md).

## Repo layout

```
core/        the spine: bus, remember, tile runtime, act, reason, reconcile,
             consent, mesh, perceive, interface
tiles/       living tiles (personal, security) + _template for new ones
tests/       stdlib unittest suite (108 passing)
scripts/     run.py (daemon) · spine_demo.py (end-to-end demo)
os/          dual-boot NixOS profile + INSTALL.md
deploy/      runtime config (e.g. act_map.toml)
docs/        the design & engineering docs (index below)
obsidian/    the same notes as a cross-linked, importable Obsidian vault
```

## Docs

- [docs/OVERVIEW.md](docs/OVERVIEW.md) — the big picture
- [docs/DESIGN.md](docs/DESIGN.md) — why it works this way
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how it's built
- [docs/INTERNALS.md](docs/INTERNALS.md) — the engineering decisions
- [docs/PROTOCOL.md](docs/PROTOCOL.md) — the tile wire protocol
- [docs/SECURITY.md](docs/SECURITY.md) — privacy, encryption, identity scope
- [docs/PLAN.md](docs/PLAN.md) — the hardware build plan (always-on topology + question bank)
- [docs/BRINGUP.md](docs/BRINGUP.md) — the order to make the software physical
- [docs/ROADMAP.md](docs/ROADMAP.md) — the build order
- [docs/BACKLOG.md](docs/BACKLOG.md) — the audit backlog (bugs / fixes / upgrades)

Prefer a graph view? Open the [`obsidian/`](obsidian/) folder as a vault.

## License

TBD.
