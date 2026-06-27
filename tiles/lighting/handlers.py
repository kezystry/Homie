"""Lighting — presence-driven, after-dark room lighting.

On arrival it lights a room only when it's dark, the room allows auto-on, and
friction hasn't taught it otherwise — acting silently at AMBIENT priority so a
SECURITY decision always wins. The bedroom never auto-ons (the 3am regret); it is
reachable only through the explicit `light_room` request. When a room empties it
arms an auto-off and turns the light off once the vacancy outlasts the window.

Values are structured dicts (`{"state": "on"}`) so they round-trip through the HA
adapter's canonicalizer (core/canonical.py) and the echo is never mistaken for a
human reversal.
"""
from __future__ import annotations

from datetime import datetime

from core.tile import Context, Event, Tile

DARK_AFTER = 18  # local hour: auto-light only between dusk...
DARK_BEFORE = 7  # ...and dawn
OFF_WINDOW = 600.0  # seconds a room must stay empty before the light auto-offs
NEVER_AUTO_ON = {"bedroom"}  # request-only rooms (sleeping != wanting the light on)


def _hour(ts: float) -> int:
    return datetime.fromtimestamp(ts).hour


def _is_dark(ts: float) -> bool:
    h = _hour(ts)
    return h >= DARK_AFTER or h < DARK_BEFORE


class Lighting(Tile):
    async def on_event(self, event: Event, ctx: Context) -> None:
        if event.topic == "presence.arrived":
            await self._maybe_on(event, ctx)
        else:  # presence.departed / occupancy.changed
            await self._maybe_off(event, ctx)

    async def _maybe_on(self, event: Event, ctx: Context) -> None:
        room = event.payload.get("zone")
        if not room or f"light.{room}" not in ctx.manifest.actuators:
            return  # a security-only zone (e.g. approach) or an unlit room
        if room in NEVER_AUTO_ON:
            return  # request-only; light_room() is the only path on
        if not _is_dark(event.ts):
            return  # daylight — don't bother
        suppressed = self.state.get("suppressed", {}).get(room, [])
        if _hour(event.ts) in suppressed:
            return  # friction taught it not to auto-light this room at this hour
        await ctx.act(f"light.{room}", {"state": "on"})

    async def _maybe_off(self, event: Event, ctx: Context) -> None:
        room = event.payload.get("zone")
        if not room or f"light.{room}" not in ctx.manifest.actuators:
            return
        vacated = dict(self.state.get("vacated", {}))
        if event.payload.get("occupied", False):
            if vacated.pop(room, None) is not None:  # re-occupied: cancel pending auto-off
                await self.state.put("vacated", vacated)
            return
        since = vacated.get(room)
        if since is None:  # first sign of vacancy — arm the timer
            vacated[room] = event.ts
            await self.state.put("vacated", vacated)
        elif event.ts - since >= OFF_WINDOW:  # stayed empty long enough — turn it off
            vacated.pop(room, None)
            await self.state.put("vacated", vacated)
            await ctx.act(f"light.{room}", {"state": "off"})

    async def light_room(self, ctx: Context, room: str, on: bool) -> None:
        """Explicit request — bypasses the after-dark and request-only gates (this is
        the only way to light the bedroom). Still routed through ctx.act, so it is
        permission-checked and ledgered for friction attribution."""
        actuator = f"light.{room}"
        if actuator in ctx.manifest.actuators:
            await ctx.act(actuator, {"state": "on" if on else "off"})
