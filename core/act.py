"""Act — the single gateway to the physical home.

Act is the mirror of the mesh bridge: a bus-attached coordinator whose only
external dependency is an injected `HomeClient` (the real Home Assistant / MQTT
client in deploy/, a fake in tests). It consumes `actuator.requested` events,
maps a Homie actuator name to a home entity via the act-map (which is also the
allowlist + never-touch guard), drives the home, and — once the change is
confirmed by a state echo — emits `actuator.done`.

The `CommandLog` here is shared with the StateReconciler (core/reconcile.py): it
records what Homie drove so the resulting state echo can be told apart from a
human action. That distinction is what closes the friction loop.
"""
from __future__ import annotations

import logging
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from core.bus import Priority, Request
from core.capability import CapabilityRegistry
from core.tile import Event

log = logging.getLogger("homie.act")

StateHandler = Callable[[str, object], Awaitable[None]]  # (entity_id, value)

# Map manifest priority level names -> the bus Priority enum (the safety floor).
_PRIORITY = {
    "ambient": Priority.AMBIENT,
    "convenience": Priority.CONVENIENCE,
    "automation": Priority.AUTOMATION,
    "security": Priority.SECURITY,
    "safety": Priority.SAFETY,
}


class HomeClient(Protocol):
    """The single seam to the home. Real impl is an MQTT/HA client; tests fake it."""

    async def drive(self, entity_id: str, command: object) -> None: ...
    def on_state_change(self, handler: StateHandler) -> None: ...


# --------------------------------------------------------------------------- #
# Actuator <-> entity mapping (allowlist + never-touch guard)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ActMap:
    forward: dict[str, str]  # actuator name -> entity_id
    reverse: dict[str, str]  # entity_id -> actuator name
    never_touch: frozenset[str] = frozenset()

    @classmethod
    def from_forward(cls, forward: dict[str, str], never_touch=()) -> "ActMap":
        nt = frozenset(never_touch)
        fwd = {a: e for a, e in forward.items() if e not in nt}  # drop forbidden targets
        return cls(forward=fwd, reverse={e: a for a, e in fwd.items()}, never_touch=nt)

    @classmethod
    def load(cls, path: Path) -> "ActMap":
        raw = tomllib.loads(Path(path).read_text("utf-8"))
        return cls.from_forward(
            raw.get("actuators", {}),
            raw.get("never_touch", {}).get("entities", []),
        )

    def entity_for(self, actuator: str) -> str | None:
        return self.forward.get(actuator)  # None => refuse


# --------------------------------------------------------------------------- #
# Shared echo-suppression record
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PendingCommand:
    entity_id: str
    value: object
    tile: str | None
    at: float


def _identity(value: object) -> object:
    return value


class CommandLog:
    """Records commands Homie issues so the resulting state echo can be matched
    and suppressed. Shared between Act (writer) and StateReconciler (matcher);
    bounded by the reconciliation window. Uses an injectable clock for tests.

    `canonical` normalizes a value to the form the home echoes it back in before
    equality is tested. Homie may drive `{"state": "on", "brightness_pct": 40}`
    while HA echoes brightness as 102/255 — without canonicalization the echo
    wouldn't match, and Homie would read its own command as a human reversal,
    poisoning the friction loop. The default is identity; the real HA adapter
    supplies the entity-aware normalizer."""

    def __init__(
        self,
        window: float = 5.0,
        *,
        clock: Callable[[], float] = time.time,
        canonical: Callable[[object], object] = _identity,
    ) -> None:
        self._window = window
        self._clock = clock
        self._canon = canonical
        self._pending: list[PendingCommand] = []

    def record(self, entity_id: str, value: object, tile: str | None) -> None:
        # store the canonical form so it compares equal to the canonicalized echo
        self._pending.append(PendingCommand(entity_id, self._canon(value), tile, self._clock()))
        self._evict()

    def take_echo(self, entity_id: str, value: object) -> PendingCommand | None:
        """Pop and return a matching outstanding command iff this change is an echo
        within the window; else None. Prefers the MOST RECENT matching command (HA
        state changes carry no correlation id, so recency is the best disambiguator),
        and popping makes each command absorb at most one echo. Both sides are
        canonicalized so differing-but-equivalent representations still match."""
        self._evict()
        target = self._canon(value)
        for i in range(len(self._pending) - 1, -1, -1):  # newest first
            c = self._pending[i]
            if c.entity_id == entity_id and c.value == target:
                return self._pending.pop(i)
        return None

    def forget(self, entity_id: str, value: object) -> bool:
        """Drop the most-recent matching pending command (the drive failed, so no echo will ever
        come). Prevents a never-echoed 'ghost' from absorbing a later unrelated change as ours."""
        target = self._canon(value)
        for i in range(len(self._pending) - 1, -1, -1):
            c = self._pending[i]
            if c.entity_id == entity_id and c.value == target:
                self._pending.pop(i)
                return True
        return False

    def _evict(self) -> None:
        now = self._clock()
        self._pending = [c for c in self._pending if now - c.at <= self._window]


# --------------------------------------------------------------------------- #
# Act
# --------------------------------------------------------------------------- #
class Act:
    def __init__(self, bus, home: HomeClient, commands: CommandLog, act_map: ActMap, *,
                 hold_window: float = 5.0, registry: CapabilityRegistry | None = None) -> None:
        self.bus = bus
        self.home = home
        self.commands = commands
        self.map = act_map
        self.hold_window = hold_window  # how long a winning request "holds" its actuator
        self._holds: dict[str, Request] = {}  # last winner per actuator (for arbitration)
        # The capability registry (C2). When present, Act trusts ONLY a resolvable handle
        # and ignores the payload's actuator/tile/priority. None is the legacy path for the
        # direct-publish unit tests that construct a bare Act — production always injects one
        # via build_daemon, so this is not a production bypass.
        self._caps = registry
        self._sub = None

    async def start(self) -> None:
        self._sub = self.bus.subscribe("actuator.requested", self._on_request, owner="act")

    async def stop(self) -> None:
        if self._sub is not None:
            self.bus.unsubscribe(self._sub)
            self._sub = None

    async def _on_request(self, event: Event) -> None:
        # Capability gate (C2): resolve the handle FIRST and take the authoritative
        # (actuator, priority, tile) from the registry — never from the payload, which a
        # tile could forge. A missing/forged handle is refused before arbitration. The
        # act-map + never_touch still run AFTER this, so the outer boundary stays absolute.
        if self._caps is not None:
            cap = self._caps.resolve(event.payload.get("cap"))
            if cap is None:
                await self.bus.publish(
                    Event("actuator.failed", event.ts,
                          {"actuator": event.payload.get("actuator"), "value": event.payload.get("value"),
                           "tile": event.payload.get("tile"), "reason": "no_capability"}, source="act"))
                return
            actuator, value, tile, level = cap.actuator, event.payload.get("value"), cap.tile, cap.priority
        else:  # legacy path: bare Act in unit tests, no registry — trust the payload as before
            actuator = event.payload.get("actuator")
            value = event.payload.get("value")
            tile = event.payload.get("tile")
            level = event.payload.get("priority", "automation")
        req = Request(actuator, value, _PRIORITY.get(level, Priority.AUTOMATION), tile, event.ts)

        # Arbitration (the bus is the referee): a fresh higher-priority decision
        # "holds" the actuator and suppresses a lower-priority request arriving
        # within the window. Ties go to recency. The hold makes priority real.
        hold = self._holds.get(actuator)
        if hold is not None and (req.at - hold.at) <= self.hold_window:
            winner = await self.bus.arbitrate(actuator, [hold, req])
            if winner is hold:
                log.info("act: '%s' (%s) suppressed by higher-priority hold (%s)", actuator, level, hold.priority.name)
                return
        self._holds[actuator] = req

        entity = self.map.entity_for(actuator)
        if entity is None:
            log.warning("act: '%s' is unmapped (or never-touch) — refused", actuator)
            await self.bus.publish(
                Event("actuator.failed", event.ts,
                      {"actuator": actuator, "value": value, "tile": tile, "reason": "unmapped"},
                      source="act")
            )
            return
        self.commands.record(entity, value, tile)  # record BEFORE drive so the echo can't beat it
        try:
            await self.home.drive(entity, value)
        except Exception as ex:  # the home rejected/failed the command
            self.commands.forget(entity, value)  # no echo will come — drop the ghost we just recorded
            log.warning("act: drive %s failed: %r", entity, ex)
            await self.bus.publish(
                Event("actuator.failed", event.ts,
                      {"actuator": actuator, "value": value, "tile": tile, "reason": "drive_error"},
                      source="act")
            )

    async def confirm(self, cmd: PendingCommand) -> None:
        """Called by the StateReconciler when the home echoes one of our commands:
        the change actually happened, so report it done."""
        actuator = self.map.reverse.get(cmd.entity_id, cmd.entity_id)
        await self.bus.publish(
            Event("actuator.done", time.time(),
                  {"actuator": actuator, "entity_id": cmd.entity_id, "value": cmd.value, "tile": cmd.tile},
                  source="act")
        )
