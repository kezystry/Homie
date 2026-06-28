"""SlashCommands — owner-typed `/commands` in the chat / terminal.

The owner wants to TYPE commands at Homie ("/now", "/reboot", "/update") and have them happen,
not read a doc. This handler watches the chat for a leading `/`, parses a FIXED allowlist of
commands (the OWNER's input, never the model's), and either answers in-chat (status, now
playing, recommendations) or runs a system action through an injected `runner`.

Safety: the command set is closed (an unknown `/x` just lists the real ones). System commands
(update/restart/rebuild/reboot/rollback) only EXECUTE when a `runner` is wired (deploy opt-in,
HOMIE_SHELL_COMMANDS=1 with a polkit rule); otherwise Homie replies with the exact command to
paste, so nothing privileged happens by surprise. In-chat read-only commands always work.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from core.tile import Event

log = logging.getLogger("homie.commands")

CHAT_IN = "chat.message"
REPLY = "chat.reply"


def _minutes_arg(args, default: float = 60.0) -> float:
    """First arg as float minutes, or `default` if it's missing/not a number. Tolerant by
    design: '/mute', '/mute 30', '/mute 1.2.3', '/mute abc' must never crash the handler."""
    try:
        return float(args[0])
    except (ValueError, IndexError, TypeError):
        return default

# System commands → the argv a wired runner executes. Without a runner, the joined string is
# shown to the owner to paste. `{root}` is filled with the repo path.
_SYSTEM = {
    "update":   ["python3", "{root}/scripts/update.py"],
    "restart":  ["systemctl", "restart", "homie"],
    "rebuild":  ["nixos-rebuild", "switch"],
    "reboot":   ["systemctl", "reboot"],
    "rollback": ["git", "-C", "{root}", "reset", "--hard", "HEAD@{1}"],
}

_HELP = [
    "Commands you can type:",
    "  /status      — is Homie up, what it knows, what's playing",
    "  /now         — what you're watching right now",
    "  /recommend   — your picks & taste (the recommendation page)",
    "  /mute [min]  — quiet for a while   ·   /unmute",
    "  /private on|off — stop/allow watching your screen",
    "  /model [name]— list the brains (general / dev) or switch to one",
    "  /update      — pull + health-check the latest version",
    "  /restart     — restart Homie   ·   /rebuild — apply OS changes",
    "  /reboot      — reboot the machine   ·   /rollback — undo the last update",
]


class SlashCommands:
    def __init__(self, bus, *, state=None, runner=None, root: Path | str | None = None,
                 models=None) -> None:
        self.bus = bus
        self.state = Path(state) if state else None
        self._run = runner               # callable(list[str]) -> str ; None = reply with the command
        self.root = str(root) if root else "/opt/homie"
        self.models = models             # ModelRegistry | None — the switchable brains
        self._sub = None

    async def start(self) -> None:
        self._sub = self.bus.subscribe(CHAT_IN, self._on_chat, owner="commands")

    async def stop(self) -> None:
        if self._sub is not None:
            self.bus.unsubscribe(self._sub)
            self._sub = None

    async def _reply(self, ts: float, text: str) -> None:
        await self.bus.publish(Event(REPLY, ts, {"text": text}, source="commands"))

    async def _on_chat(self, event: Event) -> None:
        text = str(event.payload.get("text", "")).strip()
        if not text.startswith("/"):
            return
        parts = text[1:].split()
        if not parts:
            return
        cmd, args, ts = parts[0].lower(), parts[1:], event.ts
        reply = await self._dispatch(cmd, args, ts)
        if reply is not None:
            await self._reply(ts, reply)

    async def _dispatch(self, cmd: str, args: list[str], ts: float) -> str | None:
        if cmd in ("help", "commands", "?"):
            return "\n".join(_HELP)
        if cmd == "status":
            return self._status()
        if cmd == "now":
            return self._now()
        if cmd in ("recommend", "watch", "recommendations"):
            return self._recommend()
        if cmd == "mute":
            seconds = _minutes_arg(args) * 60.0 if args else 3600.0
            await self.bus.publish(Event("voice.mute", ts, {"seconds": seconds}, source="commands"))
            return f"Quiet for {round(seconds/60)} min. Say /unmute to switch back on."
        if cmd == "unmute":
            await self.bus.publish(Event("voice.unmute", ts, {}, source="commands"))
            return "Talking again."
        if cmd == "private":
            on = not (args and args[0].lower() in ("off", "false", "0"))
            await self.bus.publish(Event("media.private", ts, {"on": on}, source="commands"))
            return "Screen-private ON — I'm not watching your screen." if on else "Screen-private off."
        if cmd in ("model", "brain"):
            return self._model(args)
        if cmd in _SYSTEM:
            return self._system(cmd)
        return "Unknown command. Type /help for the list."

    def _model(self, args: list[str]) -> str:
        if self.models is None or not self.models.names():
            return "No model profiles configured (cortex uses the single HOMIE_LLM_URL)."
        if not args:
            active = self.models.active()
            lines = ["Brains (type /model <name> to switch):"]
            for p in self.models.profiles():
                mark = "→" if active and p.name == active.name else " "
                lines.append(f"  {mark} {p.name} ({p.role}) — {p.note or p.url}")
            return "\n".join(lines)
        name = args[0]
        if self.models.switch(name):
            return f"Switched to the {name} brain. /restart to apply it to the running cortex."
        return f"No brain called “{name}”. Type /model to list them."

    # -- read-only answers ---------------------------------------------------- #
    def _status(self) -> str:
        try:
            from core import status
            facts = status.runtime_facts(self.state)
            if not facts.get("present"):
                return "Homie is up. (No state dir to summarize.)"
            ev = facts.get("events", {})
            bits = [f"Up · {ev.get('count', 0)} events logged"]
            if facts.get("now_watching"):
                bits.append(f"▶ watching {facts['now_watching'].get('title')}")
            know = facts.get("knows") or []
            if know:
                bits.append(f"{len(know)} things known about you")
            return " · ".join(bits)
        except Exception:
            return "Homie is up."

    def _now(self) -> str:
        if self.state is None:
            return "I can't see the screen from here."
        try:
            cur = json.loads((self.state / "now.json").read_text("utf-8"))
            return f"You're watching “{cur.get('title')}” ({cur.get('app')})."
        except FileNotFoundError:
            return "Nothing playing right now."
        except Exception:
            return "Nothing playing right now."

    def _recommend(self) -> str:
        if self.state is None:
            return "No watch history yet."
        try:
            from core.watchlog import WatchLog, render_page
            import time
            lines = render_page(WatchLog(self.state / "watch.json").sessions(), time.time())
            return "\n".join(lines)
        except Exception:
            return "No watch history yet."

    # -- system actions ------------------------------------------------------- #
    def _system(self, cmd: str) -> str:
        argv = [a.replace("{root}", self.root) for a in _SYSTEM[cmd]]
        if self._run is None:
            return f"To {cmd}, run:\n  {' '.join(argv)}"
        try:
            out = self._run(argv)
            return f"{cmd}: done.\n{out}".rstrip()
        except Exception as ex:
            return f"{cmd} failed: {ex}"
