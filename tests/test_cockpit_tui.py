"""Cockpit TUI routing tests — the non-curses logic (ingest, submit, commands).

The curses rendering needs a real terminal and isn't unit-tested; the message
routing and input handling are pure and are pinned here.

Run: python3 -m unittest discover -s tests
"""
import unittest

from cockpit.launcher import App, Launcher
from cockpit.tui import Cockpit


class FakeClient:
    def __init__(self) -> None:
        self.sent: list = []

    def send_chat(self, text: str) -> None:
        self.sent.append(text)

    def close(self) -> None:
        pass


def cockpit() -> tuple[Cockpit, FakeClient, list]:
    spawned: list = []
    launcher = Launcher(
        (App("stremio", ("gamescope", "-f", "--", "stremio"), "Movies"),),
        spawn=lambda argv: spawned.append(argv),
    )
    client = FakeClient()
    return Cockpit(client, launcher), client, spawned


class IngestTests(unittest.TestCase):
    def test_chat_reply_goes_to_chat(self) -> None:
        c, _, _ = cockpit()
        c._ingest({"topic": "chat.reply", "payload": {"text": "hi"}, "source": "reason"})
        self.assertTrue(any("homie: hi" in line for line in c.chat))
        self.assertEqual(c.status, [])

    def test_presence_goes_to_status(self) -> None:
        c, _, _ = cockpit()
        c._ingest({"topic": "presence.arrived", "payload": {"zone": "kitchen"}})
        self.assertTrue(any("presence.arrived" in line and "kitchen" in line for line in c.status))
        self.assertEqual(c.chat, [])

    def test_unknown_topic_ignored(self) -> None:
        c, _, _ = cockpit()
        c._ingest({"topic": "weird.thing", "payload": {}})
        self.assertEqual(c.chat, [])
        self.assertEqual(c.status, [])


class SubmitTests(unittest.TestCase):
    def test_plain_text_is_sent_as_chat(self) -> None:
        c, client, _ = cockpit()
        c.input = "are the lights on?"
        c._submit()
        self.assertEqual(client.sent, ["are the lights on?"])
        self.assertTrue(any("you: are the lights on?" in line for line in c.chat))
        self.assertEqual(c.input, "")

    def test_slash_launch_calls_launcher(self) -> None:
        c, client, spawned = cockpit()
        c.input = "/stremio"
        c._submit()
        self.assertEqual(len(spawned), 1)
        self.assertEqual(client.sent, [])  # a command is not chat

    def test_unknown_command_reports_not_chat(self) -> None:
        c, client, spawned = cockpit()
        c.input = "/nope"
        c._submit()
        self.assertEqual(spawned, [])
        self.assertEqual(client.sent, [])
        self.assertTrue(any("nope" in line for line in c.chat))

    def test_quit_stops_running(self) -> None:
        c, _, _ = cockpit()
        c.input = "/quit"
        c._submit()
        self.assertFalse(c._running)

    def test_blank_submit_noop(self) -> None:
        c, client, _ = cockpit()
        c.input = "   "
        c._submit()
        self.assertEqual(client.sent, [])
        self.assertEqual(c.chat, [])


class KeyTests(unittest.TestCase):
    def test_typing_and_backspace(self) -> None:
        c, _, _ = cockpit()
        for ch in b"hi":
            c._handle_key(ch)
        self.assertEqual(c.input, "hi")
        c._handle_key(127)  # backspace
        self.assertEqual(c.input, "h")


if __name__ == "__main__":
    unittest.main()
