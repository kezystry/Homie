"""Template tile — handlers. Implement the manifest's intents and event reactions.

Act through `ctx` (ctx.act / ctx.emit / ctx.speak); never reach into other tiles.
`learn` and `health` live in learn.py / health.py.
"""
from __future__ import annotations

from core.tile import Context, Event, Tile


class Template(Tile):
    async def on_event(self, event: Event, ctx: Context) -> None: ...
