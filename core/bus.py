"""Event routing and arbitration — the only referee in the system.

Tiles never call each other. They publish and subscribe through the bus, and
when two tiles want the same actuator the bus arbitrates.
"""
from __future__ import annotations


class Bus:
    async def publish(self, event) -> None: ...

    def subscribe(self, pattern: str, handler) -> None: ...

    async def arbitrate(self, actuator: str, requests):
        """Resolve competing actuator requests — the core's one point of authority."""
        ...
