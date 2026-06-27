"""HomeAssistantClient — the real `HomeClient`, binding Homie's act path to Home Assistant.

The owner adopted Home Assistant as the device/IO layer (DIRIGERA hub + Tradfri bulbs,
scenes, routines, phone, presence, voice). HA is the hands; Homie is the learning brain
above it. This module is the seam between them: it implements the `HomeClient` Protocol
(`drive` + `on_state_change`) that `core/act.py` and `core/reconcile.py` already inject
everywhere, so wiring it in changes nothing else in the graph (the keystone invariant).

Two design decisions, made for this codebase:

  * **WebSocket for both directions.** HA's WebSocket API is the native PUSH channel —
    `subscribe_events` delivers `state_changed` the instant a human flips a switch, which
    is exactly what the friction loop needs (REST has no push; polling would add latency
    and miss intermediate states). The same socket carries `call_service` to actuate, so
    one connection gives ordered, low-latency echoes relative to the ~5s CommandLog window.
  * **One canonical form, never a private one.** Inbound HA state is reduced through the
    SAME `core/canonical.ha_canonical` that `CommandLog` uses, so a command Homie drove and
    the echo HA sends back collapse to one comparable value — the echo is suppressed instead
    of being misread as a human reversal. The adapter MUST NOT invent its own normal form.

The actual byte-level transport (the asyncio WebSocket) lives behind the `HAConnection`
seam so the client's protocol logic — auth handshake, subscribe, dispatch, reconnect,
the command↔service mapping — is exercised in tests with an in-memory fake, no live HA.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable, Protocol

from core.canonical import Canon, ha_canonical

log = logging.getLogger("homie.ha")

StateHandler = Callable[[str, object], Awaitable[None]]


# --------------------------------------------------------------------------- #
# Pure mappers (no I/O — the heart of the offline tests)
# --------------------------------------------------------------------------- #
def command_to_call(entity_id: str, command: object) -> tuple[str, str, dict]:
    """Map a structured Homie command to an HA (domain, service, service_data) call.

    The command is first reduced through `ha_canonical`, so there is ONE interpretation
    of "on / off / brightness / colour-temp" shared with the echo-matching path. HA's
    `light.turn_on` accepts `brightness` (0-255) and `color_temp` (mired) directly, which
    is exactly the Canon's native units — no second conversion, no drift."""
    domain = entity_id.split(".", 1)[0]
    c = ha_canonical(command)
    if c.state == "off":
        return domain, "turn_off", {}
    data: dict[str, object] = {}
    if c.brightness is not None:
        data["brightness"] = c.brightness
    if c.mired is not None:
        data["color_temp"] = c.mired
    return domain, "turn_on", data


def state_event_to_value(event_data: dict) -> tuple[str, dict] | None:
    """Map an HA `state_changed` event's `data` to (entity_id, value) where `value` is a
    dict `ha_canonical` understands. Returns None for an entity removal / malformed event
    (no new_state) — there is no state to represent. Reads exactly the attributes the
    canonicalizer consumes, so the two cannot drift."""
    entity_id = event_data.get("entity_id")
    new_state = event_data.get("new_state")
    if not entity_id or not isinstance(new_state, dict):
        return None
    attrs = new_state.get("attributes") or {}
    value = {
        "state": new_state.get("state"),
        "brightness": attrs.get("brightness"),
        "color_temp": attrs.get("color_temp"),  # HA legacy mired
        "color_temp_kelvin": attrs.get("color_temp_kelvin"),
    }
    return entity_id, value


# --------------------------------------------------------------------------- #
# The transport seam
# --------------------------------------------------------------------------- #
class HAConnection(Protocol):
    """A JSON-message connection to HA. The real impl wraps a WebSocket; tests fake it.
    `recv` raises (ConnectionError / EOF) when the connection drops."""

    async def connect(self) -> None: ...
    async def send(self, message: dict) -> None: ...
    async def recv(self) -> dict: ...
    async def close(self) -> None: ...


class WebSocketHAConnection:
    """The production `HAConnection`: HA's WebSocket API carrying JSON messages. Imports
    the stdlib WS client lazily so the rest of the module (and its tests) need no socket."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ws = None

    async def connect(self) -> None:
        from core.ws import WSClient  # lazy: keep the pure path importable without I/O
        self._ws = await WSClient.connect(self._url)

    async def send(self, message: dict) -> None:
        if self._ws is None:
            raise ConnectionError("HA WebSocket not connected")
        await self._ws.send_text(json.dumps(message))

    async def recv(self) -> dict:
        if self._ws is None:
            raise ConnectionError("HA WebSocket not connected")
        return json.loads(await self._ws.recv_text())

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
class HomeAssistantClient:
    """Implements `HomeClient`. A background loop keeps one authenticated, subscribed
    connection alive (reconnecting with backoff), dispatching every `state_changed` to the
    registered handler; `drive` issues `call_service` on that live connection.

    `connect_factory()` returns a fresh `HAConnection` each attempt (so a reconnect gets a
    clean socket). On reconnect we deliberately do NOT replay current state: HA's
    `subscribe_events` only delivers FUTURE changes, so there is no snapshot to misread as a
    human action — the friction loop stays clean across a blip."""

    def __init__(
        self,
        connect_factory: Callable[[], HAConnection],
        token: str,
        *,
        backoff_min: float = 1.0,
        backoff_max: float = 30.0,
        result_timeout: float = 10.0,
        heartbeat_interval: float = 30.0,
        heartbeat_timeout: float = 70.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._connect_factory = connect_factory
        self._token = token
        self._backoff_min = backoff_min
        self._backoff_max = backoff_max
        self._result_timeout = result_timeout      # how long drive() waits for HA's result
        self._heartbeat_interval = heartbeat_interval  # ping cadence; 0 disables the heartbeat
        self._heartbeat_timeout = heartbeat_timeout    # silence beyond this => force reconnect
        self._sleep = sleep
        self._now = now
        self._handler: StateHandler | None = None
        self._conn: HAConnection | None = None
        self._id = 1  # HA requires a strictly increasing message id after auth
        self._send_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future] = {}  # call_service id -> result future (NEW-1)
        self._last_recv = 0.0  # monotonic stamp of the last inbound message (liveness, NEW-2)
        self._task: asyncio.Task | None = None
        self._closing = False
        self.connected = asyncio.Event()  # set after auth+subscribe; tests await it

    # --- HomeClient Protocol -------------------------------------------------- #
    def on_state_change(self, handler: StateHandler) -> None:
        self._handler = handler

    async def drive(self, entity_id: str, command: object) -> None:
        """Issue a `call_service` and WAIT for HA's result (NEW-1). Raises if disconnected,
        if HA does not answer in time, or if HA reports failure — Act catches that and emits
        `actuator.failed`. Without this, an HA-level rejection (entity unavailable, bad
        service) would look like success: the command sits in the CommandLog, no echo ever
        matches, and Homie believes the home changed when it did not."""
        conn = self._conn
        if conn is None:
            raise ConnectionError("Home Assistant is not connected")
        domain, service, service_data = command_to_call(entity_id, command)
        fut = asyncio.get_running_loop().create_future()
        async with self._send_lock:
            self._id += 1
            msg_id = self._id
            self._pending[msg_id] = fut
            try:
                await conn.send({
                    "id": msg_id,
                    "type": "call_service",
                    "domain": domain,
                    "service": service,
                    "service_data": service_data,
                    "target": {"entity_id": entity_id},
                })
            except Exception:
                self._pending.pop(msg_id, None)
                raise
        try:
            success = await asyncio.wait_for(fut, self._result_timeout)
        except asyncio.TimeoutError as ex:
            self._pending.pop(msg_id, None)
            raise ConnectionError(f"Home Assistant did not confirm {service} on {entity_id}") from ex
        if not success:
            raise RuntimeError(f"Home Assistant rejected {service} on {entity_id}")

    # --- lifecycle (called by the Daemon if present) -------------------------- #
    async def start(self) -> None:
        if self._task is None:
            self._closing = False
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._fail_pending(ConnectionError("Home Assistant client stopped"))
        self.connected.clear()

    # --- the connection loop -------------------------------------------------- #
    async def _run(self) -> None:
        delay = self._backoff_min
        while not self._closing:
            conn: HAConnection | None = None
            hb: asyncio.Task | None = None
            try:
                conn = self._connect_factory()
                await conn.connect()
                await self._handshake(conn)
                self._conn = conn
                self._last_recv = self._now()
                self.connected.set()
                delay = self._backoff_min  # a clean connect resets the backoff
                if self._heartbeat_interval:
                    hb = asyncio.ensure_future(self._heartbeat(conn))
                while not self._closing:
                    message = await conn.recv()
                    self._last_recv = self._now()  # liveness: any inbound traffic counts
                    await self._handle(message)
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                log.warning("HA connection lost (%r); reconnecting in %.1fs", ex, delay)
            finally:
                if hb is not None:
                    hb.cancel()
                    try:
                        await hb
                    except (asyncio.CancelledError, Exception):
                        pass
                self._conn = None
                self.connected.clear()
                # A dropped connection can never deliver outstanding results — fail them now
                # so a drive() in flight raises instead of hanging until its timeout (NEW-1).
                self._fail_pending(ConnectionError("Home Assistant connection lost"))
                if conn is not None:
                    try:
                        await conn.close()
                    except Exception:
                        pass
            if self._closing:
                break
            await self._sleep(delay)
            delay = min(delay * 2, self._backoff_max)

    async def _heartbeat(self, conn: HAConnection) -> None:
        """Liveness (NEW-2): a half-open TCP (router reboot, NAT timeout, HA host sleep)
        sends no FIN/RST, so `recv()` would block forever and the reconnect machinery never
        runs. Send HA's app-level `ping` on a cadence; if NOTHING arrives (not even our own
        pong) within `heartbeat_timeout`, close the socket to force a reconnect."""
        while not self._closing:
            await self._sleep(self._heartbeat_interval)
            if self._closing:
                return
            if self._now() - self._last_recv > self._heartbeat_timeout:
                log.warning("HA silent for >%.0fs; forcing reconnect", self._heartbeat_timeout)
                try:
                    await conn.close()  # unblocks the parked recv() -> the loop reconnects
                except Exception:
                    pass
                return
            try:
                async with self._send_lock:
                    self._id += 1
                    await conn.send({"id": self._id, "type": "ping"})
            except Exception:
                return  # the send failed; the recv loop will see the drop and reconnect

    def _fail_pending(self, exc: Exception) -> None:
        pending, self._pending = self._pending, {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(exc)

    async def _handshake(self, conn: HAConnection) -> None:
        """HA's auth + subscribe handshake: auth_required → auth → auth_ok, then
        subscribe_events(state_changed) → result(success)."""
        hello = await conn.recv()
        if hello.get("type") != "auth_required":
            raise ConnectionError(f"unexpected HA greeting: {hello.get('type')!r}")
        await conn.send({"type": "auth", "access_token": self._token})
        reply = await conn.recv()
        if reply.get("type") != "auth_ok":
            raise ConnectionError(f"HA auth failed: {reply.get('type')!r}")
        self._id = 1
        await conn.send({"id": self._id, "type": "subscribe_events", "event_type": "state_changed"})
        result = await conn.recv()
        if not (result.get("type") == "result" and result.get("success")):
            raise ConnectionError("HA subscribe_events failed")

    async def _handle(self, message: dict) -> None:
        mtype = message.get("type")
        if mtype == "result":  # the ack for a call_service (NEW-1) — resolve the waiter
            fut = self._pending.pop(message.get("id"), None)
            if fut is not None and not fut.done():
                fut.set_result(bool(message.get("success")))
            return
        if mtype == "pong":
            return  # liveness only — _last_recv was already bumped by the recv loop
        if mtype != "event":
            return
        event = message.get("event") or {}
        if event.get("event_type") != "state_changed":
            return
        mapped = state_event_to_value(event.get("data") or {})
        if mapped is None or self._handler is None:
            return
        entity_id, value = mapped
        await self._handler(entity_id, value)
