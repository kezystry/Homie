"""AnchorVoice — the floor of aliveness: a typed line never vanishes.

Pins the M0 contract: with no LLM, every `chat.message` yields a `chat.reply`;
pattern-of-life questions are answered from Remember; reasoning-shaped questions
get an honest deferral, never silence.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest
from datetime import datetime

from core.anchor_voice import AnchorVoice
from core.bus import Bus
from core.remember import Remember
from core.tile import Event


def at(hour: int, day: int = 20) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


FIXED_NOW = at(20, 22)  # a stable "now" so 'last seen' phrasing is deterministic


async def _replies_for(texts, *, seed=None, now=lambda: FIXED_NOW):
    """Drive AnchorVoice over a fresh bus; return the chat.reply texts collected."""
    bus = Bus()
    remember = Remember()
    if seed:
        seed(remember)
    voice = AnchorVoice(bus, remember, now=now)
    await voice.start()
    replies: list[str] = []
    bus.subscribe("chat.reply", lambda e: replies.append(e.payload.get("text")))
    for t in texts:
        await bus.publish(Event("chat.message", FIXED_NOW, {"text": t}, source="cockpit"))
    await bus.drain()
    await voice.stop()
    await bus.aclose()
    return replies


def _seed_back_door(remember: Remember) -> None:
    for day in range(15, 22):  # a week of arrivals at the back door around 18:00
        remember.model.observe(Event("presence.arrived", at(18, day), {"zone": "back_door"}))
        remember.model.observe(Event("presence.arrived", at(8, day), {"zone": "kitchen"}))


class AnchorVoiceTests(unittest.TestCase):
    def test_chat_always_replies_without_llm(self) -> None:
        """The acceptance test: status, pattern, and reasoning-shaped lines all
        get a reply within the drain — never silence."""
        texts = [
            "are the doors locked?",          # device-state — anchor can't know, must still reply
            "when does the back door usually open?",  # pattern-of-life
            "why did the lights flicker and what should I do about the wiring?",  # reasoning-shaped
        ]
        replies = asyncio.run(_replies_for(texts, seed=_seed_back_door))
        self.assertEqual(len(replies), 3)
        self.assertTrue(all(isinstance(r, str) and r.strip() for r in replies))

    def test_blank_text_is_not_answered(self) -> None:
        replies = asyncio.run(_replies_for(["   ", ""]))
        self.assertEqual(replies, [])

    def test_pattern_question_answered_from_memory(self) -> None:
        replies = asyncio.run(_replies_for(
            ["When does the back door usually open?"], seed=_seed_back_door))
        self.assertEqual(len(replies), 1)
        self.assertIn("back door", replies[0])
        self.assertIn("18:00", replies[0])  # the learned busiest hour

    def test_status_question_summarizes_patterns(self) -> None:
        replies = asyncio.run(_replies_for(["what do you know?"], seed=_seed_back_door))
        self.assertEqual(len(replies), 1)
        # mentions it is the anchor and references the zones it has learned
        self.assertIn("anchor", replies[0].lower())
        self.assertTrue("back_door" in replies[0] or "kitchen" in replies[0])

    def test_reasoning_question_defers_honestly(self) -> None:
        replies = asyncio.run(_replies_for(
            ["Plan my whole week around the weather forecast."], seed=_seed_back_door))
        self.assertEqual(len(replies), 1)
        self.assertIn("anchor", replies[0].lower())

    def test_unknown_zone_falls_back_not_silent(self) -> None:
        # asks about a zone we've never seen — must still reply (deferral/status), never empty
        replies = asyncio.run(_replies_for(
            ["when does the garage usually open?"], seed=_seed_back_door))
        self.assertEqual(len(replies), 1)
        self.assertTrue(replies[0].strip())


if __name__ == "__main__":
    unittest.main()
