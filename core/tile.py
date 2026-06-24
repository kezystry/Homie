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

import asyncio
import importlib.util
import json
import logging
import re
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Protocol
from uuid import uuid4

log = logging.getLogger("homie.tile")


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
    source: str | None = None  # publisher: "perception", "tile:kitchen", ...
    id: str | None = None  # dedup key (mesh fan-in)
    origin: str | None = None  # node where first published
    ttl: float | None = None  # mesh hops remaining; None/0 = node-local


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


@dataclass(frozen=True)
class InvalidManifest:
    """A manifest that failed validation — a value, never an exception, so one
    bad tile never aborts discovery of the rest."""

    name: str
    path: Path
    errors: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Tile-author surface (the in-process binding of the wire protocol)
# --------------------------------------------------------------------------- #
class Context(Protocol):
    """Injected into a tile so it can act without importing other tiles.
    Permissions are enforced here — acting outside the manifest is refused."""

    async def act(self, actuator: str, value) -> None: ...
    async def emit(self, event: Event) -> None: ...
    async def speak(self, text: str) -> None: ...
    async def recall(self, topic: str, zone: str | None, when: float): ...  # Behavioral Analysis
    def log(self, level: str, msg: str) -> None: ...


class Tile:
    """Base for the reactive surface in handlers.py. `learn` and `health` are
    module-level functions in the tile folder, not methods here — so the runtime
    can deliver friction even if the reactive surface is quarantined."""

    manifest: Manifest
    state: "TileState"  # the tile's own writable surface, set by the channel

    async def on_event(self, event: Event, ctx: Context) -> None:
        """React to a subscribed event."""
        ...


class TileState:
    """A tile's own writable surface — its self-dependence. Backed by
    tiles/<name>/state/. No tile may read another's."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._data_file = self.path / "data.json"
        self._data: dict = (
            json.loads(self._data_file.read_text("utf-8")) if self._data_file.exists() else {}
        )

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    async def put(self, key: str, value) -> None:
        self._data[key] = value
        self._data_file.write_text(json.dumps(self._data), "utf-8")

    def config(self) -> dict:
        f = self.path / "config.toml"
        return tomllib.loads(f.read_text("utf-8")) if f.exists() else {}

    def secret(self, key: str) -> str | None:
        return None  # secrets.env handling lands with the subprocess channel


class TileContext:
    """Concrete Context. Enforces the manifest's actuator permissions, then
    forwards to runtime-provided sinks (so it stays decoupled and testable)."""

    def __init__(self, manifest: Manifest, *, emit, act, speak, log_fn, recall=None) -> None:
        self.manifest = manifest
        self._emit = emit
        self._act = act
        self._speak = speak
        self._log = log_fn
        self._recall = recall

    async def act(self, actuator: str, value) -> None:
        if actuator not in self.manifest.actuators:
            self._log("warning", f"{self.manifest.name}: act on undeclared '{actuator}' refused")
            raise PermissionError(actuator)
        await self._act(actuator, value)

    async def emit(self, event: Event) -> None:
        await self._emit(event)

    async def speak(self, text: str) -> None:
        await self._speak(text)

    async def recall(self, topic: str, zone: str | None, when: float):
        """Query the pattern of life (Behavioral Analysis) — what is normal here?"""
        if self._recall is None:
            raise RuntimeError("recall unavailable (no Remember wired into the Supervisor)")
        return await self._recall(topic, zone, when)

    def log(self, level: str, msg: str) -> None:
        self._log(level, msg)


# --------------------------------------------------------------------------- #
# Manifest loading & tile loading
# --------------------------------------------------------------------------- #
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_PATTERN = re.compile(r"^[a-z0-9_*]+(\.[a-z0-9_*]+)*$")
_EGRESS = re.compile(r"^egress:[a-z0-9.\-]+$")


def load_manifest(toml_path: Path) -> Manifest | InvalidManifest:
    """Parse tile.toml into a Manifest, or an InvalidManifest value listing why."""
    toml_path = Path(toml_path)
    folder = toml_path.parent
    folder_name = folder.name
    if not toml_path.exists():
        return InvalidManifest(folder_name, folder, ("missing tile.toml",))
    try:
        raw = tomllib.loads(toml_path.read_text("utf-8"))
    except Exception as e:  # malformed TOML
        return InvalidManifest(folder_name, folder, (f"invalid TOML: {e}",))

    tile = raw.get("tile", {})
    name = tile.get("name", "")
    summary = tile.get("summary", "")
    subscribes = tuple(raw.get("subscribes", {}).get("events", []))
    intents = tuple(raw.get("provides", {}).get("intents", []))
    functions = tuple(raw.get("provides", {}).get("functions", []))
    actuators = tuple(raw.get("acts", {}).get("actuators", []))
    perms = raw.get("permissions", {})
    reads = tuple(perms.get("reads", []))
    network = perms.get("network", "local")

    errors: list[str] = []
    if not _NAME.match(name):
        errors.append(f"invalid name '{name}'")
    elif name != folder_name:
        errors.append(f"name '{name}' != folder '{folder_name}'")
    if not summary:
        errors.append("missing summary")
    if network != "local" and not _EGRESS.match(network):
        errors.append(f"invalid network '{network}'")
    for p in subscribes:
        if not _PATTERN.match(p):
            errors.append(f"invalid subscribe pattern '{p}'")
    if len(set(functions)) != len(functions):
        errors.append("duplicate functions")
    if len(set(intents)) != len(intents):
        errors.append("duplicate intents")
    if errors:
        return InvalidManifest(folder_name, folder, tuple(errors))

    return Manifest(
        name=name,
        summary=summary,
        subscribes=subscribes,
        intents=intents,
        functions=functions,
        actuators=actuators,
        reads=reads,
        network=network,
        path=folder,
    )


def _load_module(path: Path, modname: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_tile(manifest: Manifest):
    """Import a tile's code from its folder — the ONLY place tile code is loaded.
    Returns (Tile subclass, learn callable | None, health callable | None)."""
    folder = manifest.path
    handlers = _load_module(folder / "handlers.py", f"homie_tile_{manifest.name}_handlers")
    tile_cls = next(
        obj
        for obj in vars(handlers).values()
        if isinstance(obj, type)
        and issubclass(obj, Tile)
        and obj is not Tile
        and obj.__module__ == handlers.__name__
    )
    learn_fn = None
    health_fn = None
    if (folder / "learn.py").exists():
        learn_fn = getattr(_load_module(folder / "learn.py", f"homie_tile_{manifest.name}_learn"), "learn", None)
    if (folder / "health.py").exists():
        health_fn = getattr(_load_module(folder / "health.py", f"homie_tile_{manifest.name}_health"), "health", None)
    return tile_cls, learn_fn, health_fn


# --------------------------------------------------------------------------- #
# Channels — the one protocol, two transports
# --------------------------------------------------------------------------- #
class TileChannel(Protocol):
    async def start(self) -> None: ...
    async def stop(self, *, grace: float = 5.0) -> None: ...
    async def send_event(self, event: Event) -> None: ...
    async def deliver_friction(self, signal: FrictionSignal) -> None: ...
    async def call(self, fn: str, **args) -> object: ...
    async def check_health(self) -> bool: ...


class InProcessChannel:
    """Default. Loads the tile into the Supervisor's process and drives the
    protocol in memory. Restart = reload the module + reinstantiate."""

    def __init__(self, manifest: Manifest, ctx: Context) -> None:
        self.manifest = manifest
        self.ctx = ctx
        self._tile: Tile | None = None
        self._learn: Callable | None = None
        self._health: Callable | None = None
        self._state: TileState | None = None

    async def start(self) -> None:
        tile_cls, learn_fn, health_fn = load_tile(self.manifest)
        self._state = TileState(self.manifest.path / "state")
        tile = tile_cls()
        tile.manifest = self.manifest
        tile.state = self._state
        self._tile = tile
        self._learn = learn_fn
        self._health = health_fn

    async def stop(self, *, grace: float = 5.0) -> None:
        self._tile = None

    async def send_event(self, event: Event) -> None:
        await self._tile.on_event(event, self.ctx)

    async def deliver_friction(self, signal: FrictionSignal) -> None:
        if self._learn:
            await self._learn(self._state, signal)

    async def call(self, fn: str, **args) -> object:
        return await getattr(self._tile, fn)(self.ctx, **args)

    async def check_health(self) -> bool:
        if self._health:
            return bool(await self._health(self._state))
        return True


class SubprocessChannel:
    """Escape hatch (not yet implemented). Speaks line-delimited JSON over stdio
    to a child in a network namespace that enforces the manifest's network policy."""

    def __init__(self, manifest: Manifest, ctx: Context) -> None:
        self.manifest = manifest
        self.ctx = ctx

    async def start(self) -> None:
        raise NotImplementedError("SubprocessChannel is the isolation escape hatch — not built yet")

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
    quarantine_after: int = 5  # faults...
    quarantine_window: float = 600.0  # ...within this many seconds
    reversal_window: float = 600.0  # how long an act stays attributable to a correction


@dataclass
class TileRecord:
    name: str
    manifest: Manifest | None
    channel: TileChannel | None
    ctx: Context | None
    state: str  # READY | QUARANTINED | INVALID
    faults: int = 0
    fault_times: list[float] = field(default_factory=list)
    subs: list = field(default_factory=list)
    invalid: InvalidManifest | None = None


class Supervisor:
    """Discovers tiles, runs each through a TileChannel, restarts on fault, and
    routes events and friction. Routing is built from manifests; only the channel
    loader ever touches tile code."""

    def __init__(self, tiles_dir: Path, bus, policy: SupervisionPolicy | None = None, *, remember=None) -> None:
        self.tiles_dir = Path(tiles_dir)
        self.bus = bus
        self.policy = policy or SupervisionPolicy()
        self.remember = remember  # Behavioral Analysis, exposed to tiles via ctx.recall
        self._tiles: dict[str, TileRecord] = {}
        self._ledger: list[ActionRef] = []  # recent acts, for friction attribution
        self._manual: dict[str, int] = {}  # manual-action counts, for repeat detection

    # discovery — manifests only, no tile code
    def discover(self) -> list[Manifest | InvalidManifest]:
        out: list[Manifest | InvalidManifest] = []
        for child in sorted(self.tiles_dir.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            out.append(load_manifest(child / "tile.toml"))
        return out

    async def start_all(self) -> None:
        for m in self.discover():
            if isinstance(m, Manifest):
                await self.start(m.name)
            else:
                log.warning("tile %s invalid: %s", m.name, "; ".join(m.errors))
                self._tiles[m.name] = TileRecord(m.name, None, None, None, "INVALID", invalid=m)

    # lifecycle
    async def start(self, name: str) -> None:
        manifest = load_manifest(self.tiles_dir / name / "tile.toml")
        if isinstance(manifest, InvalidManifest):
            self._tiles[name] = TileRecord(name, None, None, None, "INVALID", invalid=manifest)
            log.warning("tile %s invalid: %s", name, "; ".join(manifest.errors))
            return
        ctx = self._make_ctx(manifest)
        channel = channel_for(manifest, ctx)
        await channel.start()
        rec = TileRecord(name, manifest, channel, ctx, "READY")
        self._tiles[name] = rec
        for pattern in manifest.subscribes:
            rec.subs.append(self.bus.subscribe(pattern, self._make_handler(name), owner=f"tile:{name}"))

    async def stop(self, name: str, *, grace: float = 5.0) -> None:
        rec = self._tiles.get(name)
        if not rec:
            return
        self.bus.drop_owner(f"tile:{name}")
        rec.subs.clear()
        if rec.channel:
            await rec.channel.stop(grace=grace)

    async def reload(self, name: str) -> None:
        await self.stop(name)
        await self.start(name)

    # routing
    def _make_handler(self, name: str):
        async def handler(event: Event) -> None:
            await self._dispatch(name, event)

        return handler

    async def _dispatch(self, name: str, event: Event) -> None:
        rec = self._tiles.get(name)
        if not rec or rec.state != "READY":
            return
        try:
            await asyncio.wait_for(rec.channel.send_event(event), timeout=self.policy.event_timeout)
        except Exception:
            await self._on_fault(name)

    async def call_function(self, fn: str, **args) -> object:
        for rec in self._tiles.values():
            if rec.state == "READY" and rec.manifest and fn in rec.manifest.functions:
                return await asyncio.wait_for(rec.channel.call(fn, **args), timeout=self.policy.event_timeout)
        raise KeyError(f"no ready tile provides function '{fn}'")

    async def deliver_friction(self, signal: FrictionSignal) -> None:
        rec = self._tiles.get(signal.target_tile) if signal.target_tile else None
        if rec and rec.state == "READY":
            try:
                await asyncio.wait_for(rec.channel.deliver_friction(signal), timeout=self.policy.learn_timeout)
            except Exception:
                await self._on_fault(rec.name)

    # friction attribution — turn a reaction into a learning signal for one tile
    async def note_reversal(self, actuator: str, value, at: float) -> FrictionSignal | None:
        """A human undid an actuator. Attribute it to the tile whose recent act
        on that actuator is being reversed, and deliver the correction."""
        recent = [r for r in self._ledger if r.actuator == actuator and at - r.at <= self.policy.reversal_window]
        if not recent:
            return None
        ref = max(recent, key=lambda r: r.at)
        if ref.value == value:  # same state — not a reversal
            return None
        signal = FrictionSignal(kind="reversal", at=at, target_tile=ref.tile, reverses=ref)
        await self.deliver_friction(signal)
        return signal

    async def note_remark(self, text: str, at: float) -> FrictionSignal | None:
        """A spoken correction — strongest signal. Attribute to the most recent
        acting tile within the window."""
        recent = [r for r in self._ledger if at - r.at <= self.policy.reversal_window]
        if not recent:
            return None
        target = max(recent, key=lambda r: r.at).tile
        signal = FrictionSignal(kind="remark", at=at, target_tile=target, text=text)
        await self.deliver_friction(signal)
        return signal

    async def note_manual(self, actuator: str, at: float, *, threshold: int = 3) -> FrictionSignal | None:
        """A human keeps doing something by hand. After `threshold` repeats,
        nudge the tile that owns that actuator to learn to offer it."""
        self._manual[actuator] = self._manual.get(actuator, 0) + 1
        if self._manual[actuator] < threshold:
            return None
        self._manual[actuator] = 0
        target = next(
            (rec.name for rec in self._tiles.values() if rec.manifest and actuator in rec.manifest.actuators),
            None,
        )
        signal = FrictionSignal(kind="repeat", at=at, target_tile=target, count=threshold)
        if target:
            await self.deliver_friction(signal)
        return signal

    async def _on_fault(self, name: str) -> None:
        rec = self._tiles[name]
        now = time.time()
        rec.faults += 1
        rec.fault_times.append(now)
        rec.fault_times = [t for t in rec.fault_times if now - t <= self.policy.quarantine_window]
        if len(rec.fault_times) >= self.policy.quarantine_after:
            rec.state = "QUARANTINED"
            self.bus.drop_owner(f"tile:{name}")
            rec.subs.clear()
            log.warning("tile %s quarantined after %d faults", name, len(rec.fault_times))
            return
        try:  # restart in place — reload the cell
            await rec.channel.stop()
            await rec.channel.start()
        except Exception:
            rec.state = "QUARANTINED"
            self.bus.drop_owner(f"tile:{name}")
            rec.subs.clear()
            log.warning("tile %s failed to restart; quarantined", name)

    def _make_ctx(self, manifest: Manifest) -> TileContext:
        name = manifest.name

        async def emit(event: Event) -> None:
            await self.bus.publish(event)

        async def act(actuator: str, value) -> None:
            ref = ActionRef(uuid4().hex, name, actuator, value, time.time())
            self._ledger.append(ref)
            cutoff = ref.at - self.policy.reversal_window
            self._ledger = [r for r in self._ledger if r.at >= cutoff]  # bounded by window
            await self.bus.publish(
                Event("actuator.requested", ref.at, {"actuator": actuator, "value": value, "tile": name}, source=f"tile:{name}")
            )

        async def speak(text: str) -> None:
            await self.bus.publish(Event("interface.say", time.time(), {"text": text}, source=f"tile:{name}"))

        def log_fn(level: str, msg: str) -> None:
            log.log(getattr(logging, level.upper(), logging.INFO), msg)

        recall = None
        if self.remember is not None:
            async def recall(topic: str, zone: str | None, when: float):
                return await self.remember.normal(topic, zone, when)

        return TileContext(manifest, emit=emit, act=act, speak=speak, log_fn=log_fn, recall=recall)

    def status(self) -> dict[str, str]:
        return {name: rec.state for name, rec in self._tiles.items()}
