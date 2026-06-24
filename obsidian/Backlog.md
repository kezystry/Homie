---
tags: [homie, plan, questions]
---

# Backlog

Bugs, fixes, and upgrades — a living reminder, from an adversarial code audit
(83 tests pass; architecture sound). Full detail in the repo's `BACKLOG.md`.
Grouped by the five self-* principles.

## High
- **Arbitration is dead code** [self-autonomous] — [[Act]] drives `actuator.requested`
  directly; the payload carries no priority, so [[Bus]] `arbitrate` never runs. The
  "bus is the safety floor" guarantee isn't wired yet. *Fix:* priority in the request +
  coalesce + arbitrate.
- **`Bus.drain()` uses a private attr + drop-oldest `task_done` risk** [self-healing] —
  replace with an explicit in-flight counter.
- **Silent drain-task death** [self-healing] — a dead `_drain` fills its mailbox forever,
  unseen. *Fix:* respawn/teardown via a done-callback.

## Medium
- **CommandLog echo-match by (entity,value)** [self-learning] — a human setting the same
  value is mistaken for Homie's echo; friction lost.
- **The model never forgets** [self-learning] — no decay; → the [[Nightly ritual]] decay rule.
- **Timezone/DST hour-bucketing** [correctness] — pin the home TZ; record it in the snapshot.
- **Mesh `_seq` resets on restart** [correctness] — fresh events dropped as duplicates after a reboot.
- **Mesh link errors swallowed** [self-healing] — surfaced as tile faults, no retry.
- **Single-resident friction attribution** [self-learning] — "most-recent-act wins" misfires.

## Low / hygiene
- `_housekeep` fire-and-forget (compaction silently stops) · `TileState.put` not atomic ·
  `note_manual` counters never decay · `SubprocessChannel` stderr not piped + lock held across readline.

## Upgrades (net-new)
- Wire the [[Nightly ritual]] (systemd units + ritual.sh) — the headline feature.
- Pattern-decay in [[Remember]] · atomic `TileState.put` · `/opt/homie` as a Nix derivation ·
  encrypted off-box backup of the pattern of life.
