"""Desktop — the hands on the main PC. Each function drives ONE safe media actuator through
`ctx.act` (the capability gate), which routes to the DesktopExecutor's fixed verb table. The
tile never execs anything itself — it can only ask for one of its manifest-declared actuators.
"""
from __future__ import annotations

from core.tile import Context, Event, Tile


class Desktop(Tile):
    async def on_event(self, event: Event, ctx: Context) -> None:
        return  # control is function-driven; auto-behaviors (dim on film-start) land later

    async def play_pause(self, ctx: Context) -> None:
        await ctx.act("desktop.play_pause", {})

    async def next_(self, ctx: Context) -> None:
        await ctx.act("desktop.next", {})

    async def previous(self, ctx: Context) -> None:
        await ctx.act("desktop.prev", {})

    async def skip_forward(self, ctx: Context) -> None:
        await ctx.act("desktop.seek_fwd", {})

    async def skip_back(self, ctx: Context) -> None:
        await ctx.act("desktop.seek_back", {})
