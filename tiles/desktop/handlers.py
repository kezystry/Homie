"""Desktop — the hands on the main PC. Each function drives ONE safe media actuator through
`ctx.act` (the capability gate), which routes to the DesktopExecutor's fixed verb table. The
tile never execs anything itself — it can only ask for one of its manifest-declared actuators.
"""
from __future__ import annotations

from core.tile import Context, Event, Tile

# Verbs the owner can drive from chat (/commands) via a desktop.control event → ONE safe actuator.
_CONTROL = {
    "play_pause": "desktop.play_pause", "play": "desktop.play_pause", "pause": "desktop.play_pause",
    "next": "desktop.next", "prev": "desktop.prev",
    "seek_fwd": "desktop.seek_fwd", "seek_back": "desktop.seek_back",
    "stop": "desktop.stop", "close": "desktop.close",
}


class Desktop(Tile):
    async def on_event(self, event: Event, ctx: Context) -> None:
        # Owner-typed /commands (e.g. /close) arrive as desktop.control and drive ONE safe
        # actuator through the capability gate — never a free exec.
        if event.topic != "desktop.control":
            return
        p = event.payload or {}
        actuator = _CONTROL.get(str(p.get("verb", "")).lower())
        if actuator is None:
            return
        value = {"target": p["target"]} if actuator == "desktop.close" and p.get("target") else {}
        await ctx.act(actuator, value)

    async def play_pause(self, ctx: Context) -> None:
        await ctx.act("desktop.play_pause", {})

    async def close(self, ctx: Context, app: str | None = None) -> None:
        await ctx.act("desktop.close", {"target": app} if app else {})

    async def next_(self, ctx: Context) -> None:
        await ctx.act("desktop.next", {})

    async def previous(self, ctx: Context) -> None:
        await ctx.act("desktop.prev", {})

    async def skip_forward(self, ctx: Context) -> None:
        await ctx.act("desktop.seek_fwd", {})

    async def skip_back(self, ctx: Context) -> None:
        await ctx.act("desktop.seek_back", {})
