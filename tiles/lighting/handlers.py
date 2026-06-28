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

import os
from datetime import datetime

from core.tile import Context, Event, Tile

DARK_AFTER = 18  # fallback local hour: auto-light only between dusk...
DARK_BEFORE = 7  # ...and dawn (used only when no HOMIE_LAT/HOMIE_LON is configured)
OFF_WINDOW = 600.0  # seconds a room must stay empty before the light auto-offs
NEVER_AUTO_ON = {"bedroom"}  # request-only rooms (sleeping != wanting the light on)
MAX_OFFERS = 2  # offer-once-then-auto: ask at most this many times before settling on "no"
FILM_ROOM = "living"   # the room to dim for a film (override with HOMIE_FILM_ROOM)
FILM_DIM_PCT = 15      # how low to take the lights for a film

# Zone -> actuator alias. Presence zones are short ("living"), but the home's actuator (and
# the act-map) is "light.living_room" (C14). Decoupling here keeps zone names untouched
# while the manifest/act-map agree on one actuator name. Unlisted zones map 1:1.
ROOM_ACTUATOR = {"living": "light.living_room"}


def _actuator(room: str) -> str:
    return ROOM_ACTUATOR.get(room, f"light.{room}")


def _hour(ts: float) -> int:
    return datetime.fromtimestamp(ts).hour


def _location() -> tuple[float, float] | None:
    """The home's (lat, lon) from HOMIE_LAT/HOMIE_LON, or None if unset/unparseable."""
    lat, lon = os.environ.get("HOMIE_LAT"), os.environ.get("HOMIE_LON")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except ValueError:
        return None


def _is_dark(ts: float) -> bool:
    """Is it dark enough to want lights at `ts`? Uses real solar civil dusk when the
    home's location is configured (HOMIE_LAT/HOMIE_LON) — correct at any latitude —
    and falls back to the fixed 18:00–07:00 window otherwise (second-review N4)."""
    loc = _location()
    if loc is None:
        h = _hour(ts)
        return h >= DARK_AFTER or h < DARK_BEFORE
    from core.sun import is_dark as solar_is_dark
    return solar_is_dark(ts, loc[0], loc[1])


def _off_key(room: str) -> str:
    return f"lighting.off.{room}"


class Lighting(Tile):
    async def on_event(self, event: Event, ctx: Context) -> None:
        if event.topic == "presence.arrived":
            await self._maybe_on(event, ctx)
        elif event.topic == "timer.fired":
            await self._on_off_timer(event, ctx)
        elif event.topic == "media.activity":
            await self._on_media(event, ctx)
        else:  # presence.departed / occupancy.changed
            await self._maybe_off(event, ctx)

    # -- film lighting: dim when a film starts, restore when it stops ---------- #
    async def _on_media(self, event: Event, ctx: Context) -> None:
        """When a film starts after dark, dim the film room (offer-once-then-auto, the owner's
        pattern); restore the light when it stops. Reuses the lighting tile so lights stay
        owned here, at AMBIENT priority — a security/safety decision always wins."""
        room = os.environ.get("HOMIE_FILM_ROOM", FILM_ROOM)
        if _actuator(room) not in ctx.manifest.actuators:
            return
        state, kind = event.payload.get("state"), event.payload.get("kind")
        if state == "playing" and kind == "film":
            if not _is_dark(event.ts) or self.state.get("film_dimmed"):
                return  # daylight, or already dimmed for this film
            if await self._offer_once(ctx, ok_key="film_ok", offers_key="film_offers",
                                      prompt=f"Dim the {room} lights for the film?"):
                await ctx.act(_actuator(room), {"state": "on", "brightness_pct": FILM_DIM_PCT})
                await self.state.put("film_dimmed", True)
        elif state == "stopped" and self.state.get("film_dimmed"):
            await ctx.act(_actuator(room), {"state": "on"})   # film over → lights back up
            await self.state.put("film_dimmed", False)

    async def _offer_once(self, ctx: Context, *, ok_key: str, offers_key: str, prompt: str) -> bool:
        """Generic offer-once-then-auto: True to proceed (a learned yes, or no ask-channel),
        False if declined. A settled no sticks; a missed answer re-offers up to MAX_OFFERS so a
        single timeout never disables it forever."""
        decision = self.state.get(ok_key)
        if decision is False:
            return False
        if decision is True or not ctx.can_confirm:
            return True
        if await ctx.confirm(prompt):
            await self.state.put(ok_key, True)
            return True
        offers = int(self.state.get(offers_key, 0)) + 1
        await self.state.put(offers_key, offers)
        if offers >= MAX_OFFERS:
            await self.state.put(ok_key, False)
        return False

    def _armed(self) -> set:
        # ephemeral per-instance set of rooms with a pending auto-off timer. NOT
        # persisted: a restart cancels the Clock's pending timers, and the next
        # vacancy event simply re-arms — so a stale "armed" flag can never strand a
        # light on.
        if not hasattr(self, "_arming"):
            self._arming: set = set()
        return self._arming

    async def _maybe_on(self, event: Event, ctx: Context) -> None:
        room = event.payload.get("zone")
        if not room or _actuator(room) not in ctx.manifest.actuators:
            return  # a security-only zone (e.g. approach) or an unlit room
        if room in NEVER_AUTO_ON:
            return  # request-only; light_room() is the only path on
        if not _is_dark(event.ts):
            return  # daylight — don't bother
        suppressed = self.state.get("suppressed", {}).get(room, [])
        if _hour(event.ts) in suppressed:
            return  # friction taught it not to auto-light this room at this hour
        await self._offer_or_auto(event, ctx, room)

    async def _offer_or_auto(self, event: Event, ctx: Context, room: str) -> None:
        """Offer-once-then-auto (the owner's call): the FIRST few dusks Homie ASKS before
        lighting a room; once you say yes it's automatic forever after; a settled no is
        respected. Where no ask-channel is wired (no Consent), it falls back to acting — it
        can't offer what it can't ask."""
        decision = self.state.get("auto_ok", {}).get(room)
        if decision is False:
            return                                   # settled: you don't want dusk light here
        if decision is True or not ctx.can_confirm:
            await ctx.act(_actuator(room), {"state": "on"})   # learned yes (or no way to ask)
            return
        # Never settled and we CAN ask → offer once.
        yes = await ctx.confirm(f"Light the {room}? I'll do it automatically from now on.")
        auto_ok = dict(self.state.get("auto_ok", {}))
        if yes:
            auto_ok[room] = True
            await self.state.put("auto_ok", auto_ok)
            await ctx.act(_actuator(room), {"state": "on"})
            return
        # No / no answer: count it. Settle to a firm "no" only after MAX_OFFERS, so a single
        # missed offer never permanently disables dusk lighting for the room.
        offers = dict(self.state.get("offers", {}))
        offers[room] = offers.get(room, 0) + 1
        await self.state.put("offers", offers)
        if offers[room] >= MAX_OFFERS:
            auto_ok[room] = False
            await self.state.put("auto_ok", auto_ok)

    async def _maybe_off(self, event: Event, ctx: Context) -> None:
        room = event.payload.get("zone")
        if not room or _actuator(room) not in ctx.manifest.actuators:
            return
        armed = self._armed()
        if event.payload.get("occupied", False):
            if room in armed:  # re-occupied: cancel the pending auto-off
                armed.discard(room)
                await ctx.emit(Event("timer.cancel", event.ts, {"key": _off_key(room)}))
            return
        # Vacancy: arm a real timer so the light turns off even if the room then goes
        # completely silent (no further events) — the N1 fix. Arm once per vacancy.
        if room not in armed:
            armed.add(room)
            await ctx.emit(Event("timer.set", event.ts,
                                 {"after": OFF_WINDOW, "key": _off_key(room), "data": {"room": room}}))

    async def _on_off_timer(self, event: Event, ctx: Context) -> None:
        data = event.payload.get("data") or {}
        room = data.get("room")
        if not room or event.payload.get("key") != _off_key(room):
            return  # not our auto-off timer
        self._armed().discard(room)
        if _actuator(room) in ctx.manifest.actuators:  # still ours to control
            await ctx.act(_actuator(room), {"state": "off"})

    async def light_room(self, ctx: Context, room: str, on: bool) -> None:
        """Explicit request — bypasses the after-dark and request-only gates (this is
        the only way to light the bedroom). Still routed through ctx.act, so it is
        permission-checked and ledgered for friction attribution."""
        actuator = _actuator(room)
        if actuator in ctx.manifest.actuators:
            await ctx.act(actuator, {"state": "on" if on else "off"})
