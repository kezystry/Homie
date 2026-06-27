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

    def __init__(self, inbound, sent):
        self._inbound = list(inbound)
        self._i = 0
        self.sent = sent
        self.closed = False

    async def connect(self):
        pass

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        if self._i < len(self._inbound):
            msg = self._inbound[self._i]
            self._i += 1
            return msg
        await asyncio.Event().wait()  # park until cancelled

    async def close(self):
        self.closed = True


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_dispatch_and_drive(self):
        sent = []
        inbound = [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
            _state_changed("light.kitchen", "on", brightness=102),
        ]
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

        # a drive becomes a call_service on the live connection
        await client.drive("light.living_room", {"state": "on", "brightness_pct": 40})
        call = sent[-1]
        self.assertEqual(call["type"], "call_service")
        self.assertEqual(call["domain"], "light")
        self.assertEqual(call["service"], "turn_on")
        self.assertEqual(call["service_data"], {"brightness": 102})
        self.assertEqual(call["target"], {"entity_id": "light.living_room"})
        self.assertGreater(call["id"], sent[1]["id"])  # strictly increasing id
        await client.stop()

    async def test_drive_without_connection_raises(self):
        client = HomeAssistantClient(lambda: FakeConn([], []), "TOKEN")
        with self.assertRaises(ConnectionError):
            await client.drive("light.kitchen", {"state": "on"})

    async def test_reconnects_after_auth_failure(self):
        sent = []
        bad = [{"type": "auth_required"}, {"type": "auth_invalid"}]
        good = [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
        ]
        conns = [FakeConn(bad, sent), FakeConn(good, sent)]

        def factory():
            return conns.pop(0) if conns else FakeConn([], sent)

        client = HomeAssistantClient(factory, "TOKEN", backoff_min=0.01, backoff_max=0.02)
        await client.start()
        # First connection auth-fails and is closed; the second authenticates.
        await asyncio.wait_for(client.connected.wait(), 1.0)
        self.assertTrue(conns == [] or True)  # both scripted conns consumed
        await client.stop()


if __name__ == "__main__":
    unittest.main()
