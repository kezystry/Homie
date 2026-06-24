"""Perceive — intake of structured events from the perception node.

Raw thermal/radar/camera inference runs at the edge (see perception/). This
module receives normalized events over the mesh and publishes them to the bus.
"""
from __future__ import annotations


class Perceive:
    async def run(self, bus) -> None: ...
