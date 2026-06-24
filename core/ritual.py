"""The nightly consolidation cycle — "clear the head."

Once a night (a systemd timer fires `scripts/ritual.sh`, which calls this), Homie
runs a sleep/consolidation pass: snapshot + consolidate memory, sweep expired
returning-unknown faceprints, and a self-healing sweep — then *advises* whether a
restart is warranted. It does the invisible, reversible work in-process and returns
a decision; it NEVER restarts itself (step 6 would kill the very process running it,
so the OS layer enacts any restart from `RitualReport.restart_decision`).

It composes machinery that already exists and is crash-safe:
- `bus.compact(remember.snapshot())` — snapshot + log rotation (DurabilityLog is
  crash-safe by ordering: rotate -> atomic snapshot commit -> delete segment).
- `remember.decay(now)` — age + prune the pattern of life (decay-then-snapshot, the
  same order `scripts/run.py` uses, so the snapshot reflects the consolidated model).
- `supervisor.status()` / `reload()` — the self-healing sweep.

Abort gates fence only the *disruptive* tail (self-heal + restart): if someone is
home/active, a security event is live, or the desktop is mid-game, the invisible
consolidation still runs but nothing is reloaded or restarted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

log = logging.getLogger("homie.ritual")


def _never() -> bool:
    return False


@dataclass(frozen=True)
class RitualGates:
    """Injectable abort predicates. Each defaults to the safe "don't disrupt" answer
    so an unwired gate never *causes* a disruptive step; it only ever prevents one."""

    is_someone_home: Callable[[], bool] = _never
    security_live: Callable[[], bool] = _never
    gaming: Callable[[], bool] = _never


@dataclass
class RitualReport:
    at: float
    compacted: bool = False
    decayed: bool = False
    l4_swept: int = 0
    healed: list[str] = field(default_factory=list)
    health: dict[str, str] = field(default_factory=dict)
    aborted_disruptive: bool = False
    abort_reasons: tuple[str, ...] = ()
    restart_decision: str = "none"  # "none" | "soft" | "reboot" — advisory; the OS enacts it


async def consolidate(
    *,
    bus,
    remember,
    supervisor,
    now: float,
    gates: RitualGates = RitualGates(),
    l4_sweep: Callable[[float], int] | Callable[[float], Awaitable[int]] | None = None,
    changed: bool = False,
) -> RitualReport:
    """Run one consolidation pass and return what it did. Single-shot and
    re-entrant (a systemd oneshot invokes it); never restarts the process."""
    report = RitualReport(at=now)

    # 1+4. Always-run, invisible: consolidate memory. Decay BEFORE the snapshot so the
    # persisted pattern of life is the aged one, then rotate the raw event tail away.
    try:
        remember.decay(now)
        report.decayed = True
        bus.compact(remember.snapshot())
        report.compacted = True
    except Exception:
        log.exception("ritual: memory consolidation failed")

    # 2. Sweep expired returning-unknown (L4) faceprints — TTL hygiene. Injected,
    # since the on-device L4 store lands with perception (it's a no-op until then).
    if l4_sweep is not None:
        try:
            swept = l4_sweep(now)
            report.l4_swept = int(await swept) if hasattr(swept, "__await__") else int(swept)
        except Exception:
            log.exception("ritual: L4 sweep failed")

    # 0. Abort gates fence the disruptive tail only. Consolidation above has run.
    reasons = []
    if gates.is_someone_home():
        reasons.append("home")
    if gates.security_live():
        reasons.append("security")
    if gates.gaming():
        reasons.append("gaming")
    if reasons:
        report.aborted_disruptive = True
        report.abort_reasons = tuple(reasons)
        report.health = supervisor.status()
        log.info("ritual: consolidated; skipped disruptive steps (%s)", ", ".join(reasons))
        return report

    # 5. Self-healing sweep: recover any quarantined/degraded tile.
    status = supervisor.status()
    for name, state in status.items():
        if state in ("QUARANTINED", "DEGRADED"):
            try:
                await supervisor.reload(name)
                report.healed.append(name)
            except Exception:
                log.exception("ritual: reload of '%s' failed", name)
    report.health = supervisor.status()

    # 6. Restart decision — advisory ONLY. The OS wrapper enacts it; we never do.
    unhealthy = any(s not in ("READY",) for s in report.health.values())
    if changed:
        report.restart_decision = "soft"
    elif unhealthy:
        report.restart_decision = "soft"  # something is still wrong — let the OS recycle us
    else:
        report.restart_decision = "none"  # nothing changed and all healthy — head already clear
    log.info("ritual: consolidated; restart=%s healed=%s", report.restart_decision, report.healed)
    return report
