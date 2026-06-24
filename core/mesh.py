"""The mesh — node-transparent bus bridging across the encrypted device colony.

A MeshBridge mirrors selected events between this node's bus and its peers, so a
tile subscribing to `presence.arrived` receives it whether it was published here
or on the perception node. Three invariants:

- **Default-deny** — only allowlisted topics cross the wire (MeshPolicy).
- **Privacy** — raw imagery and faceprints never traverse the mesh, enforced
  fail-closed at the boundary (PrivacyGuard), consistent with SECURITY.md.
- **No loops** — events carry (origin, seq); a node drops its own echoes and any
  frame it has already seen, and republished events are marked by origin so they
  are not re-forwarded.

The transport is abstracted behind `Link`. The encrypted Noise-IK transport and
mDNS discovery are deploy-layer concerns that implement the same interface; this
module is the pure, testable bridging logic (in-memory link in the tests).
"""
from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import asdict, replace
from typing import Awaitable, Callable, Protocol

from core.bus import _compile
from core.tile import Event

log = logging.getLogger("homie.mesh")


class Link(Protocol):
    """A duplex frame channel to the rest of the mesh. A frame is a JSON-safe
    dict: {"event": <event dict>, "origin": <node id>, "seq": <int>}."""

    async def send(self, frame: dict) -> None: ...
    def on_receive(self, handler: Callable[[dict], Awaitable[None]]) -> None: ...


class MeshPolicy:
    """Default-deny allowlist of topic patterns eligible to cross the mesh."""

    DEFAULT = ("presence.**", "motion.**", "occupancy.**", "security.**", "node.**")

    def __init__(self, allow: tuple[str, ...] = DEFAULT) -> None:
        self._patterns = [_compile(p) for p in allow]

    def is_meshed(self, topic: str) -> bool:
        return any(p.match(topic) for p in self._patterns)


class PrivacyGuard:
    """Fail-closed: raw imagery and faceprints never cross the mesh."""

    FORBIDDEN = {"raw", "image", "frame", "vector", "faceprint", "crop"}

    def __init__(self, max_bytes: int = 4096) -> None:
        self.max_bytes = max_bytes

    def permits(self, event: Event) -> bool:
        if self.FORBIDDEN & set(event.topic.split(".")):
            return False
        if self.FORBIDDEN & set(event.payload):
            return False
        # a blob-sized payload is almost certainly imagery sneaking through
        if sum(len(str(v)) for v in event.payload.values()) > self.max_bytes:
            return False
        return True


class MeshBridge:
    def __init__(
        self,
        node_id: str,
        bus,
        link: Link,
        *,
        policy: MeshPolicy | None = None,
        guard: PrivacyGuard | None = None,
        seen_max: int = 4096,
    ) -> None:
        self.node_id = node_id
        self.bus = bus
        self.link = link
        self.policy = policy or MeshPolicy()
        self.guard = guard or PrivacyGuard()
        self._seq = 0
        self._boot = uuid.uuid4().hex  # per-boot nonce: a restart can't collide with old seqs
        self._seen: set[tuple] = set()
        self._seen_order: deque[tuple] = deque(maxlen=seen_max)
        self._sub = None

    async def start(self) -> None:
        self.link.on_receive(self._on_remote)
        self._sub = self.bus.subscribe("**", self._on_local, owner=f"mesh:{self.node_id}")

    async def stop(self) -> None:
        if self._sub is not None:
            self.bus.unsubscribe(self._sub)
            self._sub = None

    async def _on_local(self, event: Event) -> None:
        if event.topic.startswith("node.link"):
            return  # local link diagnostics never cross the (possibly down) link — avoids a loop
        # forward only locally-originated events; never re-forward what we republished
        if event.origin not in (None, self.node_id):
            return
        if not self.policy.is_meshed(event.topic) or not self.guard.permits(event):
            return
        self._seq += 1
        frame = {"event": asdict(event), "origin": self.node_id, "boot": self._boot, "seq": self._seq}
        try:
            await self.link.send(frame)
        except Exception as ex:  # a dropped link is a link fault, not a tile fault
            log.warning("mesh: link send failed (%r); event %s not forwarded", ex, event.topic)
            await self.bus.publish(Event("node.link.down", event.ts, {"node": self.node_id}, source=f"mesh:{self.node_id}"))

    async def _on_remote(self, frame: dict) -> None:
        origin = frame["origin"]
        seq = frame["seq"]
        if origin == self.node_id:
            return  # our own echo
        key = (origin, frame.get("boot"), seq)  # boot nonce prevents post-restart seq collisions
        if key in self._seen:
            return  # already delivered
        self._seen.add(key)
        if len(self._seen_order) == self._seen_order.maxlen:
            self._seen.discard(self._seen_order[0])
        self._seen_order.append(key)

        event = Event(**frame["event"])
        if not self.guard.permits(event):  # belt-and-suspenders at the inbound boundary
            return
        # mark the source so our own _on_local won't bounce it back out
        await self.bus.publish(replace(event, origin=origin))
