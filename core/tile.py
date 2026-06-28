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
import os
import re
import sys
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Protocol
from uuid import uuid4

log = logging.getLogger("homie.tile")


# --------------------------------------------------------------------------- #
# Contract types
# --------------------------------------------------------------------------- #
PARAM_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object"})
# Bus Priority level names (lowercase). Kept here to avoid a tile->bus import cycle;
# core/act.py maps these strings to the bus Priority enum.
PRIORITY_LEVELS = frozenset({"ambient", "convenience", "automation", "security", "safety"})


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False


@dataclass(frozen=True)
class FunctionSpec:
    """An LLM-callable function's contract — name, description, and parameters."""

    name: str
    description: str = ""
    params: tuple[ParamSpec, ...] = ()


@dataclass(frozen=True)
class Manifest:
    """Parsed tile.toml — the six-clause contract: what a tile touches."""

    name: str
    summary: str
    subscribes: tuple[str, ...] = ()  # event patterns
    intents: tuple[str, ...] = ()  # voice phrases
    functions: tuple[str, ...] = ()  # LLM-callable names (routing key)
    function_specs: tuple[FunctionSpec, ...] = ()  # parallel rich specs (tool-calling)
    actuators: tuple[str, ...] = ()  # what it may drive
    reads: tuple[str, ...] = ()  # data domains it may read
    network: str = "local"  # "local" | "egress:<host>"
    default_priority: str = "automation"  # bus Priority level for this tile's acts
    act_priorities: tuple[tuple[str, str], ...] = ()  # per-actuator overrides (actuator, level)
    path: Path | None = None  # tiles/<name>/, set by the loader

    @property
    def needs_isolation(self) -> bool:
        """A tile runs out-of-process when it can reach the network or is
        otherwise declared unsafe — so `local`-only can be truly enforced."""
        return self.network != "local"

    def priority_for(self, actuator: str) -> str:
        """The bus Priority level (lowercase name) for an act on this actuator —
        a per-actuator override if declared, else the tile default."""
        for act, level in self.act_priorities:
            if act == actuator:
                return level
        return self.default_priority


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
    # Context stamped at capture (BACKLOG #9): who triggered the correction and
    # where. Used downstream for per-person attribution and for the privacy
    # exclusions (never train on guests / sensitive zones). None = unknown.
    zone: str | None = None
    actor: str | None = None


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
    async def speak(self, text: str, *, kind: str = "proactive") -> None: ...  # governed by the VoiceGate
    async def recall(self, topic: str, zone: str | None, when: float): ...  # Behavioral Analysis
    async def confirm(self, prompt: str, *, risk: str = "medium") -> bool: ...  # ask for a yes/no
    @property
    def can_confirm(self) -> bool: ...  # is an ask-channel wired? (offer vs act silently)
    async def beliefs(self, when: float, *, min_prob: float = 0.3) -> list[dict]: ...  # firm routines
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
        tmp = self._data_file.with_suffix(".tmp")  # atomic write: a crash can't corrupt data.json
        tmp.write_text(json.dumps(self._data), "utf-8")
        os.replace(tmp, self._data_file)

    def config(self) -> dict:
        f = self.path / "config.toml"
        return tomllib.loads(f.read_text("utf-8")) if f.exists() else {}

    def secret(self, key: str) -> str | None:
        return None  # secrets.env handling lands with the subprocess channel


class TileContext:
    """Concrete Context. Enforces the manifest's actuator permissions, then
    forwards to runtime-provided sinks (so it stays decoupled and testable)."""

    def __init__(self, manifest: Manifest, *, emit, act, speak, log_fn, recall=None, confirm=None,
                 beliefs=None) -> None:
        self.manifest = manifest
        self._emit = emit
        self._act = act
        self._speak = speak
        self._log = log_fn
        self._recall = recall
        self._confirm = confirm
        self._beliefs = beliefs

    async def act(self, actuator: str, value) -> None:
        if actuator not in self.manifest.actuators:
            self._log("warning", f"{self.manifest.name}: act on undeclared '{actuator}' refused")
            raise PermissionError(actuator)
        await self._act(actuator, value, self.manifest.priority_for(actuator))

    async def emit(self, event: Event) -> None:
        await self._emit(event)

    async def speak(self, text: str, *, kind: str = "proactive") -> None:
        await self._speak(text, kind=kind)

    async def recall(self, topic: str, zone: str | None, when: float):
        """Query the pattern of life (Behavioral Analysis) — what is normal here?"""
        if self._recall is None:
            raise RuntimeError("recall unavailable (no Remember wired into the Supervisor)")
        return await self._recall(topic, zone, when)

    @property
    def can_confirm(self) -> bool:
        """Whether an ask-channel is wired. A tile that wants to OFFER (vs act silently)
        checks this first, so it can fall back gracefully where no Consent is present."""
        return self._confirm is not None

    async def confirm(self, prompt: str, *, risk: str = "medium") -> bool:
        """Ask the human a yes/no (answered by gesture or voice). Fails safe to
        False (don't act) on no answer. Never use this to gate a safety-critical
        actuator — those are never-autonomous via the act-map."""
        if self._confirm is None:
            raise RuntimeError("confirm unavailable (no Consent wired into the Supervisor)")
        return await self._confirm(prompt, risk=risk)

    async def beliefs(self, when: float, *, min_prob: float = 0.3) -> list[dict]:
        """The firm, plain things Homie believes about the household's routines (the 'What
        Homie Knows' rows) — for the morning briefing. Empty when no Remember is wired."""
        if self._beliefs is None:
            return []
        return await self._beliefs(when, min_prob=min_prob)

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
    errors: list[str] = []
    function_specs = _parse_functions(raw.get("provides", {}).get("functions", []), errors)
    functions = tuple(s.name for s in function_specs)
    acts = raw.get("acts", {})
    actuators = tuple(acts.get("actuators", []))
    default_priority = acts.get("priority", "automation")
    act_priorities = tuple((a, lvl) for a, lvl in acts.get("priorities", {}).items())
    perms = raw.get("permissions", {})
    reads = tuple(perms.get("reads", []))
    network = perms.get("network", "local")

    for lvl in (default_priority, *(lvl for _, lvl in act_priorities)):
        if lvl not in PRIORITY_LEVELS:
            errors.append(f"invalid priority level '{lvl}'")
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
        function_specs=function_specs,
        actuators=actuators,
        reads=reads,
        network=network,
        default_priority=default_priority,
        act_priorities=act_priorities,
        path=folder,
    )


def _parse_functions(raw_functions, errors: list[str]) -> tuple[FunctionSpec, ...]:
    """Parse [provides].functions, which may be a list of bare names (strings) or
    a list of rich tables ([[provides.functions]] with name/description/params).
    Best-effort: structural problems append to `errors` (fail-closed via the caller)."""
    specs: list[FunctionSpec] = []
    for entry in raw_functions:
        if isinstance(entry, str):
            specs.append(FunctionSpec(name=entry))
            continue
        if not isinstance(entry, dict):
            errors.append("invalid function entry")
            continue
        fname = entry.get("name", "")
        if not fname:
            errors.append("function missing name")
            continue
        params: list[ParamSpec] = []
        for p in entry.get("params", []):
            pname = p.get("name", "") if isinstance(p, dict) else ""
            if not pname:
                errors.append(f"param missing name on function '{fname}'")
                continue
            ptype = p.get("type", "string")
            if ptype not in PARAM_TYPES:
                errors.append(f"invalid param type '{ptype}' on function '{fname}'")
            params.append(
                ParamSpec(
                    name=pname,
                    type=ptype,
                    description=p.get("description", ""),
                    required=bool(p.get("required", False)),
                )
            )
        specs.append(FunctionSpec(name=fname, description=entry.get("description", ""), params=tuple(params)))
    return tuple(specs)


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

    def __init__(self, manifest: Manifest, ctx: Context, *, state_dir: Path | None = None) -> None:
        self.manifest = manifest
        self.ctx = ctx
        self._state_dir = Path(state_dir) if state_dir else manifest.path / "state"
        self._tile: Tile | None = None
        self._learn: Callable | None = None
        self._health: Callable | None = None
        self._state: TileState | None = None

    async def start(self) -> None:
        tile_cls, learn_fn, health_fn = load_tile(self.manifest)
        self._state = TileState(self._state_dir)
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
            note = await self._learn(self._state, signal)
            if note:  # the tile changed its mind — let it say so, once (M4)
                await self.ctx.speak(note)

    async def call(self, fn: str, **args) -> object:
        return await getattr(self._tile, fn)(self.ctx, **args)

    async def check_health(self) -> bool:
        if self._health:
            return bool(await self._health(self._state))
        return True


class SubprocessChannel:
    """Escape hatch. Runs the tile as a child process speaking line-delimited
    JSON over stdio (PROTOCOL.md). Used when the manifest declares egress or is
    otherwise unsafe: the process boundary contains crashes, hangs, and leaks,
    and the deploy layer adds a network namespace to enforce the network policy.

    The child's outbound act/emit/speak are forwarded through the parent's
    permission-enforcing Context, so a child cannot drive an undeclared actuator
    even if its own checks are bypassed.
    """

    _ROOT = Path(__file__).resolve().parents[1]

    def __init__(self, manifest: Manifest, ctx: Context, *, call_timeout: float = 10.0, state_dir: Path | None = None) -> None:
        self.manifest = manifest
        self.ctx = ctx
        self.call_timeout = call_timeout  # kill a child that wedges past this
        self._state_dir = Path(state_dir) if state_dir else manifest.path / "state"
        self._proc: asyncio.subprocess.Process | None = None
        self._lock: asyncio.Lock | None = None

    async def start(self) -> None:
        self._lock = asyncio.Lock()
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "core.tile_harness",
            str(self.manifest.path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            cwd=str(self._ROOT),
            env={**os.environ, "PYTHONPATH": str(self._ROOT)},
        )
        await self._exchange(
            {"type": "init", "name": self.manifest.name, "state_dir": str(self._state_dir)},
            {"ready"},
        )

    async def stop(self, *, grace: float = 5.0) -> None:
        if not self._proc:
            return
        if self._proc.returncode is None:  # still running — ask, then kill
            try:
                self._proc.stdin.write(b'{"type": "stop"}\n')
                await self._proc.stdin.drain()
                await asyncio.wait_for(self._proc.wait(), timeout=grace)
            except Exception:
                try:
                    self._proc.kill()
                    await self._proc.wait()
                except ProcessLookupError:
                    pass  # already gone
        self._proc = None

    async def send_event(self, event: Event) -> None:
        await self._exchange({"type": "event", "event": asdict(event)}, {"done"})

    async def deliver_friction(self, signal: FrictionSignal) -> None:
        await self._exchange({"type": "friction", "signal": asdict(signal)}, {"done"})

    async def call(self, fn: str, **args) -> object:
        m = await self._exchange({"type": "call", "fn": fn, "args": args}, {"result"})
        return m["value"]

    async def check_health(self) -> bool:
        m = await self._exchange({"type": "health"}, {"health"})
        return bool(m["ok"])

    async def _exchange(self, msg: dict, terminal: set[str]) -> dict:
        async with self._lock:
            self._proc.stdin.write((json.dumps(msg) + "\n").encode())
            await self._proc.stdin.drain()
            try:
                return await asyncio.wait_for(self._read_until(terminal), timeout=self.call_timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                # a wedged child must not hold the channel: kill it so the next
                # call starts a fresh process rather than a half-spoken protocol
                self._proc.kill()
                await self._proc.wait()
                raise RuntimeError(f"tile '{self.manifest.name}' timed out — killed")

    async def _read_until(self, terminal: set[str]) -> dict:
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                raise RuntimeError(f"tile '{self.manifest.name}' subprocess exited")
            m = json.loads(line)
            kind = m["type"]
            if kind in ("emit", "act", "speak", "log"):
                await self._forward(kind, m)
            elif kind == "error":
                raise RuntimeError(m.get("error", "tile error"))
            elif kind in terminal:
                return m

    async def _forward(self, kind: str, m: dict) -> None:
        if kind == "emit":
            ev = Event(**m["event"])
            if ev.topic == "actuator.requested":  # a child cannot smuggle a forged command (C2)
                log.warning("tile %s: subprocess emit of actuator.requested dropped", self.manifest.name)
                return
            await self.ctx.emit(ev)
        elif kind == "act":
            await self.ctx.act(m["actuator"], m["value"])
        elif kind == "speak":
            await self.ctx.speak(m["text"])
        elif kind == "log":
            self.ctx.log(m["level"], m["msg"])


def channel_for(manifest: Manifest, ctx: Context, state_dir: Path | None = None) -> TileChannel:
    """Pick the transport from the manifest — the single isolation switch."""
    if manifest.needs_isolation:
        return SubprocessChannel(manifest, ctx, state_dir=state_dir)
    return InProcessChannel(manifest, ctx, state_dir=state_dir)


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
    manual_window: float = 86400.0  # window for counting repeated manual actions (a day)


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

    def __init__(self, tiles_dir: Path, bus, policy: SupervisionPolicy | None = None, *, remember=None, consent=None, state_root: Path | None = None, registry=None) -> None:
        self.tiles_dir = Path(tiles_dir)
        # Where tiles keep their writable state. Under the hardened service
        # /opt/homie is read-only (ProtectSystem=strict); state must live in
        # $HOMIE_STATE (/var/lib/homie). Default None keeps the dev/test layout
        # (state beside the tile) so the suite is unchanged.
        self.state_root = Path(state_root) if state_root else None
        self.bus = bus
        self.policy = policy or SupervisionPolicy()
        self.remember = remember  # Behavioral Analysis, exposed to tiles via ctx.recall
        self.consent = consent  # confirmation gate, exposed to tiles via ctx.confirm
        self._caps = registry  # capability minter (C2); None = legacy path (no cap stamped)
        self._tiles: dict[str, TileRecord] = {}
        self._ledger: list[ActionRef] = []  # recent acts, for friction attribution
        self._manual: dict[str, list[float]] = {}  # windowed manual-action times, for repeat detection

    def _state_dir(self, manifest: Manifest) -> Path:
        """A tile's writable state dir. Under a configured state_root it lives in
        $HOMIE_STATE/tiles/<name>/state (writable on the hardened OS); otherwise
        beside the tile (dev/test default)."""
        if self.state_root is not None:
            return self.state_root / "tiles" / manifest.name / "state"
        return manifest.path / "state"

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
        clashes = [f"function '{fn}' already provided by tile '{self._function_owner(fn)}'"
                   for fn in manifest.functions if self._function_owner(fn) not in (None, name)]
        if clashes:  # global function-name uniqueness — surface the collision, don't shadow
            self._tiles[name] = TileRecord(
                name, None, None, None, "INVALID", invalid=InvalidManifest(name, manifest.path, tuple(clashes))
            )
            log.warning("tile %s invalid: %s", name, "; ".join(clashes))
            return
        ctx = self._make_ctx(manifest)
        channel = channel_for(manifest, ctx, self._state_dir(manifest))
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
        if self._caps is not None:
            self._caps.revoke_tile(name)  # a stopped tile's capabilities die with it
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

    def tool_catalog(self) -> list[dict]:
        """OpenAI-style `tools` array for every function on every READY tile —
        directly usable as the model's tool list. A quarantined tile offers nothing."""
        tools: list[dict] = []
        for rec in self._tiles.values():
            if rec.state != "READY" or not rec.manifest:
                continue
            for spec in rec.manifest.function_specs:
                props = {}
                required = []
                for p in spec.params:
                    schema = {"type": p.type}
                    if p.description:
                        schema["description"] = p.description
                    props[p.name] = schema
                    if p.required:
                        required.append(p.name)
                parameters = {"type": "object", "properties": props}
                if required:
                    parameters["required"] = required
                tools.append(
                    {"type": "function",
                     "function": {"name": spec.name, "description": spec.description, "parameters": parameters}}
                )
        return tools

    def _function_owner(self, fn: str) -> str | None:
        for rec in self._tiles.values():
            if rec.state == "READY" and rec.manifest and fn in rec.manifest.functions:
                return rec.name
        return None

    async def deliver_friction(self, signal: FrictionSignal) -> None:
        rec = self._tiles.get(signal.target_tile) if signal.target_tile else None
        if rec and rec.state == "READY":
            try:
                await asyncio.wait_for(rec.channel.deliver_friction(signal), timeout=self.policy.learn_timeout)
            except Exception:
                await self._on_fault(rec.name)

    # friction attribution — turn a reaction into a learning signal for one tile
    async def note_reversal(self, actuator: str, value, at: float, *, zone: str | None = None, actor: str | None = None) -> FrictionSignal | None:
        """A human undid an actuator. Attribute it to the tile whose recent act
        on that actuator is being reversed, and deliver the correction. `zone`/
        `actor` (when known) are stamped on the signal for per-person learning and
        the privacy exclusions."""
        recent = [r for r in self._ledger if r.actuator == actuator and at - r.at <= self.policy.reversal_window]
        if not recent:
            return None
        ref = max(recent, key=lambda r: r.at)
        if ref.value == value:  # same state — not a reversal
            return None
        signal = FrictionSignal(kind="reversal", at=at, target_tile=ref.tile, reverses=ref, zone=zone, actor=actor)
        await self.deliver_friction(signal)
        return signal

    async def note_remark(self, text: str, at: float, *, zone: str | None = None, actor: str | None = None) -> FrictionSignal | None:
        """A spoken correction — strongest signal. Attribute to the most recent
        acting tile within the window."""
        recent = [r for r in self._ledger if at - r.at <= self.policy.reversal_window]
        if not recent:
            return None
        target = max(recent, key=lambda r: r.at).tile
        signal = FrictionSignal(kind="remark", at=at, target_tile=target, text=text, zone=zone, actor=actor)
        await self.deliver_friction(signal)
        return signal

    async def note_manual(self, actuator: str, at: float, *, threshold: int = 3, zone: str | None = None, actor: str | None = None) -> FrictionSignal | None:
        """A human keeps doing something by hand. After `threshold` repeats within
        the window, nudge the tile that owns that actuator to learn to offer it."""
        window = self.policy.manual_window
        # prune aged keys (no unbounded growth) and stale timestamps
        self._manual = {
            a: [t for t in ts if at - t <= window]
            for a, ts in self._manual.items()
            if a == actuator or any(at - t <= window for t in ts)
        }
        times = self._manual.get(actuator, [])
        times.append(at)
        self._manual[actuator] = times
        if len(times) < threshold:
            return None
        self._manual[actuator] = []  # reset after firing
        # attribute to the tile that most recently acted on this actuator, else any owner
        owners = [rec.name for rec in self._tiles.values() if rec.manifest and actuator in rec.manifest.actuators]
        recent = [r.tile for r in reversed(self._ledger) if r.actuator == actuator and r.tile in owners]
        target = recent[0] if recent else (owners[0] if owners else None)
        signal = FrictionSignal(kind="repeat", at=at, target_tile=target, count=threshold, zone=zone, actor=actor)
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
            if self._caps is not None:
                self._caps.revoke_tile(name)  # a quarantined tile loses its capabilities
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
            # ctx.emit is NOT the act path. Refuse a raw actuator.requested here so a tile
            # cannot bypass the capability gate by emitting a forged command (C2/N3) — the
            # forged event never even reaches the bus.
            if event.topic == "actuator.requested":
                log.warning("tile %s: raw emit of actuator.requested refused (use ctx.act)", name)
                return
            await self.bus.publish(event)

        async def act(actuator: str, value, priority: str = "automation") -> None:
            ref = ActionRef(uuid4().hex, name, actuator, value, time.time())
            self._ledger.append(ref)
            cutoff = ref.at - self.policy.reversal_window
            self._ledger = [r for r in self._ledger if r.at >= cutoff]  # bounded by window
            # The priority is taken from the manifest, never the caller — a tile cannot ask
            # for a level it wasn't granted even through ctx.act (defence in depth with
            # TileContext.act). The minted handle is the only thing Act will trust.
            level = manifest.priority_for(actuator)
            payload = {"actuator": actuator, "value": value, "tile": name, "priority": level}
            if self._caps is not None:
                payload["cap"] = self._caps.mint(name, actuator, level)
            await self.bus.publish(Event("actuator.requested", ref.at, payload, source=f"tile:{name}"))

        async def speak(text: str, *, kind: str = "proactive") -> None:
            # Emit a fact-to-say; the VoiceGate (core/voice.py) decides whether the owner
            # actually hears it. `kind="safety"`/`"alert"` bypasses the speech budget.
            await self.bus.publish(Event("interface.say", time.time(),
                                         {"text": text, "kind": kind}, source=f"tile:{name}"))

        def log_fn(level: str, msg: str) -> None:
            log.log(getattr(logging, level.upper(), logging.INFO), msg)

        recall = None
        beliefs = None
        if self.remember is not None:
            async def recall(topic: str, zone: str | None, when: float):
                return await self.remember.normal(topic, zone, when)

            async def beliefs(when: float, *, min_prob: float = 0.3):
                return self.remember.beliefs(when, min_prob=min_prob)

        confirm = None
        if self.consent is not None:
            async def confirm(prompt: str, *, risk: str = "medium"):
                return await self.consent.request(prompt, actuator=None, risk=risk)

        return TileContext(manifest, emit=emit, act=act, speak=speak, log_fn=log_fn,
                           recall=recall, confirm=confirm, beliefs=beliefs)

    def status(self) -> dict[str, str]:
        return {name: rec.state for name, rec in self._tiles.items()}
