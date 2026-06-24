"""The living-cell runtime: the contract every tile implements, and the
supervisor that keeps the colony alive.

The canonical tile boundary is the wire protocol (see PROTOCOL.md), not this
module's classes. The Supervisor drives every tile through a `TileChannel`:
`InProcessChannel` runs the protocol short-circuited in memory (the fast
default), `SubprocessChannel` speaks JSON over stdio to an isolated child (the
escape hatch). Core proper never imports a tile — the Supervisor's loader does,
into a task it can kill and quarantine.

Self-learning, self-healing, and self-dependence are provided here so individual
tiles never reimplement them. A tile declares its behaviour; the runtime
guarantees the rest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Protocol


# --------------------------------------------------------------------------- #
# Contract types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Manifest:
    """Parsed tile.toml — the six-clause contract: what a tile touches."""

    name: str
    summary: str
    subscribes: tuple[str, ...] = ()  # event patterns
    intents: tuple[str, ...] = ()  # voice phrases
    functions: tuple[str, ...] = ()  # LLM-callable
    actuators: tuple[str, ...] = ()  # what it may drive
    reads: tuple[str, ...] = ()  # data domains it may read
    network: str = "local"  # "local" | "egress:<host>"
    path: Path | None = None  # tiles/<name>/, set by the loader

    @property
    def needs_isolation(self) -> bool:
        """A tile runs out-of-process when it can reach the network or is
        otherwise declared unsafe — so `local`-only can be truly enforced."""
        return self.network != "local"


@dataclass(frozen=True)
class Event:
    topic: str  # dotted, e.g. "presence.arrived"
    ts: float
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ActionRef:
    """A stamp on every act a tile takes — the backbone of friction attribution."""

    action_id: str
    tile: str
    actuator: str
    value: object
    at: float


@dataclass(frozen=True)
class FrictionSignal:
    """A correction the runtime delivers to a tile's learn().

    Precedence when signals conflict: remark > reversal > repeat.
    """

    kind: Literal["reversal", "repeat", "remark"]
    at: float
    target_tile: str | None = None  # filled by attribution
    reverses: ActionRef | None = None
    text: str | None = None  # spoken remark
    count: int = 0  # repeats seen in window


# --------------------------------------------------------------------------- #
# Tile-author surface (the in-process binding of the wire protocol)
# --------------------------------------------------------------------------- #
class Context(Protocol):
    """Injected into a tile so it can act without importing other tiles.
    Permissions are enforced here — acting outside the manifest is refused."""

    async def act(self, actuator: str, value) -> None: ...
    async def emit(self, event: Event) -> None: ...
    async def speak(self, text: str) -> None: ...
    def log(self, level: str, msg: str) -> None: ...


class Tile:
    """Base for the reactive surface in handlers.py. `learn` and `health` are
    module-level functions in the tile folder, not methods here — so the runtime
    can deliver friction even if the reactive surface is quarantined."""

    manifest: Manifest

    async def on_event(self, event: Event, ctx: Context) -> None:
        """React to a subscribed event."""
        ...


# --------------------------------------------------------------------------- #
# Channels — the one protocol, two transports
# --------------------------------------------------------------------------- #
class TileChannel(Protocol):
    """How the Supervisor speaks to a tile. Same protocol whether the tile runs
    in-process or as an isolated subprocess (PROTOCOL.md)."""

    async def start(self) -> None: ...
    async def stop(self, *, grace: float = 5.0) -> None: ...
    async def send_event(self, event: Event) -> None: ...
    async def deliver_friction(self, signal: FrictionSignal) -> None: ...
    async def call(self, fn: str, **args) -> object: ...
    async def check_health(self) -> bool: ...


class InProcessChannel:
    """Default. Loads the tile into a killable task and drives the protocol in
    memory. The loader is the only thing that imports tile code."""

    def __init__(self, manifest: Manifest, ctx: Context) -> None:
        self.manifest = manifest
        self.ctx = ctx

    async def start(self) -> None: ...
    async def stop(self, *, grace: float = 5.0) -> None: ...
    async def send_event(self, event: Event) -> None: ...
    async def deliver_friction(self, signal: FrictionSignal) -> None: ...
    async def call(self, fn: str, **args) -> object: ...
    async def check_health(self) -> bool: ...


class SubprocessChannel:
    """Escape hatch. Spawns the tile as a child and speaks line-delimited JSON
    over stdio, inside a network namespace that enforces the manifest's network
    policy. Used when `manifest.needs_isolation`."""

    def __init__(self, manifest: Manifest, ctx: Context) -> None:
        self.manifest = manifest
        self.ctx = ctx

    async def start(self) -> None: ...
    async def stop(self, *, grace: float = 5.0) -> None: ...
    async def send_event(self, event: Event) -> None: ...
    async def deliver_friction(self, signal: FrictionSignal) -> None: ...
    async def call(self, fn: str, **args) -> object: ...
    async def check_health(self) -> bool: ...


def channel_for(manifest: Manifest, ctx: Context) -> TileChannel:
    """Pick the transport from the manifest — the single isolation switch."""
    if manifest.needs_isolation:
        return SubprocessChannel(manifest, ctx)
    return InProcessChannel(manifest, ctx)


# --------------------------------------------------------------------------- #
# Supervision
# --------------------------------------------------------------------------- #
@dataclass
class SupervisionPolicy:
    event_timeout: float = 5.0
    learn_timeout: float = 30.0
    health_timeout: float = 2.0
    health_interval: float = 30.0
    backoff_base: float = 1.0
    backoff_cap: float = 60.0
    stability_reset: float = 60.0
    quarantine_after: int = 5  # restarts...
    quarantine_window: float = 600.0  # ...within this many seconds


@dataclass(frozen=True)
class InvalidManifest:
    """A manifest that failed validation — a value, never an exception, so one
    bad tile never aborts discovery of the rest."""

    name: str
    path: Path
    errors: tuple[str, ...]


class Supervisor:
    """Discovers tiles, runs each through a TileChannel, restarts on fault, and
    routes events and friction. Builds its routing tables from manifests alone;
    only the channel loader ever touches tile code.
    """

    def __init__(self, tiles_dir: Path, bus, policy: SupervisionPolicy | None = None) -> None:
        self.tiles_dir = tiles_dir
        self.bus = bus
        self.policy = policy or SupervisionPolicy()

    # discovery — manifests only, no tile code
    def discover(self) -> list[Manifest | InvalidManifest]:
        """Read every tiles/<name>/tile.toml. Skips _template and dotfiles."""
        ...

    # lifecycle
    async def start(self, name: str) -> None: ...
    async def stop(self, name: str, *, grace: float = 5.0) -> None: ...
    async def reload(self, name: str) -> None: ...

    async def run(self) -> None:
        """Start the colony, watch tiles/, supervise health, restart the fallen."""
        ...

    # routing (resolved from manifests to live channels)
    async def dispatch_event(self, event: Event) -> None: ...
    async def call_function(self, fn: str, **args) -> object: ...
    async def deliver_friction(self, signal: FrictionSignal) -> None:
        """Attribute the signal to a tile (via the action ledger) and deliver it
        to that tile's learn(). Queued to state/inbox/ if the tile is quarantined."""
        ...
