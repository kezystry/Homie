"""Event routing and arbitration — the only referee in the system.

Tiles never call each other. They publish and subscribe through the bus, and
when two tiles want the same actuator the bus arbitrates by priority. A durability
log sits behind publish() so events survive reboots; a slow or throwing handler
harms only its own mailbox.

The durability log is bounded by generation-based compaction: a snapshot of the
derived state (the pattern of life) is committed atomically, the live log is rotated
to a generation-numbered segment, and covered segments are deleted. The snapshot's
generation makes recovery unambiguous — boot folds segments newer than the snapshot
(crash before commit ⇒ no loss) and discards those it already covers (crash before
delete ⇒ no double-count).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Awaitable, Callable, Iterator

from core.tile import Event

log = logging.getLogger("homie.bus")

Handler = Callable[[Event], Awaitable[None]]


# --------------------------------------------------------------------------- #
# Arbitration
# --------------------------------------------------------------------------- #
class Priority(IntEnum):
    AMBIENT = 0
    CONVENIENCE = 1
    AUTOMATION = 2
    SECURITY = 3
    SAFETY = 4


@dataclass(frozen=True)
class Request:
    actuator: str
    value: object
    priority: Priority
    tile: str
    at: float  # recency tiebreak; later wins


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #
def _compile(pattern: str) -> re.Pattern:
    """Segment-aware glob → regex. `*` = one segment, `**` = one-or-more."""
    parts = []
    for seg in pattern.split("."):
        if seg == "**":
            parts.append(r"[^.]+(?:\.[^.]+)*")
        elif seg == "*":
            parts.append(r"[^.]+")
        else:
            parts.append(re.escape(seg))
    return re.compile("^" + r"\.".join(parts) + "$")


@dataclass
class Subscription:
    pattern: str
    regex: re.Pattern
    handler: Handler
    owner: str | None
    queue: asyncio.Queue
    task: asyncio.Task | None = None
    dropped: int = 0  # backpressure counter
    faults: int = 0  # fault-isolation counter
    inflight: int = 0  # enqueued-but-not-yet-handled (drives drain(), no private attrs)
    respawns: int = 0  # drain-task respawns (supervision)


# --------------------------------------------------------------------------- #
# Durability + compaction
# --------------------------------------------------------------------------- #
class DurabilityLog:
    """Append-only JSON-lines event log with generation-based compaction.

    Files (all beside `path`, given `path = .../events.jsonl`):
      events.jsonl              the live tail (appended to)
      events.snapshot.json      {"gen": G, "model": <derived state>} — committed atomically
      events.seg.<G>.jsonl      a rotated segment, transient (deleted once covered)

    No-op when no path is given (in-memory/ephemeral mode for tests).
    """

    def __init__(self, path: Path | None, *, flush_every: int = 1) -> None:
        self.path = Path(path) if path else None
        self._fh = None
        self._flush_every = max(1, flush_every)
        self._pending = 0

    # -- paths --
    @property
    def _snapshot_path(self) -> Path | None:
        return self.path.parent / (self.path.stem + ".snapshot.json") if self.path else None

    def _seg_path(self, gen: int) -> Path:
        return self.path.parent / f"{self.path.stem}.seg.{gen}.jsonl"

    def _segments(self) -> list[tuple[int, Path]]:
        if not self.path:
            return []
        out = []
        for f in self.path.parent.glob(f"{self.path.stem}.seg.*.jsonl"):
            try:
                out.append((int(f.stem.rsplit(".seg.", 1)[1]), f))
            except (ValueError, IndexError):
                continue
        return sorted(out)

    # -- append / flush --
    def append(self, event: Event) -> None:
        if not self.path:
            return
        if not self._fh:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")
        self._fh.write(json.dumps(asdict(event), separators=(",", ":")) + "\n")
        self._pending += 1
        if self._pending >= self._flush_every:
            self._fh.flush()
            self._pending = 0

    def flush(self) -> None:
        if self._fh:
            self._fh.flush()
            self._pending = 0

    def close(self) -> None:
        if self._fh:
            self._fh.flush()
            os.fsync(self._fh.fileno())  # durable at clean shutdown
            self._fh.close()
            self._fh = None

    # -- read --
    def replay(self) -> Iterator[Event]:
        """Yield the live log only (the tail). Raw-consumer contract, unchanged."""
        if not self.path or not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield Event(**json.loads(line))

    def _snapshot_gen(self) -> int:
        p = self._snapshot_path
        if not p or not p.exists():
            return 0
        try:
            return int(json.loads(p.read_text("utf-8")).get("gen", 0))
        except Exception:
            return 0

    def load_snapshot(self) -> dict | None:
        """Return the committed snapshot's derived state, or None if absent/corrupt
        (corrupt ⇒ None so the caller falls back to a full fold of the log)."""
        p = self._snapshot_path
        if not p or not p.exists():
            return None
        try:
            return json.loads(p.read_text("utf-8")).get("model")
        except Exception:
            return None

    def pending_events(self) -> Iterator[Event]:
        """Yield every event NOT yet covered by the snapshot: uncovered segments
        (gen > snapshot gen, in order) then the live tail. Covered segments
        (gen <= snapshot gen) are deleted as GC. This is what boot folds on top
        of the restored snapshot."""
        gen = self._snapshot_gen()
        for seg_gen, f in self._segments():
            if seg_gen <= gen:
                f.unlink(missing_ok=True)  # already in the snapshot — discard
            else:
                with f.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            yield Event(**json.loads(line))
        yield from self.replay()

    # -- compaction --
    def compact(self, model_snapshot: dict) -> None:
        """Persist `model_snapshot` (which must already reflect every logged event)
        and rotate the live log away. Crash-safe by ordering: rotate ⇒ commit
        snapshot atomically ⇒ delete segment."""
        if not self.path:
            return
        self.close()  # flush + fsync + close the live handle
        gen = self._snapshot_gen() + 1
        seg = self._seg_path(gen)
        if self.path.exists():
            os.replace(self.path, seg)  # boundary: live log becomes segment <gen>
        snap_path = self._snapshot_path
        tmp = snap_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"gen": gen, "model": model_snapshot}, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, snap_path)  # commit point (atomic)
        dirfd = os.open(str(self.path.parent), os.O_RDONLY)
        try:
            os.fsync(dirfd)  # make the rename durable
        finally:
            os.close(dirfd)
        if seg.exists():
            seg.unlink()  # now covered by the snapshot — discard


# --------------------------------------------------------------------------- #
# Bus
# --------------------------------------------------------------------------- #
class Bus:
    def __init__(
        self,
        *,
        log_path: Path | None = None,
        maxsize: int = 256,
        flush_every: int = 1,
        compact_threshold: int = 0,
    ) -> None:
        self._subs: list[Subscription] = []
        self._maxsize = maxsize
        self._log = DurabilityLog(log_path, flush_every=flush_every)
        self._compact_threshold = compact_threshold  # 0 = never auto-compact
        self._appends_since_compact = 0
        self._max_respawns = 5  # drain-task respawn cap before tearing the sub down

    async def publish(self, event: Event) -> None:
        """Log, then fan out to matching subscribers. Returns once enqueued;
        never raises on subscriber failure or a full mailbox."""
        self._log.append(event)
        self._appends_since_compact += 1
        for sub in self._subs:
            if not sub.regex.match(event.topic):
                continue
            try:
                sub.queue.put_nowait(event)
                sub.inflight += 1
            except asyncio.QueueFull:
                _ = sub.queue.get_nowait()  # drop-oldest, keep newest
                sub.inflight -= 1  # the dropped item will never be handled
                sub.queue.put_nowait(event)
                sub.inflight += 1
                sub.dropped += 1

    def subscribe(self, pattern: str, handler: Handler, *, owner: str | None = None) -> Subscription:
        """Register a handler. Starts a drain task (requires a running loop)."""
        sub = Subscription(
            pattern=pattern,
            regex=_compile(pattern),
            handler=handler,
            owner=owner,
            queue=asyncio.Queue(maxsize=self._maxsize),
        )
        sub.task = asyncio.ensure_future(self._drain(sub))
        sub.task.add_done_callback(lambda t, s=sub: self._on_drain_done(s, t))
        self._subs.append(sub)
        return sub

    def _on_drain_done(self, sub: Subscription, task: asyncio.Task) -> None:
        """A drain task should run forever. If it exits abnormally, respawn it
        (capped) so a dead consumer never silently swallows a tile's events."""
        if task.cancelled() or sub not in self._subs:
            return  # intentional teardown (unsubscribe / drop_owner)
        exc = task.exception()
        sub.respawns += 1
        log.error("bus: drain task for %r exited (%r); respawn %d", sub.owner or sub.pattern, exc, sub.respawns)
        if sub.respawns > self._max_respawns:
            log.error("bus: drain task for %r exceeded respawn cap — tearing down", sub.owner or sub.pattern)
            self.unsubscribe(sub)
            return
        sub.task = asyncio.ensure_future(self._drain(sub))
        sub.task.add_done_callback(lambda t, s=sub: self._on_drain_done(s, t))

    def unsubscribe(self, sub: Subscription) -> None:
        if sub.task:
            sub.task.cancel()
        if sub in self._subs:
            self._subs.remove(sub)

    def drop_owner(self, owner: str) -> None:
        """Tear down every subscription for an owner — used on quarantine/reload."""
        for sub in [s for s in self._subs if s.owner == owner]:
            self.unsubscribe(sub)

    async def arbitrate(self, actuator: str, requests: list[Request]) -> Request | None:
        """Resolve competing requests for one actuator: highest priority wins,
        latest `at` breaks ties. The one point of authority."""
        candidates = [r for r in requests if r.actuator == actuator]
        if not candidates:
            return None
        return max(candidates, key=lambda r: (r.priority, r.at))

    # -- durability passthroughs --
    def replay(self) -> Iterator[Event]:
        return self._log.replay()

    def load_snapshot(self) -> dict | None:
        return self._log.load_snapshot()

    def pending_events(self) -> Iterator[Event]:
        return self._log.pending_events()

    def compact(self, model_snapshot: dict) -> None:
        """Persist a snapshot and rotate the log. The caller guarantees the
        snapshot reflects every logged event (e.g. a live Remember.snapshot())."""
        self._log.compact(model_snapshot)
        self._appends_since_compact = 0

    async def maybe_compact(self, snapshot_provider: Callable[[], dict]) -> bool:
        """Compact iff the append-count threshold is crossed. Explicit and
        synchronous (the daemon calls it) so tests stay deterministic. Returns
        whether it compacted."""
        if not self._compact_threshold or self._appends_since_compact < self._compact_threshold:
            return False
        self.compact(snapshot_provider())
        return True

    async def _drain(self, sub: Subscription) -> None:
        while True:
            event = await sub.queue.get()
            try:
                await sub.handler(event)
            except Exception:
                sub.faults += 1  # contain the failure; never reach publish/siblings
            finally:
                sub.inflight -= 1

    async def drain(self) -> None:
        """Quiescence helper: return once every enqueued event has been handled,
        to a fixed point (handlers may publish more, or park on each other). Uses
        the explicit inflight counter — no private Queue internals."""
        while any(s.inflight for s in self._subs):
            await asyncio.sleep(0)

    async def aclose(self) -> None:
        for sub in list(self._subs):
            self.unsubscribe(sub)
        self._log.close()
