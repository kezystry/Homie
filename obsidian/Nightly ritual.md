---
tags: [homie, concept, decision]
---

# Nightly ritual

Every night at **23:59**, once: a sleep/consolidation cycle —
**update → heal → consolidate memory → (maybe) restart** — to *clear the head*.
The five self-* principles made concrete: self-sufficient, self-upgrading,
self-learning, self-healing, self-autonomous.

It reuses machinery we already have: log compaction ([[Bus]]) = memory
consolidation, supervisor restart = healing, NixOS generations = self-upgrading.

## Scheduler
A **systemd timer** (`OnCalendar=23:59`, `Persistent=true`, `flock`-guarded), not an
in-process loop — the ritual must be able to restart its own daemon. 23:59 is DST-safe.

## Ordered steps (reversible first, disruptive last & health-gated)
0. **Abort gates** — skip restart steps if someone's home/active, a [[Security and Identity|security event]] is live, or the desktop is gaming.
1. Pre-flight snapshot + encrypted off-box backup.
2. Build the update (`nixos-rebuild boot`, don't activate).
3. Health-gate the candidate (`check_health`/`status`).
4. **Consolidate memory** — snapshot the pattern of life ([[Remember]]), drop the raw tail; keep relevant data + **training photos**.
5. **Self-healing sweep** — reload quarantined tiles, recover degraded ones, verify [[Mesh]] peers, fsck state.
6. Commit + restart **last, conditional** — soft restart if only the app changed; no restart if nothing changed.

## What's kept vs cleared (Speicher Leerung)
- **KEEP:** the consolidated [[Remember|pattern of life]]; **enrolled faces = the training
  photos** (on the perception node, human-curated, untouchable by the purge); raw events
  in a 14–30 day window; security anomalies.
- **DISCARD:** folded-and-aged raw events; expired returning-unknown faceprints; noise.
- **Decay:** ~30-day half-life on counts + ~90-day date horizon + drop silent keys, so the
  model tracks a *changing* household (the biggest self-learning upgrade).
- **Privacy win:** the raw minute-by-minute timeline is forgotten nightly; only the aggregate remains.

## Self-upgrading safely
`nixos-rebuild boot` + a boot-confirmation watchdog that auto-reverts to the previous
generation if the new one doesn't check in healthy. Pin + signature-verify sources;
hand-approve model-adapter promotions. See [[Decisions log]] and [[Backlog]].
