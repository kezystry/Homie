# Backlog — self-* principles, the nightly ritual, and known bugs

A living reminder. Homie's guiding principles: **self-sufficient · self-upgrading ·
self-learning · self-healing · self-autonomous.** Everything below serves one of
them. Decided in expert-panel review (see `obsidian/Decisions log.md`).

---

## The nightly ritual — 23:59 "consolidation cycle" (sleep)

Every night at 23:59, once: **update → heal → consolidate memory → (maybe) restart**
— "clear the head." A sleep/consolidation cycle, not a blunt reboot. It maps onto
machinery we already have: log compaction = memory consolidation, supervisor restart
= healing, NixOS generations = self-upgrading.

**Scheduler:** a **systemd timer** (`OnCalendar=*-*-* 23:59:00`, `Persistent=true`,
`flock`-guarded oneshot) — *not* an in-process loop, because the ritual must be able
to restart the very daemon that would host it. 23:59 is DST-safe (the danger hours are
02:00–03:00). Keep `run.py`'s `_housekeep` only as the append-threshold safety valve.

**Ordered steps — reversible/invisible first, disruptive last and health-gated:**
0. **Abort gates** — skip the restart-bearing steps if someone is **home/active**, a
   **security event** is live, or the desktop is **mid-session (gaming)**; skip the
   *update* on battery or low disk. Consolidation (invisible) can still run.
1. **Pre-flight snapshot** — `bus.compact(remember.snapshot())` now; copy the snapshot
   + mesh keys off-box, **encrypted** (the backup gap).
2. **Self-update (build, don't activate)** — `nixos-rebuild boot` (not `switch`); build
   failure is harmless (offline, running system untouched).
3. **Health-gate the candidate** — start the new daemon, run `check_health()`/`status()`;
   only commit if critical tiles are healthy.
4. **Consolidate memory ("clear the head")** — snapshot the pattern of life, rotate +
   drop the raw event tail; **keep only relevant data + training photos** (see policy
   below); trigger the L4 returning-unknown TTL sweep.
5. **Self-healing sweep** — `reload()` quarantined tiles, recover degraded ones, verify
   mesh peers + roster, fsck `/var/lib/homie` (snapshot loads, no orphan segments).
6. **Commit + restart, LAST and conditional** — prefer a **soft `systemctl restart homie`**
   if only the app changed; full reboot only for kernel/Nix-generation changes; **don't
   restart at all** if nothing changed and tiles are healthy (Step 4 already cleared the head).

**Self-upgrading safely (rollback story):** `nixos-rebuild boot` + a **boot-confirmation
watchdog** — the new generation must check in healthy within minutes or the next boot
auto-reverts to the previous GRUB generation (`configurationLimit=20`). Package
`/opt/homie` as a Nix derivation so app + OS rollback are one mechanism. **Pin and
signature-verify** all update sources (no chasing `nixos-unstable`); **hand-approve**
model-adapter promotions (never auto-promote nightly). `initrd-SSH` remote unlock as the
headless rescue path.

**Memory consolidation policy ("Speicher Leerung"):**
- **KEEP:** the `PatternModel` snapshot (the consolidated pattern of life — tiny);
  **enrolled household faces = the "training photos"** (they live on the perception node,
  outside the bus log, human-curated — *structurally untouchable* by the nightly purge);
  raw events inside a **14–30 day retention window** (re-fold buffer for schema changes);
  security-relevant anomalies (forensic, retained longer).
- **DISCARD:** raw event lines already folded into the snapshot and past the window;
  expired L4 faceprints; transient/noise events.
- **Decay (offline learning, once per night, before compaction):** exponential decay on
  the per-hour counts (half-life ≈ 30 days → counts become floats), a trailing date
  horizon (≈ 90 days) for the `days` denominator, and **drop keys gone silent** — so the
  model tracks a *changing* household instead of diluting old behavior forever.
- **Privacy upside:** nightly purge of the raw timeline means even an unlocked disk yields
  only the aggregate pattern of life, not a minute-resolution diary. Data minimization by
  construction.

---

## Bug / fix / upgrade backlog (prioritized)

From an adversarial code audit. Severity × principle. **Status as of the last
session: #1, #2, #3, #5, #7, #8, #10, #11, #12 are DONE (105 tests). Remaining
software items: #4, #6, #9, #13. Everything else left is hardware/OS/dep-gated
(the main-PC phase): the Noise transport, real MQTT/Frigate clients, Reason.decide
wiring, the nightly-ritual systemd units, and OS validation.**

### High — DONE
1. ~~**Arbitration is dead code [self-autonomous/safety].**~~ DONE: priority in the
   manifest → actuator.requested → Act arbitrates via bus.arbitrate (priority hold). `Bus.arbitrate` is never
   called — `Act._on_request` drives every `actuator.requested` directly, and the payload
   (`Supervisor._make_ctx.act`) carries **no priority**. Two tiles racing one actuator =
   last-arrival-wins, not priority. *Fix:* put a `priority` in the request (from the tile
   manifest), have Act coalesce per-actuator and call `bus.arbitrate`. Until then, "the bus
   is the safety floor" is aspirational.
2. **`Bus.drain()` reads private `Queue._unfinished_tasks` + drop-oldest `task_done()`
   risk [self-healing/correctness].** Replace with an explicit in-flight counter; balance
   the drop-oldest path against it. (Latent crash in the hot path under backpressure.)
3. **Silent drain-task death [self-healing].** If a `_drain` coroutine exits
   (cancellation, `task_done` desync), its mailbox fills forever with no consumer and no
   surfaced fault. *Fix:* a done-callback that logs + respawns or tears down and reports.

### Medium
4. **CommandLog echo-match by `(entity, value)` [correctness/self-learning].** A human
   setting the same value within the window is mistaken for Homie's echo → friction lost.
   *Fix:* correlation token through `drive()` where the home supports it; else bound + document.
5. **The model never forgets [self-learning].** No decay; `_dates` grows unbounded; a
   changed routine dilutes forever. → the nightly **decay rule** above (the single biggest
   self-learning upgrade).
6. **Timezone/DST in hour-bucketing [correctness].** `datetime.fromtimestamp(...).hour` is
   naive local time; snapshots store no TZ, so restore on a differently-configured host
   mis-buckets. *Fix:* pin the home TZ, compute with a fixed `ZoneInfo`, record it in the snapshot.
7. **Mesh `_seq` resets to 0 on restart [correctness].** After a reboot a peer's `_seen`
   may drop the fresh node's low-seq events as duplicates → silent loss. *Fix:* persist
   `_seq` or add a per-boot nonce to the dedup key.
8. **Mesh link errors swallowed as handler faults [self-healing].** `_on_local`/`_on_remote`
   don't guard `link.send`; a dropped link masquerades as a tile fault, no retry/surfacing.
9. **Single-resident friction attribution [self-learning].** "most-recent-act wins" misfires
   with overlapping tiles; `note_manual` picks by dict order. *Fix:* scope by actuator/zone.

### Low / hygiene
10. **`_housekeep` is fire-and-forget [self-sufficiency].** If it dies, compaction stops and
    the log grows unbounded — the exact SD-wear failure it prevents. *Fix:* hold the ref,
    done-callback to log + restart, wrap the body in try/except.
11. **`TileState.put` not atomic [self-healing].** Direct `write_text`; a crash mid-write
    corrupts a tile's `data.json`. *Fix:* temp-file + `os.replace` (like the bus snapshot).
12. **`note_manual` counters never decay / leak [self-sufficiency].** No time-window; stale
    actuator keys persist. *Fix:* window the repeats (like `fault_times`), prune aged keys.
13. **`SubprocessChannel` stderr not piped; `_exchange` holds the lock across `readline()`.**
    A crashing isolated tile's traceback vanishes; a wedged child blocks the channel. *Fix:*
    pipe stderr; per-call timeout that kills + faults the process.

### Upgrades (net-new, beyond fixes)
- Wire the nightly ritual (systemd units + `scripts/ritual.sh`) — the headline feature.
- The pattern-decay step in `Remember` (self-learning) — pairs with the ritual.
- Atomic `TileState.put` + `/opt/homie` as a Nix derivation (self-upgrading/healing).
- Persisted/encrypted off-box backup of `/var/lib/homie` (self-sufficiency).
