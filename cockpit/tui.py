"""The cockpit curses UI — three panes: status, chat, launcher.

A stdlib-curses control plane. It connects to the bus bridge in a background
reader thread (so the UI never blocks on the socket), renders a scrolling chat
with the brain and a live status feed, and launches allowlisted apps/games as
separate fullscreen surfaces via the Launcher (heavy pixels never live in the
terminal).

Input model — one line at the bottom:
  * plain text + Enter      -> chat with the brain
  * /stremio /steam /camera -> launch that app (or `/launch <label>`)
  * /help                   -> list commands
  * /quit  (or Ctrl-C)      -> exit

Travels over SSH unchanged; the launched surfaces only appear on the box's own
display.
"""
from __future__ import annotations

import curses
import queue
import threading
import time
from typing import Optional

from cockpit.client import CockpitClient
from cockpit.launcher import Launcher

# Topics rendered in the chat column vs the status column.
CHAT_TOPICS = {"chat.reply", "interface.say"}
STATUS_PREFIXES = ("presence.", "security.", "motion.", "occupancy.", "node.", "actuator.", "tile.")
MAX_CHAT = 500
MAX_STATUS = 200


class Cockpit:
    def __init__(self, client: CockpitClient, launcher: Optional[Launcher] = None) -> None:
        self.client = client
        self.launcher = launcher or Launcher()
        self.chat: list[str] = []
        self.status: list[str] = []
        self.input = ""
        self.connected = False
        self._q: "queue.Queue" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self._running = True

    # -- networking (background thread) --------------------------------------- #
    def _connect_and_read(self) -> None:
        try:
            self.client.connect()
        except OSError as ex:
            self._q.put(("_error", f"cannot reach the brain ({ex}). Is homie.service running?"))
            return
        self._q.put(("_connected", None))
        try:
            for obj in self.client.events():
                self._q.put(("event", obj))
        finally:
            self._q.put(("_eof", None))

    def start(self) -> None:
        self._reader = threading.Thread(target=self._connect_and_read, daemon=True)
        self._reader.start()

    # -- message routing ------------------------------------------------------ #
    def _ingest(self, obj: dict) -> None:
        topic = obj.get("topic", "")
        text = (obj.get("payload") or {}).get("text")
        if topic in CHAT_TOPICS and text:
            who = "homie" if obj.get("source") == "reason" else "·"
            self._add_chat(f"{who}: {text}")
        elif topic.startswith(STATUS_PREFIXES):
            self._add_status(self._format_status(topic, obj.get("payload") or {}))

    @staticmethod
    def _format_status(topic: str, payload: dict) -> str:
        zone = payload.get("zone")
        extra = payload.get("reason") or payload.get("state") or ""
        bits = [topic]
        if zone:
            bits.append(f"@{zone}")
        if extra:
            bits.append(str(extra))
        return " ".join(bits)

    def _add_chat(self, line: str) -> None:
        self.chat.append(line)
        del self.chat[:-MAX_CHAT]

    def _add_status(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.status.append(f"{stamp} {line}")
        del self.status[:-MAX_STATUS]

    # -- input handling ------------------------------------------------------- #
    def _submit(self) -> None:
        line = self.input.strip()
        self.input = ""
        if not line:
            return
        if line.startswith("/"):
            self._command(line[1:].strip())
        else:
            self._add_chat(f"you: {line}")
            try:
                self.client.send_chat(line)
            except Exception as ex:
                self._add_chat(f"· (couldn't send: {ex})")

    def _command(self, cmd: str) -> None:
        parts = cmd.split()
        if not parts:
            return
        name = parts[0].lower()
        if name in ("quit", "q", "exit"):
            self._running = False
            return
        if name == "help":
            self._add_chat("· commands: /stremio /steam /camera, /launch <label>, /quit")
            self._add_chat("· anything else is sent to the brain as chat")
            return
        label = parts[1] if name == "launch" and len(parts) > 1 else name
        try:
            self.launcher.launch(label)
            self._add_chat(f"· launching {label} …")
        except Exception as ex:
            self._add_chat(f"· {ex}")

    # -- render --------------------------------------------------------------- #
    def _draw(self, scr) -> None:
        scr.erase()
        h, w = scr.getmaxyx()
        left = max(24, w // 3)
        # header
        state = "connected" if self.connected else "offline"
        header = f" homie cockpit — {state} "
        scr.addnstr(0, 0, header.ljust(w), w, curses.A_REVERSE)
        # left column: status (top) + launcher (bottom)
        self._draw_status(scr, 1, 0, h - 1, left)
        self._draw_launcher(scr, h, left)
        # divider
        for y in range(1, h - 1):
            scr.addch(y, left, curses.ACS_VLINE)
        # right column: chat + input
        self._draw_chat(scr, 1, left + 1, h - 2, w - left - 1)
        prompt = "> " + self.input
        scr.addnstr(h - 1, left + 1, prompt.ljust(w - left - 1), w - left - 1)
        scr.move(h - 1, min(left + 1 + len(prompt), w - 1))
        scr.refresh()

    def _draw_status(self, scr, y0, x0, ymax, width) -> None:
        scr.addnstr(y0, x0, "STATUS".ljust(width), width, curses.A_BOLD)
        rows = ymax - y0 - len(self.launcher.apps()) - 3
        view = self.status[-rows:] if rows > 0 else []
        for i, line in enumerate(view):
            scr.addnstr(y0 + 1 + i, x0, line, width)

    def _draw_launcher(self, scr, h, width) -> None:
        apps = self.launcher.apps()
        base = h - len(apps) - 2
        scr.addnstr(base, 0, "LAUNCH".ljust(width), width, curses.A_BOLD)
        for i, app in enumerate(apps):
            ok = self.launcher.available(app.label)
            mark = " " if ok else "·"
            label = f"{mark} /{app.label} — {app.summary}"
            attr = curses.A_NORMAL if ok else curses.A_DIM
            scr.addnstr(base + 1 + i, 0, label, width, attr)

    def _draw_chat(self, scr, y0, x0, rows, width) -> None:
        view = self.chat[-rows:] if rows > 0 else []
        for i, line in enumerate(view):
            scr.addnstr(y0 + i, x0, line, width)

    # -- main loop ------------------------------------------------------------ #
    def run(self, scr) -> None:
        curses.curs_set(1)
        scr.nodelay(True)
        scr.timeout(80)
        self.start()
        while self._running:
            self._pump_queue()
            self._draw(scr)
            try:
                ch = scr.getch()
            except KeyboardInterrupt:
                break
            if ch == -1:
                continue
            self._handle_key(ch)

    def _pump_queue(self) -> None:
        try:
            while True:
                kind, obj = self._q.get_nowait()
                if kind == "event":
                    self._ingest(obj)
                elif kind == "_connected":
                    self.connected = True
                    self._add_chat("· connected to the brain. Type to chat; /help for commands.")
                elif kind == "_error":
                    self._add_chat(f"· {obj}")
                elif kind == "_eof":
                    self.connected = False
                    self._add_chat("· brain disconnected.")
        except queue.Empty:
            pass

    def _handle_key(self, ch: int) -> None:
        if ch in (curses.KEY_ENTER, 10, 13):
            self._submit()
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.input = self.input[:-1]
        elif ch == 3:  # Ctrl-C
            self._running = False
        elif 32 <= ch < 127:
            self.input += chr(ch)


def run(client: CockpitClient, launcher: Optional[Launcher] = None) -> None:
    cockpit = Cockpit(client, launcher)
    try:
        curses.wrapper(cockpit.run)
    finally:
        client.close()
