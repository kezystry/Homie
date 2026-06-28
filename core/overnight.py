"""Overnight — the honest morning word for the nightly self-renewal routine.

Every night Homie consolidates memory, distills the day into the GIST, sweeps stale faceprints,
self-heals any sick tile, and (on the OS layer) pulls + health-checks a self-upgrade. All of
that is meant to be **invisible** — the owner asked for "silent, smooth." So the routine speaks
NOTHING for routine housekeeping. It speaks ONE plain line in the morning only when something
the owner would actually want to know happened overnight:

  * a fault healed        — "I fixed the lighting tile overnight."
  * an upgrade landed     — "I updated myself overnight." / "…held an update for your okay."
  * an upgrade rolled back — "An update didn't look right, so I undid it."

The fold itself (memory growing) is never spoken — it is surfaced on demand (the "what changed
last night" detail), never pushed. This module is split the project's usual way:

  * `compose()`     — a PURE function: (RitualReport, FoldSummary, upgrade) → the one line + detail.
  * `OvernightDesk` — the thin stateful seam: stash the night's composed report, speak its one
                      line ONCE on the morning, and write a machine-readable `.report` file so the
                      upgrade oneshot can gate its restart on "nothing disruptive is happening."

Nothing here ever leaks specifics into speech: titles, identities, and raw events never reach a
spoken line (the fold summary carries only learned/faded clauses, shown on demand, never said).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("homie.overnight")


@dataclass(frozen=True)
class OvernightReport:
    """What the morning should say (or not), plus the full picture for an on-demand glance."""

    spoke: str | None = None              # the ONE merged morning line, or None = stay silent
    detail: tuple[str, ...] = ()          # the full "what happened last night" lines (on demand)


def _fold_detail(fold) -> list[str]:
    """The on-demand memory-change lines (never spoken). Honest, count-led, contentless-by-default."""
    out: list[str] = []
    if fold is None or not getattr(fold, "changed", False):
        return out
    if fold.learned:
        out.append("Learned: " + ", ".join(fold.learned))
    if fold.faded:
        out.append("Let go: " + ", ".join(fold.faded))
    if fold.forgotten:
        out.append(f"Forgot {fold.forgotten} faded {'thing' if fold.forgotten == 1 else 'things'}.")
    return out


def compose(report, *, fold=None, upgrade: str | None = None) -> OvernightReport:
    """Compose the morning word from the night's work. PURE — no I/O, no clock.

    `report`  — the `RitualReport` from `ritual.consolidate()` (or None if nothing ran).
    `fold`    — the `gist.FoldSummary` of the night's distill (or None).
    `upgrade` — one of {None, "applied", "rolledback", "held", "deferred"} from the upgrade
                oneshot. "deferred" (it waited because you were busy/watching) stays SILENT —
                it isn't a fault and isn't news; trying again tomorrow is the normal path.

    Routine housekeeping (compact/decay/distill) is SILENT. We speak only a healed fault or an
    upgrade outcome worth knowing, merged into one line. The fold delta is detail-only.
    """
    said: list[str] = []
    if report is not None:
        for name in report.healed:
            said.append(f"fixed the {name} tile")
    if upgrade == "applied":
        said.append("updated myself")
    elif upgrade == "rolledback":
        said.append("undid an update that didn't look right")
    elif upgrade == "held":
        said.append("held an update for your okay")

    spoke = None
    if said:
        # One natural sentence: "Overnight I fixed the lighting tile and updated myself."
        if len(said) == 1:
            body = said[0]
        else:
            body = ", ".join(said[:-1]) + " and " + said[-1]
        spoke = f"Overnight I {body}."

    detail: list[str] = []
    if report is not None:
        if report.healed:
            detail.append("Healed: " + ", ".join(report.healed))
        if report.aborted_disruptive:
            detail.append("Held the disruptive steps (" + ", ".join(report.abort_reasons) + ").")
    if upgrade:
        detail.append({"applied": "Update applied.", "rolledback": "Update rolled back.",
                       "held": "Update held for your okay.",
                       "deferred": "Update deferred — you were busy."}.get(upgrade, ""))
    detail += _fold_detail(fold)
    return OvernightReport(spoke=spoke, detail=tuple(d for d in detail if d))


def report_dict(report, *, media_live: bool = False) -> dict:
    """The machine-readable snapshot the upgrade oneshot reads to decide if it may restart.
    Plain JSON-able scalars only — no schema state, no identifiers."""
    if report is None:
        return {"present": False}
    return {
        "present": True,
        "at": report.at,
        "aborted_disruptive": bool(report.aborted_disruptive),
        "abort_reasons": list(report.abort_reasons),
        "restart_decision": report.restart_decision,
        "healed": list(report.healed),
        "media_live": bool(media_live),
    }


def safe_to_disrupt(report: dict | None) -> tuple[bool, str]:
    """Read a `report_dict` and answer whether the OS layer may restart/upgrade now. Fail-safe:
    a missing/old/unreadable report means 'not safe' (we never disrupt on no information)."""
    if not report or not report.get("present"):
        return False, "no fresh nightly report"
    if report.get("media_live"):
        return False, "media is playing"
    if report.get("aborted_disruptive"):
        return False, "consolidation held (" + ", ".join(report.get("abort_reasons") or []) + ")"
    return True, "clear"


class OvernightDesk:
    """The thin stateful seam around `compose()`.

    It holds the most recent night's composed report, speaks its one line ONCE on the next
    morning (`time.morning`), and writes the machine-readable `.report` file the upgrade oneshot
    reads. Routine-silent: if `compose()` returned no line, the morning passes wordless.
    """

    def __init__(self, bus, *, report_path: Path | str | None = None) -> None:
        self.bus = bus
        self._report_path = Path(report_path) if report_path else None
        self._pending: OvernightReport | None = None
        self._last_detail: tuple[str, ...] = ()
        self._subs: list = []

    async def start(self) -> None:
        self._subs = [self.bus.subscribe("time.morning", self._on_morning, owner="overnight")]

    async def stop(self) -> None:
        for s in self._subs:
            self.bus.unsubscribe(s)
        self._subs = []

    def detail(self) -> list[str]:
        """The on-demand 'what happened last night' lines (for /status or a question)."""
        return list(self._last_detail)

    def record(self, overnight: OvernightReport, report, *, media_live: bool = False) -> None:
        """Stash the composed report to speak in the morning, and write the machine-readable
        snapshot for the upgrade oneshot. Never raises into the caller (best-effort file write)."""
        self._pending = overnight
        self._last_detail = overnight.detail
        if self._report_path is not None:
            try:
                self._report_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._report_path.with_suffix(self._report_path.suffix + ".tmp")
                tmp.write_text(json.dumps(report_dict(report, media_live=media_live),
                                          separators=(",", ":")), "utf-8")
                os.replace(tmp, self._report_path)
            except Exception:
                log.warning("overnight: could not write %s", self._report_path)

    async def _on_morning(self, event) -> None:
        pending, self._pending = self._pending, None
        if pending is None or pending.spoke is None:
            return
        from core.tile import Event
        await self.bus.publish(Event("interface.say", float(event.ts),
                                     {"text": pending.spoke, "kind": "overnight"}, source="overnight"))
