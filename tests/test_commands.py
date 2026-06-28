"""Owner-typed /commands in chat — the slash-command handler.

Proves: a leading-/ message is parsed against a FIXED allowlist; read-only commands answer
in-chat; control commands publish the right bus event; system commands run via an injected
runner (and, with no runner, reply with the command to paste); plain chat is ignored.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.commands import SlashCommands
from core.tile import Event


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, text, *, state=None, runner=None):
        bus = Bus()
        replies, events = [], []
        bus.subscribe("chat.reply", lambda e: replies.append(e.payload["text"]))
        for t in ("voice.mute", "voice.unmute", "media.private"):
            bus.subscribe(t, lambda e, _t=t: events.append((_t, e.payload)))
        sc = SlashCommands(bus, state=state, runner=runner, root="/opt/homie")
        await sc.start()
        await bus.publish(Event("chat.message", 1.0, {"text": text}, source="cockpit"))
        await bus.drain()
        await sc.stop(); await bus.aclose()
        return replies, events

    async def test_plain_chat_is_ignored(self) -> None:
        replies, _ = await self._run("what's the weather")
        self.assertEqual(replies, [])

    async def test_help_lists_commands(self) -> None:
        replies, _ = await self._run("/help")
        self.assertTrue(any("/now" in r and "/reboot" in r for r in replies))

    async def test_unknown_command_points_to_help(self) -> None:
        replies, _ = await self._run("/frobnicate")
        self.assertIn("/help", replies[-1])

    async def test_know_surfaces_the_dream_journal(self) -> None:
        from core.gist import Beta, Schema
        from core.gist_store import GistStore
        firm = Schema(kind="rule", daytype="wd", daypart="eve", tokens=("media", "plex"),
                      beta=Beta(a_q=8000, b_q=0))     # firmness 3 → a firm, present-tense line
        with TemporaryDirectory() as d:
            GistStore(Path(d) / "memory.ddn").save([firm])
            replies, _ = await self._run("/know", state=Path(d))
            self.assertTrue(any("plex" in r.lower() for r in replies))
            # filtered to a word that matches
            hit, _ = await self._run("/know plex", state=Path(d))
            self.assertTrue(any("plex" in r.lower() for r in hit))
            # filtered to a word that doesn't
            miss, _ = await self._run("/know kitchen", state=Path(d))
            self.assertIn("Nothing firm", miss[-1])

    async def test_know_is_honest_empty_without_memory(self) -> None:
        replies, _ = await self._run("/know")
        self.assertIn("still learning", replies[-1])

    async def test_mute_publishes_voice_mute(self) -> None:
        replies, events = await self._run("/mute 30")
        self.assertEqual(events[0][0], "voice.mute")
        self.assertEqual(events[0][1]["seconds"], 1800.0)        # 30 min
        self.assertIn("30 min", replies[-1])

    async def test_close_publishes_desktop_control(self) -> None:
        bus = Bus()
        ctrl: list = []
        bus.subscribe("desktop.control", lambda e: ctrl.append(e.payload))
        sc = SlashCommands(bus, root="/opt/homie")
        await sc.start()
        await bus.publish(Event("chat.message", 1.0, {"text": "/close stremio"}, source="cockpit"))
        await bus.drain()
        await sc.stop(); await bus.aclose()
        self.assertEqual(ctrl, [{"verb": "close", "target": "stremio"}])

    async def test_close_no_arg_targets_the_active_window(self) -> None:
        bus = Bus()
        ctrl: list = []
        bus.subscribe("desktop.control", lambda e: ctrl.append(e.payload))
        sc = SlashCommands(bus, root="/opt/homie")
        await sc.start()
        await bus.publish(Event("chat.message", 1.0, {"text": "/close"}, source="cockpit"))
        await bus.drain()
        await sc.stop(); await bus.aclose()
        self.assertEqual(ctrl, [{"verb": "close", "target": None}])

    async def test_private_on_and_off(self) -> None:
        _, on = await self._run("/private on")
        self.assertEqual(on[0], ("media.private", {"on": True}))
        _, off = await self._run("/private off")
        self.assertEqual(off[0], ("media.private", {"on": False}))

    async def test_now_reads_the_live_marker(self) -> None:
        with TemporaryDirectory() as d:
            (Path(d) / "now.json").write_text(json.dumps({"title": "Dune", "app": "stremio"}))
            replies, _ = await self._run("/now", state=Path(d))
            self.assertIn("Dune", replies[-1])

    async def test_now_without_anything_playing(self) -> None:
        with TemporaryDirectory() as d:
            replies, _ = await self._run("/now", state=Path(d))
            self.assertIn("Nothing playing", replies[-1])

    async def test_system_command_without_runner_shows_the_command(self) -> None:
        replies, _ = await self._run("/reboot")
        self.assertIn("systemctl reboot", replies[-1])           # safe default: tells you what to run

    async def test_system_command_with_runner_executes(self) -> None:
        ran: list = []
        def runner(argv):
            ran.append(argv)
            return "ok"
        replies, _ = await self._run("/update", runner=runner)
        self.assertEqual(ran[0], ["python3", "/opt/homie/scripts/update.py"])
        self.assertIn("done", replies[-1])


if __name__ == "__main__":
    unittest.main()
