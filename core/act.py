"""Act — the single Home Assistant gateway.

The one place the system touches the physical home. Tiles declare actuators in
their manifest; only declared actuators may be driven, and the bus arbitrates conflicts.
"""
from __future__ import annotations


class Act:
    async def drive(self, actuator: str, command) -> None: ...
