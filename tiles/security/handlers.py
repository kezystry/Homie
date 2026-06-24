"""Security — graduated escalation against the pattern of life.

It consults Behavioral Analysis (ctx.recall) for what is normal at this time and
zone. Presence that is novel or rare becomes an alert — capture -> alert -> your
decision (SECURITY.md). It never identifies a person; it only flags the unusual.
"""
from __future__ import annotations

from core.tile import Context, Event, Tile

RARE_RATE = 0.1  # events/day below which presence is "unusual" for this time+zone


class Security(Tile):
    async def on_event(self, event: Event, ctx: Context) -> None:
        zone = event.payload.get("zone")
        exp = await ctx.recall(event.topic, zone, event.ts)
        if exp.novel or exp.rate < RARE_RATE:
            await ctx.emit(
                Event(
                    topic="security.alert",
                    ts=event.ts,
                    payload={
                        "reason": "unexpected presence",
                        "topic": event.topic,
                        "zone": zone,
                        "novel": exp.novel,
                        "rate": exp.rate,
                    },
                )
            )
