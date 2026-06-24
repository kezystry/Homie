---
tags: [homie, moc]
---

# Homie

> Private, local-first home intelligence — *the Machine*, reimagined for your home.

This is the map of the whole project. Prose lives in the repo (`OVERVIEW.md`,
`DESIGN.md`, `PLAN.md`); these notes are the linked, importable version.

## The system
- [[Spine]] — the loop: Perceive → [[Remember]] → [[Reason]] → [[Act]] → Interface
- [[Core and Tiles]] — a minimal core + a colony of living tiles
- [[Bus]] · [[Remember]] · [[Reason]] · [[Act]] · [[Mesh]] · [[Consent and Gestures]]
- [[Security and Identity]]

## Building it
- [[Always-on topology]] · [[Hardware]] · [[Roadmap]] · [[Open questions]]
- [[Decisions log]] · [[Glossary]]

## Status
Reasoning-node spine built and tested (**83 stdlib tests**). Working: the bus,
behavioral memory, the tile runtime, Personal + Security tiles, the friction loop,
tool-call schemas, and the confirmation gate. The outward edges — local LLM,
Home Assistant control, voice, the sensor head — are next.
