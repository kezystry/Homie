# Design

Homie is built as an organism, not a program: a **minimal core** and a **colony
of autonomous tiles**.

## The spine

Everything reduces to one loop:

1. **Perceive** — the sensor head turns thermal, radar, and camera input into
   clean events.
2. **Remember** — events accumulate into a pattern of life. *Behavioral
   Analysis* — the heart.
3. **Reason** — the local LLM weighs "now" against "normal" and decides what
   matters.
4. **Act** — Home Assistant carries out the decision.
5. **Interface** — voice-first; you ask and correct, it tells and asks. The
   window into the loop.

## Learning by friction

Homie optimizes for one thing: **needing you less over time.** It learns mostly
without a word from you.

- **Silence = approval** — no reaction reinforces what it did.
- **Reversal = correction** — you undo its action (light back off, thermostat
  back); that *is* the feedback, logged against what it just did.
- **Repeated manual action = missing pattern** — something you keep doing by
  hand is a behavior it should learn to offer.
- **Explicit remark = strongest** — when you do speak, it overrides the rest.

Success is the *declining rate of corrections.*

## Core + tiles

- **Fixed core** — the spine, plus **Security**, which emerges for free once
  Remember and Reason exist.
- **Open slot** — everything else is a **tile**: a self-contained capability
  that plugs into the spine. Personal Assistant, Kitchen, and domain tiles are
  the first; Personal Assistant is the reference. New functions are new tiles.

## The tile contract

A tile declares what it touches; the core wires it in.

1. **Subscribes** — the events and patterns it listens for.
2. **Provides** — voice intents you can speak and functions the LLM may call.
3. **Acts** — the actuators it is allowed to drive.
4. **Permissions** — what data it may read, and whether anything leaves the
   network. Default: local-only.
5. **Friction** — corrections to its actions route back to it; it learns under
   the same rule as the core.
6. **Living** — every tile is autonomous:
   - *Self-learning* — runs its own friction loop.
   - *Self-healing* — monitors itself, recovers from its own faults, degrades
     quietly instead of crashing the system.
   - *Self-dependent* — owns its state, config, and secrets; needs no other tile
     to function.

The core stays minimal — **perceive, remember, route, arbitrate.** Intelligence
and resilience live in the cells. The physical layout that follows from this is
in [`ARCHITECTURE.md`](ARCHITECTURE.md).
