"""Personal Assistant — the morning surface (recap + day briefing) and the day's tasks.

On `time.morning` (fired once a day by the clock) this assembles the one Agenda from what
Homie already has — its learned routines (`ctx.beliefs`) plus the owner's reminders/tasks —
folds it through the capped `core/briefing` render, SPEAKS exactly one budgeted line through
the VoiceGate (`ctx.speak`, kind="proactive"), and emits the full page on `briefing.ready`
for the screen/phone. HA calendar/weather and place-anchored errands enrich the same Agenda
as those sources wire in; the shape never changes.

It still provides the voice/LLM functions (agenda / add_reminder / add_task) and stays
local-only, driving no actuators.
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from core import agenda
from core import briefing as briefing_mod
from core import recap as recap_mod
from core.tile import Context, Event, Tile

BRIEFING_READY = "briefing.ready"


def _tz():
    name = os.environ.get("HOMIE_TZ")
    return ZoneInfo(name) if name else None


def _local_day_start(now: float, tz) -> float:
    dt = datetime.fromtimestamp(now, tz) if tz else datetime.fromtimestamp(now)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class Personal(Tile):
    async def on_event(self, event: Event, ctx: Context) -> None:
        if event.topic == "time.morning":
            await self._morning(event, ctx)
        elif event.topic == "agenda.external":
            # The live HA calendar/to-do/weather snapshot (core/ha_agenda.py). Cache it; the
            # morning render folds the freshest one — the tile never blocks on the network.
            await self.state.put("external", {
                "events": event.payload.get("events", []),
                "todos": event.payload.get("todos", []),
                "weather": event.payload.get("weather"),
            })
        elif event.topic == "presence.arrived":
            # Legacy welcome-offer kept light; the rich note is the morning briefing, not this.
            if self.state.get("suppress_agenda"):
                return
            items = await self._agenda_items(ctx)
            if items:
                await ctx.speak("Today: " + "; ".join(items))

    async def _morning(self, event: Event, ctx: Context) -> None:
        now = event.ts
        tz = _tz()
        day_start = _local_day_start(now, tz)

        # The Agenda, folded from what Homie already has: learned routines + the owner's list +
        # the live HA snapshot (real calendar events, to-dos, weather) cached from agenda.external.
        rows = await ctx.beliefs(now)
        items = agenda.from_beliefs(rows, day_start=day_start)
        for text in list(self.state.get("reminders", [])) + list(self.state.get("tasks", [])):
            items.append(agenda.AgendaItem(
                kind=agenda.DUE, when=agenda.Temporal.floating(), title=str(text),
                source="personal", source_id=str(text)))
        external = self.state.get("external", {}) or {}
        items += agenda.from_ha_calendar([e for e in external.get("events", []) if e.get("start")])
        items += agenda.from_ha_todo(external.get("todos", []))
        weather = agenda.weather_clause(external.get("weather"))

        view = agenda.AgendaView(items, tz=os.environ.get("HOMIE_TZ"))
        recap_line = self._recap_line(now, tz)
        brief = briefing_mod.build(view, now, weather=weather, tz=tz, recap_line=recap_line)

        # ONE budgeted proactive line through the VoiceGate — built from a REDACTED brief so a
        # sensitive item is never spoken aloud or pushed; the full page (below) keeps every title
        # on YOUR local screen.
        spoken = briefing_mod.build(view, now, weather=weather, tz=tz,
                                    recap_line=recap_line, redact=True)
        line = spoken.speak_line()
        if line:
            await ctx.speak(line, kind="proactive")
        await ctx.emit(Event(BRIEFING_READY, now,
                             {"text": brief.render_text(), "lines": brief.render_lines()},
                             source="tile:personal"))

    def _recap_line(self, now: float, tz) -> str:
        """Yesterday's one-line recap. A richer nightly fold may pre-compose `recap_line`
        (presence windows, corrections, the quiet-held count); until then we render an honest
        weekday-led line so the backward half of the surface is always present."""
        pre = self.state.get("recap_line")
        if pre:
            return pre
        yesterday = datetime.fromtimestamp(now - 86400, tz) if tz else datetime.fromtimestamp(now - 86400)
        return recap_mod.compose(recap_mod.RecapFacts(weekday=yesterday.strftime("%A")))

    # -- voice / LLM functions (unchanged contract) --------------------------- #
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
