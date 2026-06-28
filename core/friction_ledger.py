"""Friction Ledger — every action Homie took, as a plain row you can undo.

The record half of the undo button (Charter #24). It listens for `actuator.done` (only
CONFIRMED actions — the home actually changed), and remembers each one *with the value it had
before*, so an undo can restore the prior state rather than guess an inverse. Each row renders
as a plain sentence ("7:32pm · turned the kitchen light on"), newest first, ready for a one-tap
undo.

PURE of any drive: this only records and computes what an undo *would* do. Issuing the inverse
goes back through the capability-gated act path (the next slice), so undo can never become a
side-door around the safety rails. Holds the bus only to subscribe; the row logic is testable
without it.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime

from core.canonical import ha_canonical
from core.tile import Event

log = logging.getLogger("homie.ledger")

ACTUATOR_DONE = "actuator.done"


@dataclass(frozen=True)
class Action:
    """One thing Homie did. `prior` is the value the actuator held just before — what an undo
    restores. `prior is None` means Homie had never touched it, so the prior state is unknown
    and a clean undo isn't possible (the row says so)."""

    id: int
    ts: float
    actuator: str
    value: object
    prior: object | None
    tile: str | None
    undone: bool = False

    @property
    def reversible(self) -> bool:
        return self.prior is not None and not self.undone


def _onoff(value: object) -> str:
    state = ha_canonical(value).state
    return state if state in ("on", "off") else "set"


def _subject(actuator: str) -> str:
    """`light.kitchen` -> 'the kitchen light'. Plain, never the raw id."""
    domain, _, rest = actuator.partition(".")
    where = rest.replace("_", " ") or actuator
    return f"the {where} light" if domain == "light" else f"the {where}"


def _clock(ts: float, tz=None) -> str:
    dt = datetime.fromtimestamp(ts, tz) if tz else datetime.fromtimestamp(ts)
    h, m = dt.hour, dt.minute
    return f"{h % 12 or 12}:{m:02d}{'am' if h < 12 else 'pm'}"


def describe(action: Action, *, tz=None) -> str:
    """A plain past-tense sentence for the row."""
    verb = _onoff(action.value)
    body = (f"turned {_subject(action.actuator)} {verb}" if verb in ("on", "off")
            else f"changed {_subject(action.actuator)}")
    line = f"{_clock(action.ts, tz)} · {body}"
    return line + " (undone)" if action.undone else line


class FrictionLedger:
    """Records confirmed actions as reversible rows. Wire in `build_daemon`; `start()` after
    Act. `recent()`/`describe()` feed the cockpit + status page; `inverse()` is what one-key
    undo will re-drive; `mark_undone()` flips a row once the inverse is confirmed."""

    def __init__(self, bus, *, keep: int = 200) -> None:
        self.bus = bus
        self._current: dict[str, object] = {}     # actuator -> last known value
        self._rows: deque = deque(maxlen=keep)
        self._next_id = 1
        self._sub = None

    async def start(self) -> None:
        self._sub = self.bus.subscribe(ACTUATOR_DONE, self._on_done, owner="ledger")

    async def stop(self) -> None:
        if self._sub is not None:
            self.bus.unsubscribe(self._sub)
            self._sub = None

    async def _on_done(self, event: Event) -> None:
        a = event.payload.get("actuator")
        if a is None:
            return
        value = event.payload.get("value")
        prior = self._current.get(a)              # what it was before this action
        self._rows.append(Action(self._next_id, event.ts, a, value, prior,
                                 event.payload.get("tile")))
        self._next_id += 1
        self._current[a] = value

    # -- reads (pure) --------------------------------------------------------- #
    def recent(self, n: int = 10) -> list[Action]:
        """The newest actions first (the undo timeline)."""
        return list(self._rows)[-n:][::-1]

    def get(self, action_id: int) -> Action | None:
        for a in self._rows:
            if a.id == action_id:
                return a
        return None

    def inverse(self, action_id: int) -> tuple[str, object] | None:
        """The (actuator, value) an undo would drive to restore the prior state — or None if
        the row is unknown, already undone, or has no recorded prior."""
        a = self.get(action_id)
        if a is None or not a.reversible:
            return None
        return (a.actuator, a.prior)

    def mark_undone(self, action_id: int) -> None:
        for i, a in enumerate(self._rows):
            if a.id == action_id:
                self._rows[i] = replace(a, undone=True)
                self._current[a.actuator] = a.prior   # the world is back to prior
                return

    def lines(self, n: int = 10, *, tz=None) -> list[str]:
        return [describe(a, tz=tz) for a in self.recent(n)]
