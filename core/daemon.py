"""build_daemon — the single assembler of the whole Homie graph.

THE most important invariant in the system lives here: **there is exactly one
wiring of Homie.** `build_daemon(home, perception, *, config)` constructs the whole
living loop — bus → perceive → remember → tiles → act → reconcile → friction →
reason — and the production daemon (`scripts/run.py`), the spine demo
(`scripts/spine_demo.py`), and the tests all drive *this same graph*, differing
only by what they inject (the `HomeClient`, the perception source, the `LLMClient`).

Why this matters (the audit's two worst findings, killed by construction):

  * **C1** — the old `run.py` wired Bus + Remember + Consent + Supervisor + Reason +
    Cockpit and STOPPED: Act, the StateReconciler, and the ritual were real, tested
    code that production never instantiated, so the shipped daemon could not drive a
    light or learn from a reversal while every test passed. Here Act, the reconciler,
    and the in-process ritual are wired UNCONDITIONALLY — there is no second path that
    can "forget" them.
  * **C4** — Remember must commit an event only AFTER the anomaly evaluators
    (Security tile, Reason) have judged it against prior history, or the event masks
    its own novelty. `Daemon.start()` attaches Remember to the bus LAST, after the
    tiles and Reason subscribe, so for any event the evaluators' drain tasks are
    scheduled ahead of Remember's. The ordering is decided once, here, for everyone.

Reason is ALWAYS wired (with a `NullLLMClient` when no model is configured), so the
proposer path is present and tested everywhere. The mesh is a seam that defaults to
loopback (no bridge — a single process needs no wire); multi-node is a config flag,
not a rewrite.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from core.act import Act, ActMap, CommandLog
from core.capability import CapabilityRegistry
from core.anchor_voice import AnchorVoice
from core.bus import Bus
from core.canonical import ha_canonical
from core.clock import Clock
from core.cockpit_bridge import CockpitBridge
from core.commands import SlashCommands
from core.confirm_responder import ConfirmResponder
from core.consent import Consent
from core.friction_ledger import FrictionLedger
from core.groundskeeper import Groundskeeper
from core.ha_agenda import HAAgendaSource, HAWsQuery
from core.mesh import Link, MeshBridge
from core.models import ModelRegistry
from core.reason import LLMClient, NullLLMClient, Reason
from core.reconcile import StateReconciler
from core.selfimprove import ImproveTracker
from core.remember import Remember
from core.gist_store import GistCollector, GistStore
from core.ritual import consolidate
from core.watchdog import Watchdog
from core.watchlog import WatchLog, WatchTracker
from core.tile import Event, Supervisor
from core.undo import Undo
from core.voice import VoiceGate

log = logging.getLogger("homie.daemon")

ROOT = Path(__file__).resolve().parents[1]


class Perception(Protocol):
    """The single perception-intake seam. A source pulls normalized events from a
    device/mesh and publishes them onto the bus. `SyntheticPerception` (M2) and the
    live adapter implement the same `run`; the harness is NOT a test-only fork."""

    async def run(self, bus: Bus) -> None: ...


@dataclass
class DaemonConfig:
    """Everything the assembler needs that isn't an injected seam. Sensible
    ephemeral defaults so a test can `build_daemon(FakeHome(), None)` and get the
    whole real graph in memory."""

    state: Path | None = None          # HOMIE_STATE; None = in-memory/ephemeral (tests)
    tiles_dir: Path | None = None      # defaults to <repo>/tiles
    act_map: ActMap | None = None      # None = no actuators mapped (empty allowlist)
    compact_threshold: int = 5000      # durability-log auto-compact floor
    tick_seconds: float = 60.0         # Clock cadence: tick.minute (+ tick.hour on the hour)
    morning_hour: int = 7              # local hour the clock fires time.morning (the day briefing)
    compact_interval: float = 3600.0   # how often the housekeep loop ticks
    ritual_interval: float = 86400.0   # nightly consolidation cadence
    llm: LLMClient | None = None       # a real client => the reasoning cortex is present
    cockpit_sock: str | None = None    # None = no cockpit bridge
    mesh_link: Link | None = None      # None = loopback (single node, no serialization)
    node_id: str = "homie"
    housekeep: bool = True             # run the periodic compaction/ritual task
    now: Callable[[], float] = time.time
    # The live morning-briefing feed: which HA calendar/to-do/weather entities to read. Wired
    # only when the home is a real HA client (has `request`) AND at least one is configured;
    # empty => no external source (the briefing renders from learned routines + the list alone).
    ha_calendars: list[str] = field(default_factory=list)
    ha_todo_lists: list[str] = field(default_factory=list)
    ha_weather_entity: str | None = None
    # Runner for owner-typed system /commands (/update, /restart, /reboot, …). None = reply with
    # the command to paste (safe default); deploy injects a subprocess runner when HOMIE_SHELL_COMMANDS=1.
    shell_runner: Callable[[list], str] | None = None

    @property
    def has_cortex(self) -> bool:
        return self.llm is not None


class Daemon:
    """The assembled organism. `start()` wires every subscription in the one correct
    order (Remember LAST); `stop()` tears it down; `run_forever()` parks until the
    service is stopped. Tests inspect `.bus`, `.remember`, `.sup`, etc. directly."""

    def __init__(self, *, bus, remember, consent, confirm, ledger, undo, commands, improve, sup, act, reconciler, reason,
                 voice, anchor, cockpit, mesh, clock, home, perception, config: DaemonConfig,
                 ha_agenda=None, groundskeeper=None, gist=None, watch=None) -> None:
        self.bus = bus
        self.remember = remember
        self.consent = consent
        self.confirm = confirm        # turns a chat yes/no into a confirm.response (Consent answerable)
        self.ledger = ledger          # the undo timeline: every confirmed action as a reversible row
        self.undo = undo              # one-tap reversal: re-drives a row's prior value (guarded ones ask)
        self.commands = commands      # owner-typed /commands in chat
        self.improve = improve        # nightly self-improvement loop (correction-rate trend)
        self.sup = sup
        self.act = act
        self.reconciler = reconciler
        self.reason = reason
        self.voice = voice            # the speech governor (always wired): the one muzzle
        self.clock = clock
        self.anchor = anchor          # None when a real cortex owns chat
        self.cockpit = cockpit        # None when no socket configured
        self.mesh = mesh              # None = loopback (single node)
        self.home = home
        self.perception = perception
        self.ha_agenda = ha_agenda    # live HA calendar/to-do/weather feed (None if not configured)
        self.groundskeeper = groundskeeper  # storage limb (None for in-memory test graphs)
        self.gist = gist              # distilled-memory collector (None for in-memory test graphs)
        self.watch = watch            # watch-history tracker (None for in-memory test graphs)
        self.config = config
        self._tasks: list[asyncio.Task] = []
        self.started = False

    async def start(self) -> None:
        # Rebuild the pattern of life from the durability log before any live wiring
        # (pure read, no subscription).
        self.remember.bootstrap(self.bus)

        # --- the one correct wiring order ------------------------------------- #
        await self.consent.start()
        await self.confirm.start()            # makes the consent gate answerable from chat
        await self.act.start()
        await self.ledger.start()             # record actions for the undo timeline
        if self.gist is not None:
            await self.gist.start()           # buffer the day's life-shape for the nightly distill
        if self.watch is not None:
            await self.watch.start()          # record the full watch history (titles + all)
        await self.undo.start()               # one-tap reversal: re-drive a row's prior value
        await self.commands.start()           # owner-typed /commands in chat
        await self.improve.start()            # count corrections; speak the trend each morning
        await self.voice.start()              # the muzzle: live BEFORE any tile can speak
        self.reconciler.attach(self.home)     # human state-changes -> friction
        # The home is a managed seam: a real adapter (HA WebSocket) runs a background
        # connection loop, started AFTER its handler is attached so no echo is missed.
        # LoggingHome / test fakes have no start(), so this is a no-op for them.
        home_start = getattr(self.home, "start", None)
        if callable(home_start):
            await home_start()
        await self.sup.start_all()            # tiles subscribe (evaluators)
        await self.clock.start()              # the heartbeat: tick.* + the timer seam
        if self.ha_agenda is not None:
            await self.ha_agenda.start()      # live calendar/weather feed → agenda.external
        await self.reason.start()             # the proposer (real or null)
        if self.anchor is not None:
            await self.anchor.start()         # anchor chat floor (no-cortex only)
        if self.cockpit is not None:
            try:
                await self.cockpit.start()
            except Exception as ex:           # the cockpit is optional, never fatal
                log.warning("cockpit bridge failed to start (%r); continuing", ex)
                self.cockpit = None
        if self.mesh is not None:
            await self.mesh.start()
        # C4: Remember commits AFTER the evaluators above have subscribed, so an
        # event is judged against prior history before it joins that history.
        self.remember.attach(self.bus)

        if self.perception is not None:
            self._spawn(self._run_perception())
        if self.config.housekeep:
            self._spawn(self._housekeep())
        self.started = True
        # Self-heal watchdog (Charter 27a): prove liveness to systemd so a HUNG daemon recovers.
        # Only under systemd (NOTIFY_SOCKET set); a harmless no-op in dev/tests.
        if os.environ.get("NOTIFY_SOCKET"):
            self._spawn(Watchdog(self._healthy).run())
        log.info("homie: daemon up (cortex=%s, tiles=%s)", self.config.has_cortex, self.sup.status())

    def _healthy(self) -> bool:
        """Liveness signal for the watchdog: up, with no tile stuck quarantined/degraded."""
        try:
            return self.started and not any(
                s in ("QUARANTINED", "DEGRADED") for s in self.sup.status().values())
        except Exception:
            return self.started

    def _spawn(self, coro: Awaitable[None]) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._tasks.append(task)
        return task

    async def _run_perception(self) -> None:
        try:
            await self.perception.run(self.bus)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("perception intake exited")

    async def _housekeep(self) -> None:
        """In-process compaction floor + nightly consolidation. Running the ritual
        here (not from a systemd timer firing a second process) is deliberate: the
        daemon already holds events.jsonl, so there is no second-writer data-loss
        race (closes C13). One bad cycle must never kill the loop."""
        last_ritual = self.config.now()
        while True:
            try:
                await asyncio.sleep(self.config.compact_interval)
                now = self.config.now()
                if now - last_ritual >= self.config.ritual_interval:
                    await consolidate(bus=self.bus, remember=self.remember,
                                      supervisor=self.sup, now=now,
                                      gist_fold=self.gist.fold if self.gist is not None else None)
                    last_ritual = now
                else:
                    await self.bus.maybe_compact(self.remember.snapshot)
                # The storage limb runs every cycle: a cheap disk read, silent densify under
                # pressure, a notice only when almost full. Never raises into the loop.
                if self.groundskeeper is not None:
                    await self.groundskeeper.tick(now)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("housekeep cycle failed; will retry")

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self.ha_agenda is not None:
            await self.ha_agenda.stop()
        await self.clock.stop()
        await self.reason.stop()
        await self.voice.stop()
        await self.confirm.stop()
        await self.undo.stop()
        await self.commands.stop()
        await self.improve.stop()
        if self.gist is not None:
            await self.gist.stop()
        if self.watch is not None:
            await self.watch.stop()
        await self.ledger.stop()
        if self.anchor is not None:
            await self.anchor.stop()
        if self.cockpit is not None:
            await self.cockpit.stop()
        if self.mesh is not None:
            await self.mesh.stop()
        home_stop = getattr(self.home, "stop", None)
        if callable(home_stop):
            await home_stop()
        await self.act.stop()
        await self.consent.stop()
        await self.bus.aclose()
        self.started = False

    async def run_forever(self) -> None:
        await asyncio.Event().wait()


def build_daemon(home, perception: Perception | None, *, config: DaemonConfig | None = None) -> Daemon:
    """Assemble the entire Homie graph. The ONLY wiring of the system.

    `home` is the injected `HomeClient` (a real MQTT/HA client in deploy, a
    `FakeHome` in tests/demo). `perception` is the injected intake source (a live
    adapter, a `SyntheticPerception`, or None for a graph driven by direct
    publishes). Everything else comes from `config`.
    """
    config = config or DaemonConfig()
    tiles_dir = config.tiles_dir or (ROOT / "tiles")
    act_map = config.act_map if config.act_map is not None else ActMap.from_forward({})

    bus = Bus(log_path=(config.state / "events.jsonl") if config.state else None,
              compact_threshold=config.compact_threshold)
    remember = Remember()
    consent = Consent(bus)
    confirm = ConfirmResponder(bus)   # the missing producer: a chat yes/no answers a confirm (N10)
    ledger = FrictionLedger(bus)      # the undo timeline (records confirmed actions)
    # ONE capability registry, shared by reference with both the minter (Supervisor's
    # ctx.act) and the verifier (Act). This is the single wiring that makes least-privilege
    # true: a tile can only drive what its manifest declares, at the priority it declares,
    # even via a raw emit (C2). Built here so there is exactly one instance (the keystone).
    registry = CapabilityRegistry()
    # One-tap undo: re-drives a ledger row's prior value through the SAME capability-gated act
    # path (it mints its own ("undo", actuator) handle — never a forged payload). Guarded
    # domains (locks/garage/alarm) route through Consent first; everything else is instant.
    undo = Undo(bus, ledger, registry, consent=consent)
    # Switchable brains: a general one + a fine-tuned dev one (deploy/models.toml). The active
    # choice persists under the state dir; the cortex picks it up on (re)start.
    models = ModelRegistry.load(ROOT / "deploy" / "models.toml",
                                state_path=(Path(config.state) / "model.active") if config.state else None)
    # Owner-typed /commands in chat (/status, /now, /recommend, /mute, /private, /model, /reboot…).
    slash_commands = SlashCommands(bus, state=config.state, runner=config.shell_runner,
                                   root=str(ROOT), models=models)
    sup = Supervisor(tiles_dir, bus, remember=remember, consent=consent,
                     state_root=config.state, registry=registry)

    # The act path: one CommandLog shared by Act (writer) and the reconciler
    # (matcher) so Homie's own echoes are suppressed and only human changes become
    # friction. ha_canonical normalizes values to the home's echo form.
    commands = CommandLog(canonical=ha_canonical)
    act = Act(bus, home, commands, act_map, registry=registry)
    # Self-improvement (the measurable loop): a human reversal of Homie's own act is a
    # correction; count them per day and speak the trend each morning.
    improve = (ImproveTracker(bus, state_path=Path(config.state) / "improve.json",
                              tz=os.environ.get("HOMIE_TZ"))
               if config.state is not None else ImproveTracker(bus))

    async def _on_correction(actuator, zone, actor, at):
        await bus.publish(Event("friction.correction", at,
                                {"actuator": actuator, "zone": zone, "actor": actor}, source="reconcile"))

    reconciler = StateReconciler(sup, commands, act_map.reverse, on_echo=act.confirm,
                                 on_correction=_on_correction)

    # Reason is ALWAYS wired; a real client means the cortex is present, else the
    # null client makes the proposer a tested no-op. The anchor chat floor is wired
    # ONLY when there is no cortex, so chat is answered exactly once.
    # Active memory (M7): feed the cortex "what Homie knows about you" — the live firm beliefs
    # plus the nightly-distilled GIST brief — so a chat answer is informed by what it has learned.
    def _memory_brief() -> list[str]:
        lines: list[str] = []
        try:
            from core.journal import what_homie_knows
            lines += what_homie_knows(remember.beliefs(config.now(), min_prob=0.3))
        except Exception:
            pass
        if config.state is not None:
            try:
                from core.gist import render_brief
                from core.gist_store import GistStore
                lines += render_brief(GistStore(Path(config.state) / "memory.ddn").load(), min_firmness=3)
            except Exception:
                pass
        return lines

    reason = Reason(bus, config.llm or NullLLMClient(), sup, remember, memory_brief=_memory_brief)

    # The Voice waist: the ONE governor on owner-facing speech. Tiles and the cortex emit
    # interface.say; this gate decides what the owner actually hears (interface.spoken) and
    # what defers to the morning recap (speech.deferred). Wired unconditionally — there is
    # no second path that can speak to the owner ungoverned (Phase A: muzzle before mouths).
    voice = VoiceGate(bus)

    anchor = None if config.has_cortex else AnchorVoice(bus, remember, now=config.now)

    cockpit = CockpitBridge(bus, path=config.cockpit_sock) if config.cockpit_sock else None
    mesh = MeshBridge(config.node_id, bus, config.mesh_link) if config.mesh_link is not None else None
    clock = Clock(bus, now=config.now, tick_seconds=config.tick_seconds, morning_hour=config.morning_hour)

    # The storage limb (Charter 28a): silent densify under pressure, a notice only when almost
    # full. Built only when there is a real on-disk state dir; in-memory test graphs skip it.
    groundskeeper = Groundskeeper(config.state, bus, remember.snapshot) if config.state is not None else None

    # The distilled memory (Charter 22/22a): a bus collector buffers the day's life-shape and
    # the nightly ritual folds it into the GIST `.ddn`. Built only with a real on-disk state dir.
    gist = (GistCollector(bus, GistStore(Path(config.state) / "memory.ddn"),
                          tz=os.environ.get("HOMIE_TZ"))
            if config.state is not None else None)

    # The watch history (owner's call: store everything — titles + all): the full, wipeable
    # record of what he watches, powering the recommendation page. Separate from the title-free
    # GIST. Records media.activity sessions; honors the one-tap screen-private pause.
    watch = (WatchTracker(bus, WatchLog(Path(config.state) / "watch.json"),
                          tz=os.environ.get("HOMIE_TZ"), now_path=Path(config.state) / "now.json")
             if config.state is not None else None)

    # The live morning feed: real HA calendar/to-do/weather → agenda.external, folded by the
    # Personal tile into the briefing. Wired ONLY when the home can answer queries (a real HA
    # client exposes `request`) and at least one entity is configured — otherwise the briefing
    # renders from learned routines + the owner's list alone, exactly as before.
    ha_agenda = None
    if (config.ha_calendars or config.ha_todo_lists or config.ha_weather_entity) and \
            callable(getattr(home, "request", None)):
        ha_agenda = HAAgendaSource(
            bus,
            HAWsQuery(home, calendars=config.ha_calendars, todo_lists=config.ha_todo_lists,
                      weather_entity=config.ha_weather_entity),
            tz=os.environ.get("HOMIE_TZ"),
        )

    return Daemon(bus=bus, remember=remember, consent=consent, confirm=confirm, ledger=ledger, undo=undo, commands=slash_commands, improve=improve, sup=sup, act=act,
                  reconciler=reconciler, reason=reason, voice=voice, anchor=anchor,
                  cockpit=cockpit, mesh=mesh, clock=clock, home=home, perception=perception, ha_agenda=ha_agenda,
                  groundskeeper=groundskeeper, gist=gist, watch=watch, config=config)
