"""The Agenda substrate + the offline route-sequencer + the capped Briefing render.

Proves the organizing system the design council specified: one typed list, deterministic
dedup (fact beats routine, no false merges across deadlines), an honest offline order that
never reorders a fixed appointment, and a briefing that is capped in code with lossy
overflow and honest-empty — the anti-nag discipline, on the morning surface.

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timedelta, timezone

from core import briefing
from core.agenda import (
    AT, BY, ALLDAY, FLOAT, AgendaItem, AgendaView, Place, Temporal, from_beliefs,
    from_ha_calendar, from_ha_todo, weather_clause,
)
from core.route import RoutePlan, sequence, zone_cost

UTC = timezone.utc
DAY = datetime(2026, 3, 10, tzinfo=UTC)               # a Tuesday


def t(hour: int, minute: int = 0, day_off: int = 0) -> float:
    return (DAY + timedelta(days=day_off, hours=hour, minutes=minute)).timestamp()


def item(kind, when, title, *, zone=None, conf=1.0, sid="") -> AgendaItem:
    place = Place(zone, zone) if zone else None
    return AgendaItem(kind=kind, when=when, title=title, place=place, confidence=conf,
                      source="test", source_id=sid or title)


class TemporalTests(unittest.TestCase):
    def test_exactly_one_anchor(self) -> None:
        self.assertEqual(Temporal.at(t(9)).kind, AT)
        self.assertEqual(Temporal.by(t(17)).anchor, t(17))
        self.assertIsNone(Temporal.floating().anchor)
        with self.assertRaises(ValueError):
            Temporal.at(t(10), t(9))                  # end before start

    def test_sort_order_overdue_then_timeline_then_float(self) -> None:
        now = t(12)
        overdue = item(BY := "due", Temporal.by(t(9)), "bill")      # deadline passed
        soon = item("event", Temporal.at(t(14)), "dentist")
        allday = item("event", Temporal.allday(t(0)), "birthday")
        floaty = item("due", Temporal.floating(), "someday")
        ordered = sorted([floaty, allday, soon, overdue], key=lambda it: it.sort_key(now))
        self.assertEqual([i.title for i in ordered], ["bill", "dentist", "birthday", "someday"])


class ViewSliceTests(unittest.TestCase):
    def test_today_and_yesterday(self) -> None:
        v = AgendaView([
            item("event", Temporal.at(t(9)), "today-event"),
            item("event", Temporal.at(t(9, 0, -1)), "yesterday-event"),
            item("due", Temporal.floating(), "anytime"),
        ], tz="UTC")
        self.assertEqual({i.title for i in v.today(t(12))}, {"today-event", "anytime"})
        self.assertEqual([i.title for i in v.yesterday(t(12))], ["yesterday-event"])

    def test_due_horizon(self) -> None:
        v = AgendaView([
            item("due", Temporal.by(t(15)), "due-today"),
            item("due", Temporal.by(t(15, 0, 3)), "due-friday"),
        ], tz="UTC")
        titles = [i.title for i in v.due(t(9), horizon_s=86400.0)]
        self.assertEqual(titles, ["due-today"])       # friday is beyond a 1-day horizon


class DedupTests(unittest.TestCase):
    def test_identity_replace_not_duplicate(self) -> None:
        a = item("event", Temporal.at(t(9)), "Standup", sid="x")
        b = item("event", Temporal.at(t(10)), "Standup moved", sid="x")  # same source_id
        v = AgendaView([a, b], tz="UTC")
        self.assertEqual(len(v.all(t(8))), 1)
        self.assertEqual(v.all(t(8))[0].title, "Standup moved")

    def test_fact_beats_routine_same_slot(self) -> None:
        fact = item("event", Temporal.at(t(8)), "Kitchen", conf=1.0, sid="cal")
        guess = item("routine", Temporal.at(t(8)), "Kitchen", conf=0.7, sid="bel")
        v = AgendaView([guess, fact], tz="UTC")
        kept = v.all(t(7))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].kind, "event")       # the hard fact hides the learned guess

    def test_no_merge_across_different_deadlines(self) -> None:
        a = item("due", Temporal.by(t(12)), "Pay rent", sid="a")
        b = item("due", Temporal.by(t(12, 0, 5)), "Pay rent", sid="b")  # 5 days later
        v = AgendaView([a, b], tz="UTC")
        self.assertEqual(len(v.all(t(9))), 2)         # two real deadlines, not one


class RouteTests(unittest.TestCase):
    def test_honest_empty_under_two_places(self) -> None:
        plan = sequence([item("event", Temporal.at(t(9)), "solo", zone="a")], t(8))
        self.assertIsNone(plan.clause)

    def test_fixed_spine_in_time_order_flexible_inserted(self) -> None:
        zones = {"north": 3, "mid": 2, "south": 1}
        items = [
            item("event", Temporal.at(t(14)), "dentist", zone="north"),
            item("due", Temporal.floating(), "bakery", zone="mid"),
            item("due", Temporal.floating(), "post office", zone="south"),
        ]
        plan = sequence(items, t(8), cost=zone_cost(zones))
        self.assertIsNotNone(plan.clause)
        # the fixed dentist stays put; flexible errands order toward it along the loop
        self.assertEqual(plan.stops[-1].title, "dentist")
        self.assertIn("dentist", plan.clause)

    def test_overlapping_fixed_is_flagged_not_crammed(self) -> None:
        items = [
            item("event", Temporal.at(t(14), t(15)), "dentist", zone="a"),
            item("event", Temporal.at(t(14, 30), t(15, 30)), "meeting", zone="b"),
        ]
        plan = sequence(items, t(8))
        self.assertTrue(plan.conflicts)
        self.assertIn("overlap", plan.conflicts[0])


class BriefingTests(unittest.TestCase):
    def _view(self, items):
        return AgendaView(items, tz="UTC")

    def test_timeline_capped_with_lossy_overflow(self) -> None:
        items = [item("event", Temporal.at(t(8 + i)), f"e{i}") for i in range(5)]
        b = briefing.build(self._view(items), t(7), tz=UTC)
        self.assertEqual(len(b.timeline), briefing.TIMELINE_MAX)
        self.assertEqual(b.timeline_overflow, 2)
        self.assertIn("(+2 more)", b.render_text())

    def test_due_capped(self) -> None:
        items = [item("due", Temporal.by(t(12 + i)), f"bill{i}") for i in range(4)]
        b = briefing.build(self._view(items), t(7), tz=UTC)
        self.assertEqual(len(b.due), briefing.DUE_MAX)
        self.assertEqual(b.due_overflow, 2)

    def test_quiet_day_is_honest_and_silent(self) -> None:
        b = briefing.build(self._view([]), t(7), tz=UTC)
        self.assertTrue(b.is_quiet)
        self.assertIn("Quiet day", b.render_text())
        self.assertIsNone(b.speak_line())             # nothing on -> Homie stays silent

    def test_weather_is_woven_never_a_headline(self) -> None:
        items = [item("event", Temporal.at(t(9)), "dentist")]
        b = briefing.build(self._view(items), t(7), weather="rain from 11", tz=UTC)
        text = b.render_text()
        self.assertIn("rain from 11", text)
        self.assertNotIn("\nrain from 11", text)      # not its own line — woven into the header

    def test_speak_line_is_single_and_present_on_a_work_day(self) -> None:
        items = [item("event", Temporal.at(t(9)), "dentist"),
                 item("due", Temporal.by(t(12)), "rent")]
        b = briefing.build(self._view(items), t(7), tz=UTC)
        line = b.speak_line()
        self.assertIsNotNone(line)
        self.assertEqual(line.count("\n"), 0)         # one line, never the whole page

    def test_deterministic(self) -> None:
        items = [item("event", Temporal.at(t(9)), "a"), item("due", Temporal.by(t(12)), "b")]
        b1 = briefing.build(self._view(items), t(7), tz=UTC).render_text()
        b2 = briefing.build(self._view(items), t(7), tz=UTC).render_text()
        self.assertEqual(b1, b2)


class AdapterTests(unittest.TestCase):
    def test_ha_calendar_and_todo_map_to_items(self) -> None:
        events = from_ha_calendar([{"start": t(9), "end": t(10), "summary": "Dentist",
                                    "location": "Clinic", "uid": "1", "entity": "calendar.work"}])
        self.assertEqual(events[0].kind, "event")
        self.assertEqual(events[0].place.label, "Clinic")
        todos = from_ha_todo([{"summary": "Pay rent", "due": t(17), "uid": "2", "entity": "todo.home"}])
        self.assertEqual(todos[0].when.kind, BY)

    def test_beliefs_become_routine_items_without_leaking_topic(self) -> None:
        rows = [{"topic": "presence.arrived", "zone": "kitchen", "hour": 8, "prob": 0.9, "firm": True}]
        items = from_beliefs(rows, day_start=t(0))
        self.assertEqual(items[0].kind, "routine")
        self.assertEqual(items[0].confidence, 0.9)
        self.assertNotIn("presence.arrived", items[0].title)

    def test_weather_clause_is_short_or_none(self) -> None:
        self.assertEqual(weather_clause({"rain_onset_hour": 11}), "rain from 11am")
        self.assertIsNone(weather_clause(None))


class RevealTests(unittest.TestCase):
    def test_reveal_signal_from_tag_or_entity(self) -> None:
        from core.agenda import reveal_for
        self.assertEqual(reveal_for("[private] Therapy", "calendar.work"), "sensitive")
        self.assertEqual(reveal_for("Standup", "calendar.private_stuff"), "sensitive")
        self.assertEqual(reveal_for("Standup", "calendar.work"), "household")

    def test_ha_calendar_marks_sensitive(self) -> None:
        items = from_ha_calendar([{"start": t(9), "summary": "[private] Therapy",
                                   "uid": "9", "entity": "calendar.work"}])
        self.assertEqual(items[0].reveal, "sensitive")

    def test_sensitive_item_redacted_on_speech_but_not_on_screen(self) -> None:
        it = AgendaItem(kind="event", when=Temporal.at(t(9)), title="[private] Therapy",
                        place=Place("Clinic", "town"), reveal="sensitive")
        view = AgendaView([it])
        screen = briefing.build(view, t(8), tz=UTC)               # local page
        spoken = briefing.build(view, t(8), tz=UTC, redact=True)  # voice/push
        self.assertTrue(any("Therapy" in s for s in screen.render_lines()))   # full title local
        self.assertIn("a private appointment", spoken.speak_line())           # redacted aloud
        self.assertNotIn("Therapy", spoken.speak_line())

    def test_household_item_unchanged_when_redacting(self) -> None:
        it = AgendaItem(kind="event", when=Temporal.at(t(9)), title="Dentist",
                        place=Place("Clinic", "town"))
        view = AgendaView([it])
        self.assertIn("Dentist", briefing.build(view, t(8), tz=UTC, redact=True).speak_line())


if __name__ == "__main__":
    unittest.main()
