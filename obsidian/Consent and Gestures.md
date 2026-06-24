---
tags: [homie, component, built, decision]
---

# Consent and Gestures

How Homie asks for a yes/no on the bigger things — **wordlessly**, by reading a
**head nod (yes) / shake (no)** through the camera (voice is always an equal fallback).

## Core (built) — `core/consent.py`
- `ctx.confirm(prompt, risk=...) -> bool`. Consent publishes `confirm.requested`,
  awaits the matching `confirm.response` by id, with a timeout that **fails safe to
  No** (silence is not consent for an ask).
- The response is produced later by a Pi-side **gesture detector** (nod→yes, shake→no)
  or voice — the core only consumes the event, like Frigate's perception events.

## Policy (decided; see [[Decisions log]])
- **Act-silent** on anything a reversal cheaply undoes (the [[Spine|friction]] net handles it).
- **Confirm** only consequential-but-reversible actions; **never** a gesture for a
  lock/garage/safety actuator — those stay never-autonomous via `act_map.toml`.
- Gesture only counts **inside the prompt window**, from a [[Security and Identity|known face]];
  non-response = No.
- **Decay**: a repeatedly-nodded action *graduates* to act-silent — Homie learns to ask less.
