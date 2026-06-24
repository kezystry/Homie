"""The living-cell runtime: the contract every tile implements, and the
supervisor that keeps the colony alive.

Self-learning, self-healing, and self-dependence are provided here so individual
tiles never reimplement them. A tile declares its behaviour; the runtime
guarantees the rest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Manifest:
    """Parsed tile.toml — the six-clause contract: what a tile touches."""

    name: str
    summary: str
    subscribes: list[str] = field(default_factory=list)  # events/patterns
    intents: list[str] = field(default_factory=list)  # voice phrases
    functions: list[str] = field(default_factory=list)  # LLM-callable
    actuators: list[str] = field(default_factory=list)  # what it may drive
    network: str = "local"  # local | egress:<host>


class Tile:
    """Base class for a tile. Subclasses implement reactions, learning, and
    health; the Supervisor provides isolation, restart, and friction delivery.
    """

    manifest: Manifest

    async def on_event(self, event) -> None:
        """React to a subscribed event."""
        ...

    async def learn(self, friction) -> None:
        """Adapt from a friction signal (reversal, repeat, or remark).

        Self-learning: the tile refines itself; the core only delivers the signal.
        """
        ...

    async def health(self) -> bool:
        """Report fitness. The Supervisor restarts or quarantines on failure.

        Self-healing: a sick cell isolates itself; the colony lives on.
        """
        return True


class Supervisor:
    """Discovers tiles, runs each in isolation, restarts on fault, and routes
    events and friction. The core never imports a tile — it loads manifests.
    """

    def __init__(self, tiles_dir: Path) -> None:
        self.tiles_dir = tiles_dir

    def discover(self) -> list[Manifest]:
        """Read every tiles/<name>/tile.toml. No tile code is imported to route."""
        ...

    async def run(self) -> None:
        """Start the colony, supervise health, and restart the fallen."""
        ...
