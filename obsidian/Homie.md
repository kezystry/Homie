---
tags: [homie, moc]
---

# Homie

> Private, local-first home intelligence — *the Machine*, reimagined for your home.

This is the map of the whole project. Prose lives in the repo (`docs/OVERVIEW.md`,
`docs/DESIGN.md`, `docs/PLAN.md`); these notes are the linked, importable version.

## The system
- [[Spine]] — the loop: Perceive → [[Remember]] → [[Reason]] → [[Act]] → Interface
- [[Core and Tiles]] — a minimal core + a colony of living tiles
- [[Bus]] · [[Remember]] · [[Reason]] · [[Act]] · [[Mesh]] · [[Consent and Gestures]]
- [[Security and Identity]]

## Building it
- [[Always-on topology]] · [[Hardware]] · [[Roadmap]] · [[Open questions]]
- [[Nightly ritual]] (the 23:59 sleep cycle) · [[Backlog]] (bugs/fixes/upgrades)
- [[Bring-up]] (code → running home) · [[Decisions log]] · [[Glossary]]

## Status
Reasoning-node spine built and tested (**169 stdlib tests**). Working: the bus,
behavioral memory, the tile runtime, Personal + Security tiles, the friction loop,
tool-call schemas, and the confirmation gate. The outward edges — local LLM,
Home Assistant control, voice, the sensor head — are next.
