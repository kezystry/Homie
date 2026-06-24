# Tiles

A tile is a self-contained capability that plugs into the spine. The core
discovers tiles and routes to them; it never imports one, so a broken tile
cannot take down the system.

Every tile is the same five-part folder:

```
tiles/<name>/
├── tile.toml   # manifest — the contract: subscribes · provides · acts · permissions
├── handlers.py # reactions to events and the functions it provides
├── learn.py    # self-learning — adapt from friction signals
├── health.py   # self-healing — report fitness; the supervisor recovers failures
└── state/      # self-dependent — its own config, secrets, and data (never committed)
```

To add a capability, copy [`_template/`](_template/) to `tiles/<name>/` and fill
it in. Self-learning, self-healing, and isolation are guaranteed by the runtime
(`core/tile.py`); the tile only declares its behaviour.

[`personal/`](personal/) is the reference implementation.
