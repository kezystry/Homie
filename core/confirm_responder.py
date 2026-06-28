"""ConfirmResponder — makes the Consent gate answerable from plain chat, SAFELY.

`core/consent.py` opens a `confirm.requested` and waits for a matching `confirm.response`,
failing safe to "no" on timeout. Nothing produced that response (audit N10), so every confirm
died — blocking the undo/autonomy path. This is the producer; an external audit then found two
ways the first cut could approve the WRONG thing, fixed here:

  * **One question at a time, oldest first, echoed back (A-1).** Concurrent confirms are queued
    FIFO, not overwritten. A yes/no answers the FRONT (the one shown first), and we echo *what*
    was approved (`chat.reply`), so a "buy X?" then "sell Y?" can never resolve as "Y approved,
    X denied" with the owner none the wiser. A money/GUARDED gate must never mis-map an answer.
  * **A deliberate answer, briefly (A-2).** The WHOLE message must be a yes/no (an exact phrase
    from the sets — not just a first word), within a short window. So "stop lighting the kitchen"
    no longer answers an open money confirm, and a stale question expires rather than catching a
    later unrelated yes/no.

Chat in, not a new control channel: the owner answers with words he already sends; this trusted
core component does the translation. The cockpit's input stays `chat.message`-only. Event-clocked
(uses event timestamps), so it is deterministic.
"""
from __future__ import annotations

import logging

from core.tile import Event

log = logging.getLogger("homie.confirm")

CONFIRM_REQUESTED = "confirm.requested"
CONFIRM_RESPONSE = "confirm.response"
CHAT_MESSAGE = "chat.message"
CHAT_REPLY = "chat.reply"
ANSWER_WINDOW_S = 90.0  # a yes/no answers a confirm only within this long of the question

# WHOLE-message phrases only — a safety gate needs a deliberate answer, never a first-word match
# (so "stop lighting the kitchen" can't resolve a money confirm via the word "stop").
_YES = {"yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure", "do it", "yes please",
        "go ahead", "go for it", "please do", "confirm", "approve", "approved", "ja", "mach"}
_NO = {"no", "n", "nope", "nah", "don't", "dont", "cancel", "stop", "stop it", "no thanks",
       "decline", "deny", "reject", "nein", "ne"}


def parse_yes_no(text: str) -> bool | None:
    """True/False only if the WHOLE message is a clear yes/no phrase; else None. No first-word
    matching — a confirmation that can authorise spending must not be answered by accident."""
    t = " ".join("".join(ch for ch in (text or "").lower() if ch.isalnum() or ch in " '").split())
    if t in _YES:
        return True
    if t in _NO:
        return False
    return None


class ConfirmResponder:
    """Wire in `build_daemon`; `start()` after Consent. Holds a FIFO of open confirmations and
    emits `confirm.response` (plus a `chat.reply` echo of what was decided) when the owner
    answers the front one in chat."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self._open: list[tuple[str, str, float]] = []   # FIFO of (id, prompt, ts), oldest first
        self._subs: list = []

    async def start(self) -> None:
        self._subs = [
            self.bus.subscribe(CONFIRM_REQUESTED, self._on_request, owner="confirm"),
            self.bus.subscribe(CHAT_MESSAGE, self._on_chat, owner="confirm"),
        ]

    async def stop(self) -> None:
        for sub in self._subs:
            self.bus.unsubscribe(sub)
        self._subs = []

    async def _on_request(self, event: Event) -> None:
        cid = event.payload.get("id")
        if cid and not any(c[0] == cid for c in self._open):
            self._open.append((cid, str(event.payload.get("prompt", "")), event.ts))

    def _drop_stale(self, now: float) -> None:
        """Expire questions older than the window from the FRONT — they fail safe in Consent
        (timeout → no) rather than catching a later, unrelated yes/no."""
        while self._open and now - self._open[0][2] > ANSWER_WINDOW_S:
            self._open.pop(0)

    async def _on_chat(self, event: Event) -> None:
        self._drop_stale(event.ts)
        if not self._open:
            return
        answer = parse_yes_no(event.payload.get("text", ""))
        if answer is None:                               # not a deliberate yes/no → plain chat
            return
        cid, prompt, _ = self._open.pop(0)               # answer the OLDEST open confirm
        await self.bus.publish(Event(CONFIRM_RESPONSE, event.ts,
                                     {"id": cid, "yes": answer}, source="confirm"))
        verb = "Approved" if answer else "Declined"
        echo = f"{verb}: {prompt}" if prompt else f"{verb}."
        await self.bus.publish(Event(CHAT_REPLY, event.ts, {"text": echo}, source="confirm"))
        log.info("confirm: %s -> %s (%s)", cid, "yes" if answer else "no", prompt)
