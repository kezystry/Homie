"""Personal Assistant — the reference tile. Calendar, reminders, tasks.

Proves the contract: it subscribes to presence and time, provides voice intents
and LLM functions, drives no actuators, and stays local-only. When you arrive in
the morning it offers the day's agenda — unless friction has taught it not to.
"""
from __future__ import annotations

from core.tile import Context, Event, Tile


class Personal(Tile):
    async def on_event(self, event: Event, ctx: Context) -> None:
        if self.state.get("suppress_agenda"):
            return  # friction taught it to stop offering unprompted
        items = await self._agenda_items(ctx)
        if items:
            await ctx.speak("Today: " + "; ".join(items))

    async def agenda(self, ctx: Context) -> list[str]:
        return await self._agenda_items(ctx)

    async def add_reminder(self, ctx: Context, text: str) -> None:
        await self._append(ctx, "reminders", text)

    async def add_task(self, ctx: Context, text: str) -> None:
        await self._append(ctx, "tasks", text)

    async def _agenda_items(self, ctx: Context) -> list[str]:
        return list(self.state.get("reminders", [])) + list(self.state.get("tasks", []))

    async def _append(self, ctx: Context, key: str, text: str) -> None:
        items = list(self.state.get(key, []))
        items.append(text)
        await self.state.put(key, items)
