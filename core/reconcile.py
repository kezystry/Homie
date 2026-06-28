"""StateReconciler — the friction producer.

Observes the home's state changes (via the same injected HomeClient Act uses) and
turns the HUMAN-caused ones into the friction signals the Supervisor already
consumes. The hard part is breaking the feedback loop: a change Homie itself
caused echoes back from the home and must not be read as a human action. The
shared CommandLog suppresses those echoes; everything else is a human action.

Closes the loop the design flagged as the missing producer — with zero Supervisor
changes (it just calls the existing note_reversal / note_manual).
"""
from __future__ import annotations

import time
from typing import Awaitable, Callable

from core.act import CommandLog, HomeClient, PendingCommand


class StateReconciler:
    def __init__(
        self,
        supervisor,  # has note_reversal / note_manual
        commands: CommandLog,  # shared with Act
        entity_to_actuator: dict[str, str],
        *,
        on_echo: Callable[[PendingCommand], Awaitable[None]] | None = None,
        on_correction: Callable[[str, str | None, str | None, float], Awaitable[None]] | None = None,
        context: Callable[[str], tuple[str | None, str | None]] | None = None,
    ) -> None:
        self.sup = supervisor
        self.commands = commands
        self.rev = entity_to_actuator
        self.on_echo = on_echo
        # Called when a HUMAN reversal of Homie's own act is detected (a real correction) — the
        # measurable signal the nightly self-improvement loop counts. Optional.
        self.on_correction = on_correction
        # Optional: resolve (zone, actor) for an entity at the moment of a human
        # change — e.g. the zone the actuator lives in and who is present (L2
        # label). Stamped onto the friction signal for per-person learning and the
        # privacy exclusions. Returns (None, None) when unknown.
        self.context = context

    def attach(self, home: HomeClient) -> None:
        home.on_state_change(self.on_state_change)

    async def on_state_change(self, entity_id: str, value: object) -> None:
        echo = self.commands.take_echo(entity_id, value)
        if echo is not None:  # Homie's own command — suppress; let Act confirm done
            if self.on_echo is not None:
                await self.on_echo(echo)
            return
        actuator = self.rev.get(entity_id)
        if actuator is None:  # unmapped / never-touch entity — never our concern
            return
        at = time.time()
        zone, actor = self.context(entity_id) if self.context else (None, None)
        sig = await self.sup.note_reversal(actuator, value, at, zone=zone, actor=actor)  # reverses a tile's act?
        if sig is None:  # no recent Homie act on it — a manual action
            await self.sup.note_manual(actuator, at, zone=zone, actor=actor)
        elif self.on_correction is not None:  # a real correction of Homie — count it for self-improvement
            await self.on_correction(actuator, zone, actor, at)
