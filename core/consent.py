"""Consent — the confirmation gate (ask on the bigger things).

Homie is highly autonomous: it acts silently on anything a reversal can cheaply
undo, and learns from the friction. For consequential-but-reversible actions it
asks for a yes/no. A tile (or Reason) asks via ctx.confirm(); Consent publishes
`confirm.requested` and awaits the matching `confirm.response` by id, with a
timeout that FAILS SAFE (default: no — silence is not consent for an ask).

The response is produced later by a Pi-side gesture detector (a head nod → yes,
a shake → no) or by voice — Consent only consumes the event, exactly as the core
consumes Frigate's perception events. Never let a gesture confirm a safety-
critical actuator (locks/garage); those stay never-autonomous, enforced by the
act-map, not here.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable
from uuid import uuid4

from core.tile import Event


class Consent:
    def __init__(self, bus, *, timeout: float = 30.0, default: bool = False, clock: Callable[[], float] = time.time) -> None:
        self.bus = bus
        self._timeout = timeout
        self._default = default  # what timeout / teardown resolves to; False = don't act
        self._clock = clock
        self._pending: dict[str, asyncio.Future] = {}
        self._sub = None

    async def start(self) -> None:
        self._sub = self.bus.subscribe("confirm.response", self._on_response, owner="consent")

    async def stop(self) -> None:
        if self._sub is not None:
            self.bus.unsubscribe(self._sub)
            self._sub = None
        for fut in self._pending.values():  # fail safe on teardown
            if not fut.done():
                fut.set_result(self._default)
        self._pending.clear()

    async def request(self, prompt: str, *, actuator: str | None = None, risk: str = "medium", timeout: float | None = None) -> bool:
        """Open a confirmation, await the matching response, resolve yes/no/timeout."""
        cid = uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._pending[cid] = fut
        await self.bus.publish(
            Event("confirm.requested", self._clock(),
                  {"id": cid, "prompt": prompt, "actuator": actuator, "risk": risk},
                  source="consent")
        )
        try:
            return await asyncio.wait_for(fut, timeout=timeout or self._timeout)
        except asyncio.TimeoutError:
            return self._default  # no answer → fail safe
        finally:
            self._pending.pop(cid, None)

    async def _on_response(self, event: Event) -> None:
        cid = event.payload.get("id")
        fut = self._pending.get(cid)
        if fut is None or fut.done():  # unmatched / stale / already resolved → ignore
            return
        fut.set_result(bool(event.payload.get("yes")))
