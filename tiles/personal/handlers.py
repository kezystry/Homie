"""Personal Assistant — the reference tile. Calendar, reminders, tasks.

Proves the contract: it subscribes to presence and time, provides voice intents
and LLM functions, drives no actuators, and stays local-only.
"""
from __future__ import annotations

from core.tile import Tile


class Personal(Tile):
    async def on_event(self, event) -> None:
        # e.g. on time.morning + presence.arrived -> offer the day's agenda
        ...

    async def agenda(self): ...

    async def add_reminder(self, text: str, when) -> None: ...

    async def add_task(self, text: str) -> None: ...
