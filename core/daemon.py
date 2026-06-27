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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from core.act import Act, ActMap, CommandLog
from core.anchor_voice import AnchorVoice
from core.bus import Bus
from core.canonical import ha_canonical
from core.cockpit_bridge import CockpitBridge
from core.consent import Consent
from core.mesh import Link, MeshBridge
from core.reason import LLMClient, NullLLMClient, Reason
from core.reconcile import StateReconciler
from core.remember import Remember
from core.ritual import consolidate
from core.tile import Supervisor

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
    compact_interval: float = 3600.0   # how often the housekeep loop ticks
    ritual_interval: float = 86400.0   # nightly consolidation cadence
    llm: LLMClient | None = None       # a real client => the reasoning cortex is present
    cockpit_sock: str | None = None    # None = no cockpit bridge
    mesh_link: Link | None = None      # None = loopback (single node, no serialization)
    node_id: str = "homie"
    housekeep: bool = True             # run the periodic compaction/ritual task
    now: Callable[[], float] = time.time

    @property
    def has_cortex(self) -> bool:
        return self.llm is not None


class Daemon:
    """The assembled organism. `start()` wires every subscription in the one correct
    order (Remember LAST); `stop()` tears it down; `run_forever()` parks until the
    service is stopped. Tests inspect `.bus`, `.remember`, `.sup`, etc. directly."""

    def __init__(self, *, bus, remember, consent, sup, act, reconciler, reason,
                 anchor, cockpit, mesh, home, perception, config: DaemonConfig) -> None:
        self.bus = bus
        self.remember = remember
        self.consent = consent
        self.sup = sup
        self.act = act
        self.reconciler = reconciler
        self.reason = reason
        self.anchor = anchor          # None when a real cortex owns chat
        self.cockpit = cockpit        # None when no socket configured
        self.mesh = mesh              # None = loopback (single node)
        self.home = home
        self.perception = perception
        self.config = config
        self._tasks: list[asyncio.Task] = []
        self.started = False

    async def start(self) -> None:
        # Rebuild the pattern of life from the durability log before any live wiring
        # (pure read, no subscription).
        self.remember.bootstrap(self.bus)

        # --- the one correct wiring order ------------------------------------- #
        await self.consent.start()
        await self.act.start()
        self.reconciler.attach(self.home)     # human state-changes -> friction
        await self.sup.start_all()            # tiles subscribe (evaluators)
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
        log.info("homie: daemon up (cortex=%s, tiles=%s)", self.config.has_cortex, self.sup.status())

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
                                      supervisor=self.sup, now=now)
                    last_ritual = now
                else:
                    await self.bus.maybe_compact(self.remember.snapshot)
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
        await self.reason.stop()
        if self.anchor is not None:
            await self.anchor.stop()
        if self.cockpit is not None:
            await self.cockpit.stop()
        if self.mesh is not None:
            await self.mesh.stop()
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
    sup = Supervisor(tiles_dir, bus, remember=remember, consent=consent, state_root=config.state)

    # The act path: one CommandLog shared by Act (writer) and the reconciler
    # (matcher) so Homie's own echoes are suppressed and only human changes become
    # friction. ha_canonical normalizes values to the home's echo form.
    commands = CommandLog(canonical=ha_canonical)
    act = Act(bus, home, commands, act_map)
    reconciler = StateReconciler(sup, commands, act_map.reverse, on_echo=act.confirm)

    # Reason is ALWAYS wired; a real client means the cortex is present, else the
    # null client makes the proposer a tested no-op. The anchor chat floor is wired
    # ONLY when there is no cortex, so chat is answered exactly once.
    reason = Reason(bus, config.llm or NullLLMClient(), sup, remember)
    anchor = None if config.has_cortex else AnchorVoice(bus, remember, now=config.now)

    cockpit = CockpitBridge(bus, path=config.cockpit_sock) if config.cockpit_sock else None
    mesh = MeshBridge(config.node_id, bus, config.mesh_link) if config.mesh_link is not None else None

    return Daemon(bus=bus, remember=remember, consent=consent, sup=sup, act=act,
                  reconciler=reconciler, reason=reason, anchor=anchor, cockpit=cockpit,
                  mesh=mesh, home=home, perception=perception, config=config)
