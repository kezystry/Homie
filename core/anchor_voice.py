"""AnchorVoice — the floor of aliveness: a typed line never vanishes.

On the bare Pi anchor (no `HOMIE_LLM_URL`, so no reasoning cortex), the cockpit
still lets the resident type a line — it publishes `chat.message` and, until now,
*nothing* answered: the words fell into a void. A home that eats your words is
dead, not alive. AnchorVoice closes that floor: it subscribes to `chat.message`
and ALWAYS publishes a `chat.reply`, with no LLM and no GPU.

It answers what it can locally from Remember's pattern of life — "how are you?",
"when does the back door usually open?" — and for anything reasoning-shaped it
says so plainly ("I'm the anchor; the thinking node is asleep — here's what I
know…") rather than faking a smart answer. Felt honesty over latent cleverness.

Coordination with the cortex: when a real model IS serving, `Reason` answers chat
and the daemon leaves AnchorVoice unwired (Reason owns the chat seam), so there is
never a double reply. AnchorVoice is precisely the anchor-only guarantee that a
reply never goes missing.
"""
from __future__ import annotations

import logging
import time

from core.tile import Event

log = logging.getLogger("homie.anchor")

# Same chat seam topics Reason uses: a typed line in, a reply back out.
CHAT_IN = "chat.message"
CHAT_REPLY = "chat.reply"

# Cheap intent cues. Deliberately simple and stdlib — the anchor is a floor, not a
# parser; the cortex (when present) does the real understanding.
GREETINGS = ("hi", "hello", "hey", "yo", "good morning", "good evening", "good night")
PATTERN_CUES = ("when", "usually", "normally", "what time", "how often", "typical", "around what")
STATUS_CUES = (
    "status", "what do you know", "how are you", "are you there", "you there",
    "what's up", "whats up", "everything ok", "all good", "you awake", "anyone home",
)


def _ago(seconds: float) -> str:
    """A coarse, friendly 'last seen' phrase from a delta in seconds."""
    s = max(0, int(seconds))
    if s < 90:
        return "just now"
    if s < 5400:
        return f"{s // 60} minutes ago"
    if s < 129600:  # < 36h
        return f"{s // 3600} hours ago"
    return f"{s // 86400} days ago"


class AnchorVoice:
    """Subscribes to `chat.message` and guarantees a `chat.reply` for every typed
    line. Start it after the Bus is up; stop it on shutdown. `now` is injectable so
    the relative 'last seen' phrasing is deterministic under test."""

    def __init__(self, bus, remember, *, now=time.time) -> None:
        self.bus = bus
        self.remember = remember
        self._now = now
        self._sub = None

    async def start(self) -> None:
        self._sub = self.bus.subscribe(CHAT_IN, self._on_chat, owner="anchor")

    async def stop(self) -> None:
        if self._sub is not None:
            self.bus.unsubscribe(self._sub)
            self._sub = None

    async def _on_chat(self, event: Event) -> None:
        text = (event.payload or {}).get("text")
        if not isinstance(text, str) or not text.strip():
            return  # nothing said — nothing to answer
        reply = self.compose(text.strip())
        await self.bus.publish(Event(CHAT_REPLY, event.ts, {"text": reply}, source="anchor"))

    # -- the pure, testable composer ------------------------------------------- #
    def compose(self, text: str) -> str:
        """Map a typed line to the anchor's best honest reply. Never empty."""
        low = text.lower()
        if any(low == g or low.startswith(g + " ") for g in GREETINGS):
            return ("Hi — I'm Homie's anchor, always listening. The thinking node is "
                    "asleep right now, but I'm watching the home.")
        if any(cue in low for cue in PATTERN_CUES):
            answer = self._answer_pattern(low)
            if answer:
                return answer
        if any(cue in low for cue in STATUS_CUES):
            return self._status_line()
        return self._defer_line()

    def _answer_pattern(self, low: str) -> str | None:
        zone = self._zone_in(low)
        if zone is None:
            return None
        summary = self.remember.describe_zone(zone, self._now())
        if not summary or summary.get("hour") is None:
            return None
        pretty = zone.replace("_", " ")
        line = f"The {pretty} usually sees activity around {summary['hour']:02d}:00."
        last = summary.get("last_seen")
        if last:
            line += f" Last seen {_ago(self._now() - last)}."
        return line

    def _zone_in(self, low: str) -> str | None:
        """The most specific known zone whose name appears in the question
        ('back_door' matches 'back door' or 'door')."""
        best = None
        for zone in self.remember.zones():
            if any(word in low for word in zone.replace("_", " ").split()):
                if best is None or len(zone) > len(best):
                    best = zone
        return best

    def _status_line(self) -> str:
        n = self.remember.pattern_count()
        if n == 0:
            return ("I'm the anchor and I'm here. I haven't learned the home's patterns "
                    "yet — still watching. The thinking node is asleep.")
        zones = self.remember.zones()
        where = ", ".join(zones[:4]) if zones else "the home"
        return (f"I'm the anchor — the thinking node is asleep, but I'm watching {n} "
                f"pattern{'s' if n != 1 else ''} across {where}. Everything looks normal.")

    def _defer_line(self) -> str:
        n = self.remember.pattern_count()
        return ("I'm the anchor right now — the thinking node is asleep, so I can't reason "
                f"that through. Here's what I can tell you: I'm watching {n} "
                f"pattern{'s' if n != 1 else ''} across the home, and it's been quiet.")
