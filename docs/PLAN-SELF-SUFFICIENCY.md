# Plan — Self-sufficiency (the always-on system cycle)

> Plain-language plan for what the owner asked: a background Homie that *very slowly* grows
> smarter, takes care of itself, and feels alive — *richtig langsam, silent, smooth*. Decided
> by a 5-professional council and made binding in `docs/CHARTER.md` (8a, 13a, 22a, 23a, 25a,
> 28a). This file is the human-readable map of the build order. The status board is
> `docs/PROGRESS.md`.

## The one idea

Homie gets smarter the longer it lives with you — **not by hoarding, but by forgetting noise
faster and keeping proven patterns longer.** Everything below serves that, and everything runs
**silently in the background, nightly**, on the always-on node (your mini-PC + the Pi). You feel
it only as: it runs smoother, knows you a little better each week, and tells you almost nothing
about the housekeeping.

## What's already done (this phase)

- ✅ **The council + the binding rules** (Charter 8a/13a/22a/23a/25a/28a).
- ✅ **The storage limb** (`core/groundskeeper.py`) — silent densify under pressure; a notice
  only when the disk is nearly full (hysteresis + 24h debounce, no nagging).

## The build order (each step ships tested + pushed, suite stays green)

### S1 — Slow, earned memory (the heart of your request) · task #29
*"Langsam mehr merken" done honestly.*
1. **Forgetting first (safety before growth).** Wire GIST's absence-counting + evidence floor +
   a compression-style prune into the nightly ritual, so a stopped routine fades fast and noise
   is dropped. *Without this, "remember more" = hoarding; with it, more retention is safe.*
2. **Then earned retention.** Each pattern's "stickiness" (half-life) grows **only with its own
   sustained evidence** — log-slow, 30 days → capped at 1 year, never global, never for a
   one-off. A routine you've kept for months survives a 3-week holiday; a fluke never does.
3. **Nightly + invisible.** It happens in the existing nightly consolidation. No announcement.
   The felt result: over weeks it just knows you a bit better.
- *Proof:* tests for monotonic-and-capped growth, earned-only (a one-off still decays today's
  way), a stopped routine still fades fast even with a grown half-life, and replay-determinism.

### S2 — The nightly self-cycle: heal + upgrade · task #30
*Self-healing, self-sustaining, self-upgrading — each with its safety rail (Charter 8a/28a).*
1. **Self-heal watchdog.** A heartbeat so a *hung* (not just crashed) daemon is caught and
   restarted; a crash-loop ceiling that escalates to you instead of thrashing; corrupted-state
   falls back to last-good or boots honest-empty and says so.
2. **Health-gated self-upgrade.** Nightly: record last-good → pull (from a vetted internet
   source) → **run the whole test suite as the gate** → atomic switch → re-check health → if
   anything fails, **auto-roll-back** to last-good. A changelog you can read each morning.
3. **The authority freeze (non-negotiable).** Any update that would change what Homie is allowed
   to touch (devices, zones, egress, trust) **fails the gate and waits for your yes — even if all
   tests pass.** It may get better at what it already does; it may never grant itself more.
4. **On the always-on node.** A NixOS systemd timer fires the cycle on the mini-PC/Pi (not the
   GPU desktop with the unsandboxed movie app).

### S3 — Getting to know you (your three "remember" choices) · task #31
*Charter 23a/25a — built behind your informed-consent rule.*
1. **Pattern facts** (already the spine) — made richer: routines, preferences, activities as
   plain words on the "What Homie Knows" page, correctable, fading.
2. **Your self-gallery** — occasional photos of *you*, only the ones you pin, on the Pi,
   encrypted, bounded, one-tap wipe. Never autonomous.
3. **Informed recognition** — others are learned/recognized (vector-only, no photo album) **only
   while you've marked present people informed**; default is store-nothing. Your responsibility.
   Hard lines stay: no off-property, no outward identification, raw frames die at the edge.

## Cross-cutting: extreme compatibility (your core ask · Charter 13a)
- **One OS image, every node.** The same NixOS config + the same `build_daemon` graph run on the
  mini-PC (always-on pillar), the Pi (learning floor), and the desktop (episodic cortex).
- **Stdlib discipline.** Few/no third-party deps, so nothing breaks parity across nodes.
- **The always-on system cycle + developer mode live on the always-on node**, so the box keeps
  improving itself whether or not the desktop is awake.
- Every new piece is checked: *does this run drop-in on all three nodes?* If not, it's the wrong
  choice.

## How we keep it honest
- Every step is **silent, nightly, slow** — the owner feels smoothness, not chatter.
- Every step ships with **tests that fail on the bug and pass on the fix**; the suite only grows.
- Nothing here ever lets Homie **expand its own authority** or **store a non-consenting person**.
- Big sub-decisions still go through a council + chaired synthesis (Charter 40).
