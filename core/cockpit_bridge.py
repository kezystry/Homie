"""The cockpit bridge — the only external attachment point to the in-process bus.

The Layer 2 cockpit (a separate `homie` process, possibly over SSH) cannot touch
the daemon's in-memory Bus directly. This module exposes a NARROW, capability-
scoped window onto it over a local unix-domain socket, so the cockpit can watch
events and chat with the brain — and do nothing else.

Decided by the cockpit council (see the bring-up plan); the invariants here are
load-bearing, not cosmetic:

- **Local only.** A filesystem unix-domain socket, mode 0600, owned by the homie
  service user. NEVER a TCP port — the cockpit is a console/SSH-local view, not a
  network service. Remote access is a WireGuard concern, layered above, not here.
- **Read + chat, nothing else.** Outbound: an allowlist of topics the cockpit may
  *see* (status, presence, security, the brain's speech). Inbound: the cockpit may
  publish EXACTLY ONE topic — `chat.message` (the user's typed line). It can never
  publish `actuator.requested`, `confirm.*`, or anything that drives the home. The
  allowlists are enforced server-side; a malicious client cannot widen them.
- **Privacy still fences the boundary.** PrivacyGuard gates every event crossing
  the socket in both directions — so even though local rendering of camera frames
  is fine, a frame can never *ride this socket* (frames reach the cockpit straight
  from the local device, never via the bus).
- **No origin spoofing.** Inbound events are rebuilt from (topic, payload) only;
  source is forced to "cockpit" and the timestamp is stamped here, so a client
  cannot forge origin/id/ttl to confuse the mesh or the durability log.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path

from core.bus import _compile
from core.mesh import PrivacyGuard
from core.tile import Event

log = logging.getLogger("homie.cockpit")

# The default socket lives under the service's runtime dir. systemd's
# RuntimeDirectory=homie creates /run/homie owned by the service user; we fall
# back to it via $HOMIE_RUNTIME or this constant.
DEFAULT_SOCKET = "/run/homie/cockpit.sock"


class CockpitPolicy:
    """Capability allowlists for the cockpit window. Default-deny in both
    directions: only matching topics may cross."""

    # What the cockpit may SEE. Disjoint top-level prefixes so an event matches at
    # most one pattern (no duplicate forwarding). Deliberately excludes raw
    # perception internals and anything actuator-driving except the *done* echo.
    OUTBOUND = (
        "interface.**",   # the brain's speech / things said to the human
        "chat.**",        # chat replies routed back
        "security.**",    # alerts the owner should see
        "presence.**",    # who/what is around (no pixels — guarded)
        "motion.**",
        "occupancy.**",
        "node.**",        # mesh/node up-down for a status line
        "actuator.done",  # confirmation that an act happened (not the request)
        "tile.**",        # tile status/health
        "wake.**",        # cortex wake telemetry: cadence/asleep-fraction (M3, read-only)
    )
    # What the cockpit may PUBLISH. Exactly the user's chat line — nothing that
    # drives an actuator, confirms a gesture, or forges perception.
    INBOUND = ("chat.message",)

    def __init__(self, outbound: tuple[str, ...] = OUTBOUND, inbound: tuple[str, ...] = INBOUND) -> None:
        self.outbound = tuple(outbound)
        self.inbound = tuple(inbound)
        self._out = [_compile(p) for p in outbound]
        self._in = [_compile(p) for p in inbound]

    def may_send(self, topic: str) -> bool:
        """May an event on `topic` be forwarded OUT to the cockpit?"""
        return any(p.match(topic) for p in self._out)

    def may_receive(self, topic: str) -> bool:
        """May the cockpit publish an event on `topic` IN to the bus?"""
        return any(p.match(topic) for p in self._in)


def encode(event: Event) -> bytes:
    """An Event as one newline-delimited JSON frame for the socket."""
    return (json.dumps(asdict(event), separators=(",", ":")) + "\n").encode("utf-8")


def decode_inbound(line: bytes | str) -> Event | None:
    """Parse a client line into a SANITIZED inbound Event, or None if malformed.

    Only `topic` (str) and `payload` (dict) are honored; source is forced to
    "cockpit" and the timestamp is stamped server-side. A client cannot set
    source/id/origin/ttl — no origin spoofing."""
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    topic = obj.get("topic")
    if not isinstance(topic, str) or not topic:
        return None
    payload = obj.get("payload", {})
    if not isinstance(payload, dict):
        return None
    return Event(topic=topic, ts=time.time(), payload=payload, source="cockpit")


class CockpitBridge:
    """Serves the cockpit window on a local unix socket. Start it after the Bus is
    up (it subscribes to the outbound allowlist); stop it on shutdown."""

    def __init__(
        self,
        bus,
        *,
        path: str | Path = DEFAULT_SOCKET,
        policy: CockpitPolicy | None = None,
        guard: PrivacyGuard | None = None,
    ) -> None:
        self.bus = bus
        self.path = Path(path)
        self.policy = policy or CockpitPolicy()
        self.guard = guard or PrivacyGuard()
        self._server: asyncio.AbstractServer | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._subs: list = []

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Remove a stale socket from a previous run so bind() succeeds.
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
        # Create the socket 0600 from the start (umask), then chmod belt-and-braces.
        old = os.umask(0o177)
        try:
            self._server = await asyncio.start_unix_server(self._handle_client, path=str(self.path))
        finally:
            os.umask(old)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        # One subscription per outbound pattern; each fans out to all clients.
        self._subs = [self.bus.subscribe(p, self._forward, owner="cockpit") for p in self.policy.outbound]
        log.info("cockpit bridge listening on %s", self.path)

    async def stop(self) -> None:
        for sub in self._subs:
            self.bus.unsubscribe(sub)
        self._subs = []
        for w in list(self._clients):
            self._close_writer(w)
        self._clients.clear()
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass

    # -- outbound: bus event -> connected cockpits ----------------------------- #
    async def _forward(self, event: Event) -> None:
        # Privacy fences the boundary even for a local socket: a frame never rides
        # this channel. (may_send already excludes the obvious topics; this is the
        # fail-closed backstop on payload contents and size.)
        if not self.guard.permits(event):
            return
        data = encode(event)
        for w in list(self._clients):
            try:
                w.write(data)
            except Exception:
                self._drop(w)

    # -- inbound: cockpit line -> bus ------------------------------------------ #
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._clients.add(writer)
        try:
            async for raw in reader:  # newline-delimited frames
                line = raw.strip()
                if not line:
                    continue
                event = decode_inbound(line)
                if event is None:
                    continue
                # Default-deny: only the chat topic may be injected, and the guard
                # still applies. Anything else is silently dropped.
                if not self.policy.may_receive(event.topic):
                    log.warning("cockpit: refused inbound topic %r", event.topic)
                    continue
                if not self.guard.permits(event):
                    continue
                await self.bus.publish(event)
        except Exception as ex:
            log.debug("cockpit client error: %r", ex)
        finally:
            self._drop(writer)

    # -- writer bookkeeping ---------------------------------------------------- #
    def _drop(self, writer: asyncio.StreamWriter) -> None:
        self._clients.discard(writer)
        self._close_writer(writer)

    @staticmethod
    def _close_writer(writer: asyncio.StreamWriter) -> None:
        try:
            writer.close()
        except Exception:
            pass
