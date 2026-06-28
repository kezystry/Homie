"""The confirm.response producer (Phase D) — makes the Consent gate answerable.

Closes audit N10: a typed yes/no now resolves a pending confirmation, but ONLY while one is
open and recent, so ordinary chat is never hijacked into authorising an action.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest

from core.bus import Bus
from core.confirm_responder import ANSWER_WINDOW_S, ConfirmResponder, parse_yes_no
from core.consent import Consent
from core.tile import Event


class ParseTests(unittest.TestCase):
    def test_clear_yes_no(self) -> None:
        for y in ("yes", "Yeah", "ok", "do it", "go ahead", "ja", "sure!"):
            self.assertIs(parse_yes_no(y), True)
        for n in ("no", "Nope", "cancel", "don't", "nein", "stop"):
            self.assertIs(parse_yes_no(n), False)

    def test_non_answer_is_none(self) -> None:
        for t in ("", "what's the weather", "turn on the light", "maybe later"):
            self.assertIsNone(parse_yes_no(t))


class ResponderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = Bus()
        self.responses: list = []
        self.bus.subscribe("confirm.response", lambda e: self.responses.append(e))
        self.r = ConfirmResponder(self.bus)
        await self.r.start()

    async def asyncTearDown(self) -> None:
        await self.r.stop()
        await self.bus.aclose()

    async def _say(self, text: str, ts: float = 0.0) -> None:
        await self.bus.publish(Event("chat.message", ts, {"text": text}, source="cockpit"))
        await self.bus.drain()

    async def _ask(self, cid: str, ts: float = 0.0) -> None:
        await self.bus.publish(Event("confirm.requested", ts, {"id": cid, "prompt": "warm the lights?"},
                                     source="consent"))
        await self.bus.drain()

    async def test_yes_answers_an_open_confirm(self) -> None:
        await self._ask("c1")
        await self._say("yes")
        self.assertEqual(len(self.responses), 1)
        self.assertEqual(self.responses[0].payload, {"id": "c1", "yes": True})

    async def test_no_answers_an_open_confirm(self) -> None:
        await self._ask("c2")
        await self._say("nope")
        self.assertEqual(self.responses[0].payload, {"id": "c2", "yes": False})

    async def test_chat_without_an_open_confirm_is_ignored(self) -> None:
        await self._say("yes")                       # no question pending → plain chat
        self.assertEqual(self.responses, [])

    async def test_only_answers_once(self) -> None:
        await self._ask("c3")
        await self._say("yes")
        await self._say("yes")                       # a second yes is plain chat again
        self.assertEqual(len(self.responses), 1)

    async def test_stale_question_is_not_answered(self) -> None:
        await self._ask("c4", ts=0.0)
        await self._say("yes", ts=ANSWER_WINDOW_S + 1)   # answered far too late
        self.assertEqual(self.responses, [])

    async def test_non_answer_leaves_confirm_open(self) -> None:
        await self._ask("c5")
        await self._say("hmm not sure")              # not yes/no → confirm stays open
        await self._say("yes")
        self.assertEqual(self.responses[0].payload, {"id": "c5", "yes": True})


class EndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_consent_request_resolves_yes_via_chat(self) -> None:
        bus = Bus()
        consent = Consent(bus, timeout=5.0)
        responder = ConfirmResponder(bus)
        await consent.start()
        await responder.start()
        try:
            # Homie asks; the owner answers "yes" in chat; the request resolves True.
            async def answer() -> None:
                await asyncio.sleep(0)               # let confirm.requested publish first
                await bus.publish(Event("chat.message", 1.0, {"text": "yes"}, source="cockpit"))
            asyncio.ensure_future(answer())
            granted = await consent.request("warm the hallway lights?")
            self.assertTrue(granted)
        finally:
            await responder.stop()
            await consent.stop()
            await bus.aclose()

    async def test_consent_still_fails_safe_with_no_answer(self) -> None:
        bus = Bus()
        consent = Consent(bus, timeout=0.05, default=False)
        responder = ConfirmResponder(bus)
        await consent.start(); await responder.start()
        try:
            granted = await consent.request("spend money?")   # nobody answers → safe no
            self.assertFalse(granted)
        finally:
            await responder.stop(); await consent.stop(); await bus.aclose()


if __name__ == "__main__":
    unittest.main()
