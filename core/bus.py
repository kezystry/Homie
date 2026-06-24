"""Event routing and arbitration — the only referee in the system.

Tiles never call each other. They publish and subscribe through the bus, and
when two tiles want the same actuator the bus arbitrates by priority. A durability
log sits behind publish() so events survive reboots; a slow or throwing handler
harms only its own mailbox.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Awaitable, Callable, Iterator

from core.tile import Event

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


# --------------------------------------------------------------------------- #
# Durability
# --------------------------------------------------------------------------- #
class DurabilityLog:
    """Append-only JSON-lines event log. No-op when no path is given."""

    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None
        self._fh = None  # opened lazily on first append, so replay-only use opens nothing

    def append(self, event: Event) -> None:
        if not self.path:
            return
        if not self._fh:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")
        self._fh.write(json.dumps(asdict(event), separators=(",", ":")) + "\n")
        self._fh.flush()

    def replay(self) -> Iterator[Event]:
        if not self.path or not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield Event(**json.loads(line))

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


# --------------------------------------------------------------------------- #
# Bus
# --------------------------------------------------------------------------- #
class Bus:
    def __init__(self, *, log_path: Path | None = None, maxsize: int = 256) -> None:
        self._subs: list[Subscription] = []
        self._maxsize = maxsize
        self._log = DurabilityLog(log_path)

    async def publish(self, event: Event) -> None:
        """Log, then fan out to matching subscribers. Returns once enqueued;
        never raises on subscriber failure or a full mailbox."""
        self._log.append(event)
        for sub in self._subs:
            if not sub.regex.match(event.topic):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                _ = sub.queue.get_nowait()  # drop-oldest, keep newest
                sub.queue.task_done()  # keep unfinished-count consistent for drain()/join()
                sub.queue.put_nowait(event)
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
        self._subs.append(sub)
        return sub

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

    async def _drain(self, sub: Subscription) -> None:
        while True:
            event = await sub.queue.get()
            try:
                await sub.handler(event)
            except Exception:
                sub.faults += 1  # contain the failure; never reach publish/siblings
            finally:
                sub.queue.task_done()

    async def drain(self) -> None:
        """Quiescence helper: return once every enqueued event has been handled.
        Loops to a fixed point in case handlers publish further events."""
        while True:
            pending = [s for s in self._subs if s.queue._unfinished_tasks]  # type: ignore[attr-defined]
            if not pending:
                return
            await asyncio.gather(*(s.queue.join() for s in pending))

    def replay(self) -> Iterator[Event]:
        return self._log.replay()

    async def aclose(self) -> None:
        for sub in list(self._subs):
            self.unsubscribe(sub)
        self._log.close()
