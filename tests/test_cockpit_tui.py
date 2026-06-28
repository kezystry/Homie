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

    def test_daemon_command_is_forwarded_not_launched(self) -> None:
        # /update, /status, /know, /close … are Homie commands: forwarded to the daemon,
        # never treated as an app to launch (the "unknown app update" trap).
        for cmd in ("/update", "/status", "/close stremio", "/know kitchen"):
            c, client, spawned = cockpit()
            c.input = cmd
            c._submit()
            self.assertEqual(spawned, [])              # nothing launched
            self.assertEqual(client.sent, [cmd])       # sent verbatim to Homie
            self.assertTrue(any(f"you: {cmd}" in line for line in c.chat))

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


def cockpit_with_cam() -> tuple[Cockpit, list]:
    spawned: list = []
    launcher = Launcher(
        (
            App("camera", ("mpv", "--vo=drm", "av://v4l2:/dev/video0"), "cam"),
            App("stremio", ("gamescope", "-f", "--", "stremio"), "Movies"),
        ),
        spawn=lambda argv: spawned.append(argv),
    )
    c = Cockpit(FakeClient(), launcher, present_fn=lambda: True)
    return c, spawned


def _focus_on(c: Cockpit, name: str) -> None:
    c._focus = c._targets().index(name)


class CameraVisibilityTests(unittest.TestCase):
    def test_pane_hidden_when_no_device(self) -> None:
        c, _ = cockpit_with_cam()
        c._cam_present = False
        self.assertFalse(c._cam_shown())
        self.assertNotIn("camera", c._targets())

    def test_pane_shown_when_device_present(self) -> None:
        c, _ = cockpit_with_cam()
        c._cam_present = True
        self.assertTrue(c._cam_shown())
        self.assertIn("camera", c._targets())

    def test_cam_command_toggles_pane(self) -> None:
        c, _ = cockpit_with_cam()
        c._cam_present = True
        c._command("cam")           # disable
        self.assertFalse(c._cam_shown())
        self.assertNotIn("camera", c._targets())
        c._command("cam")           # re-enable
        self.assertTrue(c._cam_shown())


class NavigationTests(unittest.TestCase):
    def test_focus_ring_wraps(self) -> None:
        c, _ = cockpit_with_cam()
        c._cam_present = True
        targets = c._targets()  # ["chat", "camera", "stremio"]
        self.assertEqual(c._focused(), "chat")
        for _ in range(len(targets)):
            c._move_focus(1)
        self.assertEqual(c._focused(), "chat")  # full cycle returns home
        c._move_focus(-1)
        self.assertEqual(c._focused(), targets[-1])  # wraps backward

    def test_enter_on_empty_input_activates_focused_app(self) -> None:
        c, spawned = cockpit_with_cam()
        c._cam_present = True
        _focus_on(c, "stremio")
        c._handle_key(10)  # Enter with empty input
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0][0], "gamescope")

    def test_enter_on_camera_launches_full_view(self) -> None:
        c, spawned = cockpit_with_cam()
        c._cam_present = True
        _focus_on(c, "camera")
        c._activate()
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0][0], "mpv")  # full view is mpv --vo=drm

    def test_enter_with_text_still_chats(self) -> None:
        c, spawned = cockpit_with_cam()
        c.input = "hello"
        c._handle_key(10)
        self.assertEqual(spawned, [])  # not a launch
        self.assertEqual(c.client.sent, ["hello"])


if __name__ == "__main__":
    unittest.main()
