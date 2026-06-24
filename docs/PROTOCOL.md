# Tile protocol

The boundary between the core and a tile is a set of JSON messages — never a
shared Python class. In-process tiles run this protocol short-circuited in
memory; out-of-process tiles speak it as **line-delimited JSON over stdio**. The
core couples to the protocol, not to tile code, so a tile can be written in any
language and isolated to any degree without the core changing.

## Lifecycle

1. **init** — core → tile: `{"type": "init", "manifest": {…}, "state_dir": "…"}`
2. tile → core: `{"type": "ready"}` or `{"type": "error", "error": "…"}`
3. … steady-state messages below …
4. **stop** — core → tile: `{"type": "stop"}`; tile drains and exits.

## Core → tile

| Message | Meaning |
|---------|---------|
| `{"type": "event", "event": {"topic", "ts", "payload"}}` | A subscribed event. |
| `{"type": "friction", "signal": {"kind", "at", …}}` | A correction to learn from (`reversal` / `repeat` / `remark`). |
| `{"type": "call", "fn", "args"}` | Invoke a manifest `function`; expects a `result`. |
| `{"type": "health"}` | Probe; expects a `health` reply. |
| `{"type": "stop"}` | Shut down. |

## Tile → core

| Message | Meaning |
|---------|---------|
| `{"type": "act", "actuator", "value"}` | Drive an actuator. The core stamps it with an `action_id` + tile name for friction attribution. |
| `{"type": "emit", "event": {…}}` | Publish an event to the bus. |
| `{"type": "speak", "text"}` | Say something through the Interface. |
| `{"type": "result", "value"}` | Reply to a `call`. |
| `{"type": "health", "ok": true}` | Reply to a `health` probe. |
| `{"type": "log", "level", "msg"}` | Structured log line. |

## Rules

- **stdout is protocol only.** Out-of-process tiles must log via `log` messages
  or stderr — never bare `print` to stdout (it corrupts the stream).
- **The core enforces permissions on every message**, not by convention: an
  `act` on an actuator not in `manifest.actuators` is rejected; an outbound
  connection is allowed only if `manifest.network = "egress:<host>"`.
- **Acts are stamped** with `(action_id, tile, actuator, value, at)` into the
  core's action ledger — this is what lets a later reversal be matched back to
  the tile that caused it.
- The same message dicts are passed in-memory for in-process tiles; the schema
  is identical across both transports.
