"""HomeAssistantClient tests — the real HomeClient, exercised with NO live HA.

Three layers, all offline:
  * the pure mappers (command -> service call; HA state_changed -> canonical value);
  * THE invariant: a command Homie drives and the echo HA sends back reduce to the SAME
    canonical value, so the friction loop suppresses the echo instead of misreading it;
  * the client driven by an in-memory fake connection: handshake, dispatch, drive,
    and reconnect-after-auth-failure.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest

from core.canonical import ha_canonical
from core.ha import HomeAssistantClient, command_to_call, state_event_to_value


class _Clk:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def _state_changed(entity_id, state, **attrs):
    return {"id": 1, "type": "event", "event": {"event_type": "state_changed",
            "data": {"entity_id": entity_id,
                     "new_state": {"state": state, "attributes": attrs}}}}


class CommandToCallTests(unittest.TestCase):
    def test_on_with_brightness_pct(self):
        domain, service, data = command_to_call("light.living_room", {"state": "on", "brightness_pct": 40})
        self.assertEqual((domain, service), ("light", "turn_on"))
        self.assertEqual(data, {"brightness": 102})  # 40% -> 102/255

    def test_off(self):
        domain, service, data = command_to_call("light.kitchen", {"state": "off"})
        self.assertEqual((domain, service), ("light", "turn_off"))
        self.assertEqual(data, {})

    def test_bare_on_string(self):
        self.assertEqual(command_to_call("switch.fan", "on"), ("switch", "turn_on", {}))

    def test_colour_temp_kelvin_maps_to_mired(self):
        _, service, data = command_to_call("light.bedroom", {"state": "on", "color_temp_kelvin": 4000})
        self.assertEqual(service, "turn_on")
        self.assertEqual(data, {"color_temp": 250})  # round(1e6/4000)

    def test_domain_taken_from_entity(self):
        domain, _, _ = command_to_call("switch.coffee", {"state": "off"})
        self.assertEqual(domain, "switch")


class StateEventTests(unittest.TestCase):
    def test_typical_light_event(self):
        mapped = state_event_to_value(
            {"entity_id": "light.kitchen", "new_state": {"state": "on", "attributes": {"brightness": 102}}})
        self.assertIsNotNone(mapped)
        entity_id, value = mapped
        self.assertEqual(entity_id, "light.kitchen")
        self.assertEqual(ha_canonical(value), ha_canonical({"state": "on", "brightness_pct": 40}))

    def test_entity_removed_is_none(self):
        self.assertIsNone(state_event_to_value({"entity_id": "light.x", "new_state": None}))

    def test_missing_entity_is_none(self):
        self.assertIsNone(state_event_to_value({"new_state": {"state": "on", "attributes": {}}}))


class RoundTripInvariantTests(unittest.TestCase):
    """The load-bearing guarantee: drive(command) then HA echoes it -> both canonicalize
    equal, so CommandLog.take_echo matches and the StateReconciler suppresses the echo."""

    def _echo_for(self, command):
        # Mimic what HA echoes after applying our service call.
        domain, service, data = command_to_call("light.living_room", command)
        if service == "turn_off":
            return _state_changed("light.living_room", "off")["event"]["data"]
        attrs = {}
        if "brightness" in data:
            attrs["brightness"] = data["brightness"]
        if "color_temp" in data:
            attrs["color_temp"] = data["color_temp"]
        return _state_changed("light.living_room", "on", **attrs)["event"]["data"]

    def test_on_off_and_brightness_roundtrip(self):
        for command in ({"state": "on", "brightness_pct": 40},
                        {"state": "off"},
                        {"state": "on"},
                        {"state": "on", "color_temp_kelvin": 4000}):
            with self.subTest(command=command):
                _, value = state_event_to_value(self._echo_for(command))
                self.assertEqual(ha_canonical(command), ha_canonical(value))


class FakeConn:
    """In-memory HAConnection: delivers a scripted list of inbound messages, then parks
    (so the receive loop blocks instead of spinning). Records everything sent."""

    def __init__(self, inbound, sent, *, auto_result=True, fail_service=False, auto_pong=True):
        self._q = asyncio.Queue()
        for m in inbound:
            self._q.put_nowait(m)
        self.sent = sent
        self.closed = False
        self._auto_result = auto_result
        self._fail_service = fail_service
        self._auto_pong = auto_pong

    async def connect(self):
        pass

    async def send(self, message):
        self.sent.append(message)
        # Mirror a real HA: ack a call_service with a result, answer a ping with a pong.
        t = message.get("type")
        if t == "call_service" and self._auto_result:
            self._q.put_nowait({"id": message["id"], "type": "result", "success": not self._fail_service})
        elif t == "ping" and self._auto_pong:
            self._q.put_nowait({"id": message["id"], "type": "pong"})

    async def recv(self):
        item = await self._q.get()  # blocks (parks) when empty — no busy loop
        if item is _CLOSED:
            raise ConnectionError("connection closed")
        return item

    async def close(self):
        self.closed = True
        self._q.put_nowait(_CLOSED)  # unblock a parked recv() so the loop can react


_CLOSED = object()

_HANDSHAKE = [{"type": "auth_required"}, {"type": "auth_ok"}, {"id": 1, "type": "result", "success": True}]


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_dispatch_and_drive(self):
        sent = []
        inbound = _HANDSHAKE + [_state_changed("light.kitchen", "on", brightness=102)]
        received = []
        got_event = asyncio.Event()

        async def handler(entity_id, value):
            received.append((entity_id, value))
            got_event.set()

        client = HomeAssistantClient(lambda: FakeConn(inbound, sent), "TOKEN", backoff_min=0.01)
        client.on_state_change(handler)
        await client.start()
        await asyncio.wait_for(client.connected.wait(), 1.0)
        await asyncio.wait_for(got_event.wait(), 1.0)

        # auth used the token; subscribe was sent
        self.assertEqual(sent[0], {"type": "auth", "access_token": "TOKEN"})
        self.assertEqual(sent[1]["type"], "subscribe_events")
        self.assertEqual(sent[1]["event_type"], "state_changed")
        # the state change reached the handler, canonicalized
        self.assertEqual(received[0][0], "light.kitchen")
        self.assertEqual(ha_canonical(received[0][1]), ha_canonical({"state": "on", "brightness_pct": 40}))

        # a drive becomes a call_service AND waits for HA's result (returns on success)
        await asyncio.wait_for(client.drive("light.living_room", {"state": "on", "brightness_pct": 40}), 1.0)
        call = next(m for m in sent if m.get("type") == "call_service")
        self.assertEqual(call["domain"], "light")
        self.assertEqual(call["service"], "turn_on")
        self.assertEqual(call["service_data"], {"brightness": 102})
        self.assertEqual(call["target"], {"entity_id": "light.living_room"})
        self.assertGreater(call["id"], sent[1]["id"])  # strictly increasing id
        await client.stop()

    async def test_drive_raises_on_ha_rejection(self):
        # NEW-1: HA returns result.success == false -> drive must RAISE (Act emits failed),
        # never silently succeed.
        sent = []
        client = HomeAssistantClient(
            lambda: FakeConn(_HANDSHAKE, sent, fail_service=True), "TOKEN", backoff_min=0.01)
        await client.start()
        await asyncio.wait_for(client.connected.wait(), 1.0)
        with self.assertRaises(RuntimeError):
            await asyncio.wait_for(client.drive("light.kitchen", {"state": "on"}), 1.0)
        await client.stop()

    async def test_drive_times_out_when_no_result(self):
        # NEW-1: if HA never answers, drive raises rather than hanging forever.
        sent = []
        client = HomeAssistantClient(
            lambda: FakeConn(_HANDSHAKE, sent, auto_result=False), "TOKEN",
            backoff_min=0.01, result_timeout=0.05, heartbeat_interval=0)
        await client.start()
        await asyncio.wait_for(client.connected.wait(), 1.0)
        with self.assertRaises(ConnectionError):
            await client.drive("light.kitchen", {"state": "on"})
        await client.stop()

    async def test_drive_without_connection_raises(self):
        client = HomeAssistantClient(lambda: FakeConn([], []), "TOKEN")
        with self.assertRaises(ConnectionError):
            await client.drive("light.kitchen", {"state": "on"})

    async def test_reconnects_after_auth_failure(self):
        sent = []
        bad = [{"type": "auth_required"}, {"type": "auth_invalid"}]
        conns = [FakeConn(bad, sent), FakeConn(_HANDSHAKE, sent)]

        client = HomeAssistantClient(
            lambda: conns.pop(0) if conns else FakeConn([], sent), "TOKEN",
            backoff_min=0.01, backoff_max=0.02)
        await client.start()
        # First connection auth-fails and is closed; the second authenticates.
        await asyncio.wait_for(client.connected.wait(), 1.0)
        self.assertEqual(conns, [])  # both scripted connections consumed
        await client.stop()

    async def test_heartbeat_pings_and_pong_keeps_alive(self):
        # NEW-2: the client sends its own ping; a pong keeps it from going stale.
        clk = _Clk()

        async def sleep(s):
            clk.t += s
            await asyncio.sleep(0)

        sent = []
        client = HomeAssistantClient(
            lambda: FakeConn(_HANDSHAKE, sent), "TOKEN",
            heartbeat_interval=30.0, heartbeat_timeout=70.0, sleep=sleep, now=clk)
        await client.start()
        await asyncio.wait_for(client.connected.wait(), 1.0)
        for _ in range(100):  # let the heartbeat tick
            await asyncio.sleep(0)
            if any(m.get("type") == "ping" for m in sent):
                break
        self.assertTrue(any(m.get("type") == "ping" for m in sent))
        self.assertTrue(client.connected.is_set())  # pong kept it alive
        await client.stop()

    async def test_heartbeat_reconnects_on_silence(self):
        # NEW-2: a half-open socket sends nothing (not even a pong); the heartbeat must
        # notice the silence and force a reconnect.
        clk = _Clk()

        async def sleep(s):
            clk.t += s
            await asyncio.sleep(0)

        sent = []
        silent = FakeConn(_HANDSHAKE, sent, auto_pong=False)
        good = FakeConn(_HANDSHAKE, sent)
        conns = [silent, good]
        client = HomeAssistantClient(
            lambda: conns.pop(0) if conns else FakeConn([], sent), "TOKEN",
            heartbeat_interval=30.0, heartbeat_timeout=70.0,
            backoff_min=0.01, backoff_max=0.01, sleep=sleep, now=clk)
        await client.start()
        for _ in range(500):
            await asyncio.sleep(0)
            if silent.closed and not conns:  # stale socket closed, second conn taken
                break
        self.assertTrue(silent.closed)
        self.assertEqual(conns, [])  # reconnected onto the good connection
        await client.stop()


if __name__ == "__main__":
    unittest.main()
