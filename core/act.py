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

from core.tile import Event

log = logging.getLogger("homie.act")

StateHandler = Callable[[str, object], Awaitable[None]]  # (entity_id, value)


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


class CommandLog:
    """Records commands Homie issues so the resulting state echo can be matched
    and suppressed. Shared between Act (writer) and StateReconciler (matcher);
    bounded by the reconciliation window. Uses an injectable clock for tests."""

    def __init__(self, window: float = 5.0, *, clock: Callable[[], float] = time.time) -> None:
        self._window = window
        self._clock = clock
        self._pending: list[PendingCommand] = []

    def record(self, entity_id: str, value: object, tile: str | None) -> None:
        self._pending.append(PendingCommand(entity_id, value, tile, self._clock()))
        self._evict()

    def take_echo(self, entity_id: str, value: object) -> PendingCommand | None:
        """Pop and return a matching outstanding command iff this change is an echo
        within the window; else None. Popping makes each command absorb one echo."""
        self._evict()
        for i, c in enumerate(self._pending):
            if c.entity_id == entity_id and c.value == value:
                return self._pending.pop(i)
        return None

    def _evict(self) -> None:
        now = self._clock()
        self._pending = [c for c in self._pending if now - c.at <= self._window]


# --------------------------------------------------------------------------- #
# Act
# --------------------------------------------------------------------------- #
class Act:
    def __init__(self, bus, home: HomeClient, commands: CommandLog, act_map: ActMap) -> None:
        self.bus = bus
        self.home = home
        self.commands = commands
        self.map = act_map
        self._sub = None

    async def start(self) -> None:
        self._sub = self.bus.subscribe("actuator.requested", self._on_request, owner="act")

    async def stop(self) -> None:
        if self._sub is not None:
            self.bus.unsubscribe(self._sub)
            self._sub = None

    async def _on_request(self, event: Event) -> None:
        actuator = event.payload.get("actuator")
        value = event.payload.get("value")
        tile = event.payload.get("tile")
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
