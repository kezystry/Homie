"""ConfirmResponder — makes the Consent gate answerable from plain chat.

`core/consent.py` opens a `confirm.requested` and waits for a matching `confirm.response`,
failing safe to "no" on timeout. But nothing PRODUCED that response (external audit N10), so
every "are you sure?" silently died — Homie could never actually be told *yes*, which blocks
the whole undo/autonomy path.

This is the producer. It watches for an OPEN confirmation and, when the owner types a clear
yes/no in chat, emits the `confirm.response`. The design choices that keep it safe:

  * **Chat in, not a new control channel.** The owner answers with words he already can send
    (`chat.message`); this trusted core component does the translation. The cockpit's input
    allowlist stays `chat.message`-only — no new way to drive anything.
  * **Only while a confirm is OPEN, and only briefly.** A yes/no is interpreted as an answer
    only when a confirmation is genuinely pending and recent (a window), so ordinary
    conversation is never hijacked into authorising an action.
  * **Resolves exactly one.** It answers the latest open confirm and forgets it; a later yes/no
    is plain chat again. Event-clocked (uses event timestamps), so it is deterministic.
"""
from __future__ import annotations

import logging

from core.tile import Event

log = logging.getLogger("homie.confirm")

CONFIRM_REQUESTED = "confirm.requested"
CONFIRM_RESPONSE = "confirm.response"
CHAT_MESSAGE = "chat.message"
ANSWER_WINDOW_S = 180.0  # a yes/no counts as an answer only within this long of the question

_YES = {"yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure", "do it", "go ahead",
        "go for it", "please do", "ja", "jo", "mach"}
_NO = {"no", "n", "nope", "nah", "don't", "dont", "stop", "cancel", "never", "nein", "ne"}


def parse_yes_no(text: str) -> bool | None:
    """True for yes, False for no, None if the text isn't a clear answer."""
    t = "".join(ch for ch in (text or "").strip().lower() if ch.isalnum() or ch == " ").strip()
    if not t:
        return None
    if t in _YES:
        return True
    if t in _NO:
        return False
    first = t.split()[0]
    if first in _YES:
        return True
    if first in _NO:
        return False
    return None


class ConfirmResponder:
    """Wire in `build_daemon`; `start()` after Consent so the seam is live. Holds the bus and
    the single open confirmation; emits `confirm.response` when the owner answers in chat."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self._open_id: str | None = None
        self._open_ts: float | None = None
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
        if cid:
            self._open_id, self._open_ts = cid, event.ts

    async def _on_chat(self, event: Event) -> None:
        if self._open_id is None or self._open_ts is None:
            return
        if event.ts - self._open_ts > ANSWER_WINDOW_S:   # the question went stale → plain chat
            self._open_id = self._open_ts = None
            return
        answer = parse_yes_no(event.payload.get("text", ""))
        if answer is None:
            return                                       # not a yes/no → leave it as chat
        cid, self._open_id, self._open_ts = self._open_id, None, None
        await self.bus.publish(Event(CONFIRM_RESPONSE, event.ts,
                                     {"id": cid, "yes": answer}, source="confirm"))
        log.info("confirm: %s -> %s", cid, "yes" if answer else "no")
