"""Scenario library — named, deterministic days of normalized perception.

These traces are the substrate for testing the whole graph and for the
`HOMIE_FAKE_PERCEPTION` demo mode (boot the real daemon against a synthetic day).
Each builder returns a list of `Event`s with stable timestamps, so a replay is
bit-identical. Events are already normalized (the form `Perceive` publishes): a
topic, a timestamp, and a small zone/label payload — never raw imagery.

Keep these realistic but tiny; they are read by humans in test failures.
"""
from __future__ import annotations

from datetime import datetime

from core.tile import Event

# A fixed base week so timestamps never depend on the wall clock (deterministic).
_BASE_YEAR, _BASE_MONTH = 2026, 6


def _at(day: int, hour: int, minute: int = 0) -> float:
    return datetime(_BASE_YEAR, _BASE_MONTH, day, hour, minute, 0).timestamp()


def normal_weekday(day: int = 15) -> list[Event]:
    """A routine day: wake in the bedroom, kitchen breakfast, leave, return in the
    evening to the living room, wind down. The household's baseline."""
    return [
        Event("presence.arrived", _at(day, 7, 5), {"zone": "bedroom"}),
        Event("presence.arrived", _at(day, 7, 20), {"zone": "kitchen"}),
        Event("occupancy.changed", _at(day, 7, 50), {"zone": "kitchen", "occupied": True}),
        Event("presence.departed", _at(day, 8, 30), {"zone": "kitchen"}),
        Event("occupancy.changed", _at(day, 8, 31), {"zone": "kitchen", "occupied": False}),
        Event("presence.arrived", _at(day, 18, 10), {"zone": "living"}),
        Event("motion.detected", _at(day, 19, 0), {"zone": "living"}),
        Event("presence.arrived", _at(day, 22, 30), {"zone": "bedroom"}),
        Event("presence.departed", _at(day, 22, 35), {"zone": "living"}),
    ]


def novel_visitor_3am(day: int = 16) -> list[Event]:
    """A normal day with one genuinely unusual event: an unrecognized presence at
    the back door at 3am. Security should alert; nothing else should change."""
    return normal_weekday(day) + [
        Event("presence.unknown", _at(day, 3, 12), {"zone": "back_door"}),
    ]


def holiday_drift(day: int = 17) -> list[Event]:
    """The routine, shifted late (a slow morning). Tests that the model treats a
    drifted-but-plausible day as drift, not alarm — nothing here is novel by zone,
    only by hour."""
    return [
        Event("presence.arrived", _at(day, 10, 30), {"zone": "bedroom"}),
        Event("presence.arrived", _at(day, 11, 15), {"zone": "kitchen"}),
        Event("occupancy.changed", _at(day, 11, 40), {"zone": "kitchen", "occupied": True}),
        Event("presence.arrived", _at(day, 14, 0), {"zone": "living"}),
        Event("motion.detected", _at(day, 20, 30), {"zone": "living"}),
        Event("presence.arrived", _at(day, 23, 45), {"zone": "bedroom"}),
    ]


def sensor_flap_storm(day: int = 18, *, count: int = 60) -> list[Event]:
    """A flapping sensor: many motion events in one zone in quick succession. Tests
    the graph stays sane under a burst (backpressure, coalescing) — none of it is a
    security event, just noise."""
    return [
        Event("motion.detected", _at(day, 14, 0) + i, {"zone": "hallway", "seq": i})
        for i in range(count)
    ]


#: name -> zero-arg builder, for HOMIE_FAKE_PERCEPTION and tests.
SCENARIOS = {
    "normal_weekday": normal_weekday,
    "novel_visitor_3am": novel_visitor_3am,
    "holiday_drift": holiday_drift,
    "sensor_flap_storm": sensor_flap_storm,
}


def build(name: str) -> list[Event]:
    """Build a named scenario trace, or raise KeyError listing the known names."""
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}; known: {sorted(SCENARIOS)}")
    return SCENARIOS[name]()
