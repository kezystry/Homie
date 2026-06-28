"""Lighting tile tests — the M5 "organism comes alive" loop, no hardware.

Presence after dark lights a room; the bedroom never auto-ons; a reversal teaches
the tile to stay dark; a guest's reversal teaches nothing; vacancy auto-offs after
the window; and a SECURITY decision outranks the tile's AMBIENT light.

Run: python3 -m unittest discover -s tests
"""
import shutil
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from core.act import Act, ActMap, CommandLog
from core.bus import Bus
from core.consent import Consent
from core.tile import ActionRef, Event, FrictionSignal, Supervisor

ROOT = Path(__file__).resolve().parents[1]


def at(hour: int, day: int = 13) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


def collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


class FakeHome:
    def __init__(self) -> None:
        self.driven: list = []

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler


class LightingTests(unittest.IsolatedAsyncioTestCase):
    async def _sup(self, root: Path):
        shutil.copytree(ROOT / "tiles" / "lighting", root / "lighting")
        bus = Bus()
        sup = Supervisor(root, bus)
        await sup.start("lighting")
        acts: list[Event] = []
        bus.subscribe("actuator.requested", collect(acts))
        return bus, sup, acts

    async def test_presence_after_dark_lights_room(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            await bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(len(acts), 1)
            self.assertEqual(acts[0].payload["actuator"], "light.living_room")
            self.assertEqual(acts[0].payload["value"], {"state": "on"})
            self.assertEqual(acts[0].payload["priority"], "ambient")
            await bus.aclose()

    async def test_daytime_does_not_auto_on(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            await bus.publish(Event("presence.arrived", at(12), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(acts, [])
            await bus.aclose()

    async def test_bedroom_never_auto_ons_but_request_works(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            await bus.publish(Event("presence.arrived", at(23), {"zone": "bedroom"}))
            await bus.drain()
            self.assertEqual(acts, [])  # never auto-on, even after dark
            await sup.call_function("light_room", room="bedroom", on=True)
            await bus.drain()
            self.assertEqual(acts[-1].payload["actuator"], "light.bedroom")
            self.assertEqual(acts[-1].payload["value"], {"state": "on"})
            self.assertEqual(acts[-1].payload["priority"], "convenience")
            await bus.aclose()

    async def test_security_only_zone_ignored(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            await bus.publish(Event("presence.arrived", at(21), {"zone": "approach"}))
            await bus.drain()
            self.assertEqual(acts, [])  # no light.approach actuator -> ignored
            await bus.aclose()

    async def test_reversal_suppresses_then_no_auto_on(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            ref = ActionRef("x", "lighting", "light.living_room", {"state": "on"}, at(21))
            await sup.deliver_friction(
                FrictionSignal(kind="reversal", at=at(21), target_tile="lighting",
                               reverses=ref, zone="living", actor="owner")
            )
            await bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(acts, [])  # the lesson stuck — no light at 21:00 in the living room
            await bus.aclose()

    async def test_guest_reversal_does_not_train(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            ref = ActionRef("x", "lighting", "light.living_room", {"state": "on"}, at(21))
            await sup.deliver_friction(
                FrictionSignal(kind="reversal", at=at(21), target_tile="lighting",
                               reverses=ref, zone="living", actor="guest_visitor")
            )
            await bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(len(acts), 1)  # a guest's correction is not a household preference
            await bus.aclose()

    async def test_vacancy_arms_timer_then_fires_off(self) -> None:
        # The N1 fix: vacancy ARMS a Clock timer (timer.set), and when that timer
        # fires the light goes off — even with no further zone events in between.
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            sets: list[Event] = []
            bus.subscribe("timer.set", collect(sets))
            await bus.publish(Event("occupancy.changed", 1000.0, {"zone": "living", "occupied": False}))
            await bus.drain()
            self.assertEqual(acts, [])  # armed, not yet off
            self.assertEqual(len(sets), 1)
            self.assertEqual(sets[0].payload["key"], "lighting.off.living")
            self.assertEqual(sets[0].payload["after"], 600.0)
            # the Clock fires the timer later (here simulated) — no other events needed
            await bus.publish(Event("timer.fired", 1601.0, {"key": "lighting.off.living", "data": {"room": "living"}}))
            await bus.drain()
            self.assertEqual(len(acts), 1)
            self.assertEqual(acts[0].payload["actuator"], "light.living_room")
            self.assertEqual(acts[0].payload["value"], {"state": "off"})
            await bus.aclose()

    async def test_reoccupied_cancels_auto_off(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            cancels: list[Event] = []
            bus.subscribe("timer.cancel", collect(cancels))
            await bus.publish(Event("occupancy.changed", 1000.0, {"zone": "living", "occupied": False}))
            await bus.publish(Event("occupancy.changed", 1100.0, {"zone": "living", "occupied": True}))
            await bus.drain()
            self.assertEqual(len(cancels), 1)  # re-occupancy cancels the pending auto-off
            self.assertEqual(cancels[0].payload["key"], "lighting.off.living")
            # even if a stray timer.fired arrived after the cancel, the room is occupied;
            # but normally the Clock dropped it — assert no off was issued
            self.assertEqual(acts, [])
            await bus.aclose()

    async def test_solar_dusk_gates_auto_on_when_location_set(self) -> None:
        # With HOMIE_LAT/HOMIE_LON set, the dark-gate uses real solar dusk (N4): an
        # arrival at 21:00 local in June (19:00 UTC) at Kiel is still daylight -> no
        # auto-on; at ~midnight local it is dark -> auto-on.
        import os
        from datetime import timezone
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            saved = (os.environ.get("HOMIE_LAT"), os.environ.get("HOMIE_LON"))
            os.environ["HOMIE_LAT"], os.environ["HOMIE_LON"] = "54.32", "10.14"
            try:
                daylight = datetime(2026, 6, 21, 19, 0, 0, tzinfo=timezone.utc).timestamp()
                await bus.publish(Event("presence.arrived", daylight, {"zone": "living"}))
                await bus.drain()
                self.assertEqual(acts, [])  # solar dusk: not dark yet at 21:00 in June
                night = datetime(2026, 6, 21, 22, 0, 0, tzinfo=timezone.utc).timestamp()
                await bus.publish(Event("presence.arrived", night, {"zone": "living"}))
                await bus.drain()
                self.assertEqual(len(acts), 1)  # genuinely dark now -> auto-on
            finally:
                for key, val in zip(("HOMIE_LAT", "HOMIE_LON"), saved):
                    if val is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = val
            await bus.aclose()

    async def _sup_consent(self, root: Path, *, answer: bool):
        """A supervisor with a Consent gate that auto-answers every offer `answer`."""
        shutil.copytree(ROOT / "tiles" / "lighting", root / "lighting")
        bus = Bus()
        consent = Consent(bus, timeout=5.0)
        await consent.start()
        sup = Supervisor(root, bus, consent=consent)
        await sup.start("lighting")
        acts: list[Event] = []
        offers: list[Event] = []
        bus.subscribe("actuator.requested", collect(acts))

        async def auto_answer(e: Event) -> None:
            offers.append(e)
            await bus.publish(Event("confirm.response", e.ts, {"id": e.payload["id"], "yes": answer}))

        bus.subscribe("confirm.requested", auto_answer)
        return bus, sup, acts, offers, consent

    async def test_dusk_offers_first_then_autos_after_yes(self) -> None:
        # Owner's call: the FIRST dusk asks; after yes it's automatic, never asks again.
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts, offers, consent = await self._sup_consent(root, answer=True)
            await bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(len(offers), 1)            # it asked the first time
            self.assertEqual(len(acts), 1)              # ...and lit it on yes
            await bus.publish(Event("presence.arrived", at(21, day=14), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(len(offers), 1)            # the SECOND dusk does not ask again
            self.assertEqual(len(acts), 2)              # ...just lights, automatically
            await consent.stop(); await bus.aclose()

    async def test_dusk_single_decline_offers_again_next_time(self) -> None:
        # A single no (or missed answer) must not permanently disable dusk lighting.
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts, offers, consent = await self._sup_consent(root, answer=False)
            await bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(len(offers), 1)
            self.assertEqual(acts, [])                  # declined → no light
            await bus.publish(Event("presence.arrived", at(21, day=14), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(len(offers), 2)            # still willing to offer again
            await consent.stop(); await bus.aclose()

    async def test_dusk_repeated_decline_settles_and_stops_asking(self) -> None:
        # After MAX_OFFERS declines, it settles on "no" and stops nagging (anti-nag).
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts, offers, consent = await self._sup_consent(root, answer=False)
            for day in (13, 14):
                await bus.publish(Event("presence.arrived", at(21, day=day), {"zone": "living"}))
                await bus.drain()
            self.assertEqual(len(offers), 2)            # asked MAX_OFFERS times
            await bus.publish(Event("presence.arrived", at(21, day=15), {"zone": "living"}))
            await bus.drain()
            self.assertEqual(len(offers), 2)            # ...then never again
            self.assertEqual(acts, [])                  # and never lights
            await consent.stop(); await bus.aclose()

    async def test_security_request_outranks_ambient_light(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup, acts = await self._sup(root)
            home = FakeHome()
            act = Act(bus, home, CommandLog(), ActMap.from_forward({"light.living_room": "light.lr"}), hold_window=1e9)
            await act.start()
            # the tile asks for ambient light...
            await bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
            await bus.drain()
            # ...then a SECURITY decision wants it off on the same bulb
            await bus.publish(Event("actuator.requested", time.time(),
                                    {"actuator": "light.living_room", "value": {"state": "off"},
                                     "tile": "security", "priority": "security"}))
            await bus.drain()
            self.assertEqual(home.driven[-1], ("light.lr", {"state": "off"}))  # security wins arbitration
            await act.stop()
            await bus.aclose()


if __name__ == "__main__":
    unittest.main()
