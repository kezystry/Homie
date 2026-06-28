"""HA discovery — naming bulbs into Homie actuators, and round-tripping the act-map.

Proves the part that can get a room wrong: vendor noise is stripped, opaque ids fall back to
the friendly name, two bulbs never collapse to one actuator, the never-touch set is honored,
and the rendered TOML loads back through the real ActMap.load.

Run: python3 -m unittest discover -s tests
"""
import tempfile
import unittest
from pathlib import Path

from core.act import ActMap
from core.ha_discovery import entities_to_actmap, render_act_map, suggest_name


def st(entity_id: str, friendly: str | None = None) -> dict:
    return {"entity_id": entity_id, "attributes": ({"friendly_name": friendly} if friendly else {})}


class NamingTests(unittest.TestCase):
    def test_strips_vendor_prefix(self) -> None:
        self.assertEqual(suggest_name("light.tradfri_living_room"), "light.living_room")
        self.assertEqual(suggest_name("light.dirigera_kitchen"), "light.kitchen")

    def test_plain_entity_kept(self) -> None:
        self.assertEqual(suggest_name("light.hallway"), "light.hallway")

    def test_opaque_id_falls_back_to_friendly_name(self) -> None:
        self.assertEqual(suggest_name("light.0x00158d0001", "Bedroom Lamp"), "light.bedroom_lamp")


class MapTests(unittest.TestCase):
    def test_maps_only_lights_by_default(self) -> None:
        states = [st("light.tradfri_kitchen"), st("switch.tv"), st("sensor.temp")]
        m = entities_to_actmap(states)
        self.assertEqual(m, {"light.kitchen": "light.tradfri_kitchen"})

    def test_collision_never_overwrites(self) -> None:
        # Two different entities that would both name 'light.lamp' must both survive.
        states = [st("light.tradfri_lamp"), st("light.ikea_lamp")]
        m = entities_to_actmap(states)
        self.assertEqual(len(m), 2)
        self.assertEqual(set(m.values()), {"light.tradfri_lamp", "light.ikea_lamp"})

    def test_excludes_never_touch(self) -> None:
        states = [st("light.tradfri_kitchen"), st("light.tradfri_office")]
        m = entities_to_actmap(states, exclude={"light.tradfri_office"})
        self.assertEqual(m, {"light.kitchen": "light.tradfri_kitchen"})

    def test_extra_domains_opt_in(self) -> None:
        states = [st("light.tradfri_kitchen"), st("scene.movie_night")]
        m = entities_to_actmap(states, domains=("light", "scene"))
        self.assertIn("scene.movie_night", m)

    def test_deterministic(self) -> None:
        states = [st("light.b"), st("light.a"), st("light.c")]
        self.assertEqual(entities_to_actmap(states), entities_to_actmap(list(reversed(states))))


class RenderTests(unittest.TestCase):
    def test_rendered_toml_loads_back(self) -> None:
        actuators = {"light.kitchen": "light.tradfri_kitchen",
                     "light.living_room": "light.tradfri_living_room"}
        toml = render_act_map(actuators, never_touch=["lock.front_door"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "act_map.toml"
            p.write_text(toml, "utf-8")
            loaded = ActMap.load(p)
        self.assertEqual(loaded.entity_for("light.kitchen"), "light.tradfri_kitchen")
        self.assertIn("lock.front_door", loaded.never_touch)

    def test_never_touch_target_is_dropped_on_load(self) -> None:
        # A mapped entity that is also never-touch must not be drivable (ActMap drops it).
        toml = render_act_map({"light.x": "light.forbidden"}, never_touch=["light.forbidden"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "act_map.toml"
            p.write_text(toml, "utf-8")
            loaded = ActMap.load(p)
        self.assertIsNone(loaded.entity_for("light.x"))


if __name__ == "__main__":
    unittest.main()
