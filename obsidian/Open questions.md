---
tags: [homie, questions]
---

# Open questions

Live design questions (the full 63-item hardware/setup bank is in the repo's `docs/PLAN.md` §9).

## Conceptual
- **How [[Reason]] consumes [[Remember]]** — is a per-(topic,zone,hour) rate enough, or does it
  need transitions/sessions/multi-zone context? Where does richer structure live?
- **Multi-resident friction** — attribution is global today; two people disagreeing thrashes it.
  Per-identity scoping? (also bears on [[Consent and Gestures|whose nod counts]]).
- **Gate Reason by novelty** so the GPU only wakes when *now* diverges from *normal* (decided: yes).
- **Backup/restore/portability** of the pattern of life across the encrypted [[Mesh]] without exposing it.
- **Tile marketplace + WASM** as a third isolation tier for untrusted tiles.
- **Failure UX** — a quarantined tile / dropped node should *surface*, not go silently dark.

## Decisions already taken
See [[Decisions log]].
