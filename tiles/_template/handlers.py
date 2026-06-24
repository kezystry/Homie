"""Template tile — handlers. Implement the manifest's intents and event reactions."""
from __future__ import annotations

from core.tile import Tile


class Template(Tile):
    async def on_event(self, event) -> None: ...
