"""The cockpit curses UI — status, chat, launcher, and a live camera pane.

A stdlib-curses control plane. It connects to the bus bridge in a background
reader thread (so the UI never blocks on the socket), renders a scrolling chat
with the brain and a live status feed, launches allowlisted apps/games as
separate fullscreen surfaces, and shows a live camera thumbnail rendered with the
terminal's own colours (see cockpit/camera.py — no web, no chafa fighting curses).

Two ways to drive it (the owner asked for arrow-key traversal, no mouse):
  * ARROW KEYS            -> move focus between panes (chat · camera · apps)
  * Enter on a focused
    camera/app (empty input) -> activate it (full cam view / launch)
  * type + Enter          -> chat with the brain
  * /stremio /steam /camera, /launch <label> -> launch that app (cockpit-local)
  * /cam                  -> toggle the camera pane on/off
  * /quit  (or Ctrl-C)    -> exit
  * ANY OTHER /command    -> forwarded to Homie (/status /now /know /close /mute
                             /private /model /update /restart /rebuild /reboot /rollback)
  * /help                 -> cockpit keys + Homie's command list

The camera pane stays hidden until a webcam device is present, then appears on
its own; the crisp FULL view is mpv --vo=drm via the launcher. Heavy pixels never
live in the terminal as more than a thumbnail, and never cross the bus.

Travels over SSH unchanged (a phone client gets 256-colour, so the thumbnail is a
real picture there); the launched surfaces only appear on the box's own display.
"""
from __future__ import annotations

import curses
import os
import queue
import threading
import time
from typing import Callable, Optional

from cockpit.camera import CameraSource, nearest_256, nearest_ansi
from cockpit.client import CockpitClient
from cockpit.launcher import Launcher

# Topics rendered in the chat column vs the status column.
CHAT_TOPICS = {"chat.reply", "interface.say"}
STATUS_PREFIXES = ("presence.", "security.", "motion.", "occupancy.", "node.", "actuator.", "tile.")
MAX_CHAT = 500
MAX_STATUS = 200

CAM_PANE_ROWS = 12          # cell height budget for the camera thumbnail
_CAM_CHECK_INTERVAL = 2.0   # how often to (cheaply) re-check for a webcam
_UI_PAIR_BASE = 16          # camera colour pairs start here; below is UI chrome


class Cockpit:
    def __init__(
        self,
        client: CockpitClient,
        launcher: Optional[Launcher] = None,
        *,
        device: str = "/dev/video0",
        present_fn: Optional[Callable[[], bool]] = None,
        cam_factory: Optional[Callable[[Callable[[], tuple[int, int]]], CameraSource]] = None,
    ) -> None:
        self.client = client
        self.launcher = launcher or Launcher()
        self.chat: list[str] = []
        self.status: list[str] = []
        self.input = ""
        self.connected = False
        self._q: "queue.Queue" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self._running = True
        # camera
        self.device = device
        self._present_fn = present_fn or (lambda: os.path.exists(device))
        self._cam_factory = cam_factory
        self._cam: Optional[CameraSource] = None
        self._cam_enabled = True          # /cam toggles this; "always-on but toggleable"
        self._cam_present = False          # last device-presence check
        self._cam_checked_at = 0.0
        self._cam_pane_size = (0, 0)       # (cols, rows) of cells, updated each draw
        # focus / navigation
        self._focus = 0
        # colour rendering for the camera (set up once curses starts)
        self._quant = nearest_256
        self._pairs: dict[int, int] = {}
        self._next_pair = _UI_PAIR_BASE

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

    # -- focus / navigation --------------------------------------------------- #
    def _cam_shown(self) -> bool:
        """The camera pane is shown only when enabled AND a device is present —
        so with no webcam plugged in the pane is hidden entirely (owner's call)."""
        return self._cam_enabled and self._cam_present

    def _launch_apps(self) -> list:
        """Apps shown in the LAUNCH pane — everything except the camera, which
        lives in its own pane (so it's never duplicated as a launch tile)."""
        return [a for a in self.launcher.apps() if a.label != "camera"]

    def _targets(self) -> list[str]:
        """The arrow-key focus ring: chat, then the camera (if a device is shown),
        then each launchable app. Order matches the on-screen layout top-to-bottom.
        The camera appears once — as the pane — never also as a launch tile."""
        targets = ["chat"]
        if self._cam_shown():
            targets.append("camera")
        targets.extend(a.label for a in self._launch_apps())
        return targets

    def _focused(self) -> str:
        targets = self._targets()
        return targets[self._focus % len(targets)] if targets else "chat"

    def _move_focus(self, delta: int) -> None:
        targets = self._targets()
        if targets:
            self._focus = (self._focus + delta) % len(targets)

    def _activate(self) -> None:
        """Enter on a focused pane with an empty input line: launch the camera's
        full view or the focused app. Chat focus does nothing (you type to chat)."""
        target = self._focused()
        if target == "chat":
            return
        self._do_launch(target)

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

    def _launch_labels(self) -> set:
        """The app labels the launcher knows — these `/<label>` commands launch locally."""
        return {a.label.lower() for a in self.launcher.apps()}

    def _command(self, cmd: str) -> None:
        # The cockpit handles ONLY its own window/launcher commands; every other `/command`
        # (/status, /now, /know, /close, /mute, /update, /restart, …) is a Homie command and is
        # forwarded to the daemon — otherwise the cockpit would swallow them (the "unknown app"
        # trap: an unforwarded /update was treated as "launch an app called update").
        parts = cmd.split()
        if not parts:
            return
        name = parts[0].lower()
        if name in ("quit", "q", "exit"):
            self._running = False
            return
        if name == "cam":
            self._cam_enabled = not self._cam_enabled
            self._add_chat(f"· camera pane {'on' if self._cam_enabled else 'off'}")
            return
        if name == "launch" or name in self._launch_labels():
            label = parts[1] if name == "launch" and len(parts) > 1 else name
            self._do_launch(label)
            return
        if name == "help":
            self._add_chat("· arrows move focus · Enter activates a pane · type to chat")
            self._add_chat("· cockpit: /stremio /steam /camera · /launch <label> · /cam · /quit")
            # fall through to also ask Homie for ITS command list (/status /know /update …)
        # a Homie command (or /help) → forward it to the daemon
        self._add_chat(f"you: /{cmd}")
        try:
            self.client.send_chat("/" + cmd)
        except Exception as ex:
            self._add_chat(f"· (couldn't send: {ex})")

    def _do_launch(self, label: str) -> None:
        try:
            self.launcher.launch(label)
            self._add_chat(f"· launching {label} …")
        except Exception as ex:
            self._add_chat(f"· {ex}")

    # -- camera lifecycle ----------------------------------------------------- #
    def _manage_camera(self) -> None:
        """Cheaply re-check for a webcam on an interval and start/stop the capture
        source so the pane appears when a camera is plugged in and the thread isn't
        running when there's nothing to show."""
        now = time.monotonic()
        if now - self._cam_checked_at >= _CAM_CHECK_INTERVAL:
            self._cam_checked_at = now
            self._cam_present = bool(self._present_fn())
        if self._cam_shown() and self._cam is None:
            self._cam = self._make_camera()
            self._cam.start()
        elif not self._cam_shown() and self._cam is not None:
            self._cam.stop()
            self._cam = None

    def _make_camera(self) -> CameraSource:
        if self._cam_factory is not None:
            return self._cam_factory(self._cam_size)
        return CameraSource(self.device, size_fn=self._cam_size, quantize=self._quant)

    def _cam_size(self) -> tuple[int, int]:
        return self._cam_pane_size

    # -- render --------------------------------------------------------------- #
    def _draw(self, scr) -> None:
        scr.erase()
        h, w = scr.getmaxyx()
        left = max(26, w // 3)
        self._draw_header(scr, w)
        self._draw_left(scr, 1, 0, h - 1, left)
        for y in range(1, h - 1):
            try:
                scr.addch(y, left, curses.ACS_VLINE)
            except curses.error:
                pass
        self._draw_chat(scr, 1, left + 1, h - 2, w - left - 1)
        prompt = "> " + self.input
        focus_chat = self._focused() == "chat"
        try:
            scr.addnstr(h - 1, left + 1, prompt.ljust(w - left - 1), w - left - 1,
                        curses.A_BOLD if focus_chat else curses.A_NORMAL)
        except curses.error:
            pass
        if focus_chat:
            curses.curs_set(1)
            try:
                scr.move(h - 1, min(left + 1 + len(prompt), w - 1))
            except curses.error:
                pass
        else:
            curses.curs_set(0)
        scr.refresh()

    def _draw_header(self, scr, w) -> None:
        dot = "●" if self.connected else "○"
        state = "online" if self.connected else "offline"
        clock = time.strftime("%H:%M:%S")
        header = f" ⌂ homie cockpit   {clock}   {dot} {state} "
        try:
            scr.addnstr(0, 0, header.ljust(w), w, curses.A_REVERSE)
        except curses.error:
            pass

    def _draw_left(self, scr, y0, x0, h, width) -> None:
        apps = self._launch_apps()
        launch_h = len(apps) + 1
        cam_h = CAM_PANE_ROWS if self._cam_shown() else 0
        # status gets whatever is left between the header and the cam/launch panes
        status_bottom = h - launch_h - (cam_h + 1 if cam_h else 0)
        self._draw_status(scr, y0, x0, status_bottom, width)
        if cam_h:
            self._draw_camera(scr, status_bottom, x0, cam_h, width)
        self._draw_launcher(scr, h - launch_h, x0, apps, width)

    def _draw_status(self, scr, y0, x0, ymax, width) -> None:
        self._title(scr, y0, x0, "STATUS", width, focused=False)
        rows = ymax - y0 - 1
        view = self.status[-rows:] if rows > 0 else []
        for i, line in enumerate(view):
            try:
                scr.addnstr(y0 + 1 + i, x0, line, width)
            except curses.error:
                pass

    def _draw_camera(self, scr, y0, x0, height, width) -> None:
        focused = self._focused() == "camera"
        self._title(scr, y0, x0, "CAMERA  (Enter = full)", width, focused=focused)
        body_y = y0 + 1
        body_h = height - 1
        # the pixel grid we ask the capture thread to render at
        self._cam_pane_size = (max(1, width), max(1, body_h * 2))  # *2: see note below
        cells = self._cam.cells() if self._cam else None
        if not cells:
            try:
                scr.addnstr(body_y, x0, "  starting camera …", width, curses.A_DIM)
            except curses.error:
                pass
            return
        # Render two stacked pixels per character row as a half-block ▀ (fg = top
        # pixel, bg = bottom pixel) to double vertical resolution. Falls back to a
        # full block if colours are unavailable.
        for r in range(body_h):
            top = cells[2 * r] if 2 * r < len(cells) else None
            bot = cells[2 * r + 1] if 2 * r + 1 < len(cells) else None
            if top is None:
                break
            for c in range(min(width, len(top))):
                fg = top[c]
                bg = bot[c] if bot is not None and c < len(bot) else fg
                self._draw_pixel(scr, body_y + r, x0 + c, fg, bg)

    def _draw_pixel(self, scr, y, x, fg, bg) -> None:
        try:
            pair = self._half_pair(fg, bg)
            if pair:
                scr.addstr(y, x, "▀", curses.color_pair(pair))
            else:
                scr.addch(y, x, " ")
        except curses.error:
            pass

    def _draw_launcher(self, scr, y0, x0, apps, width) -> None:
        self._title(scr, y0, x0, "LAUNCH", width, focused=False)
        for i, app in enumerate(apps):
            ok = self.launcher.available(app.label)
            focused = self._focused() == app.label
            mark = "▶" if focused else (" " if ok else "·")
            label = f"{mark} /{app.label} — {app.summary}"
            attr = curses.A_REVERSE if focused else (curses.A_NORMAL if ok else curses.A_DIM)
            try:
                scr.addnstr(y0 + 1 + i, x0, label, width, attr)
            except curses.error:
                pass

    def _draw_chat(self, scr, y0, x0, rows, width) -> None:
        view = self.chat[-rows:] if rows > 0 else []
        for i, line in enumerate(view):
            try:
                scr.addnstr(y0 + i, x0, line, width)
            except curses.error:
                pass

    def _title(self, scr, y, x, text, width, *, focused: bool) -> None:
        attr = curses.A_REVERSE if focused else curses.A_BOLD
        try:
            scr.addnstr(y, x, text.ljust(width), width, attr)
        except curses.error:
            pass

    # -- colour pairs for the camera ------------------------------------------ #
    def _setup_colors(self) -> None:
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            self._quant = None
            return
        colors = curses.COLORS if curses.has_colors() else 0
        if colors >= 256:
            self._quant = nearest_256
        elif colors >= 16:
            self._quant = lambda r, g, b: nearest_ansi(r, g, b, 16)
        elif colors >= 8:
            self._quant = lambda r, g, b: nearest_ansi(r, g, b, 8)
        else:
            self._quant = None  # monochrome terminal: cam pane shows a placeholder

    def _half_pair(self, fg: int, bg: int) -> int:
        """Allocate (and cache) a curses colour pair for a fg/bg combo, capped at
        the terminal's pair budget. Returns 0 when colour is unavailable/exhausted
        (the caller then draws a blank cell)."""
        if self._quant is None:
            return 0
        key = fg * 1000 + bg
        if key in self._pairs:
            return self._pairs[key]
        if self._next_pair >= min(getattr(curses, "COLOR_PAIRS", 256), 32767):
            return 0
        try:
            curses.init_pair(self._next_pair, fg, bg)
        except curses.error:
            return 0
        self._pairs[key] = self._next_pair
        self._next_pair += 1
        return self._pairs[key]

    # -- main loop ------------------------------------------------------------ #
    def run(self, scr) -> None:
        self._setup_colors()
        curses.curs_set(1)
        scr.nodelay(True)
        scr.timeout(80)
        self.start()
        while self._running:
            self._pump_queue()
            self._manage_camera()
            self._draw(scr)
            try:
                ch = scr.getch()
            except KeyboardInterrupt:
                break
            if ch == -1:
                continue
            self._handle_key(ch)
        if self._cam is not None:
            self._cam.stop()

    def _pump_queue(self) -> None:
        try:
            while True:
                kind, obj = self._q.get_nowait()
                if kind == "event":
                    self._ingest(obj)
                elif kind == "_connected":
                    self.connected = True
                    self._add_chat("· connected to the brain. Arrows move focus; type to chat; /help.")
                elif kind == "_error":
                    self._add_chat(f"· {obj}")
                elif kind == "_eof":
                    self.connected = False
                    self._add_chat("· brain disconnected.")
        except queue.Empty:
            pass

    def _handle_key(self, ch: int) -> None:
        if ch in (curses.KEY_ENTER, 10, 13):
            if self.input:
                self._submit()
            else:
                self._activate()
        elif ch in (curses.KEY_UP, curses.KEY_LEFT):
            self._move_focus(-1)
        elif ch in (curses.KEY_DOWN, curses.KEY_RIGHT):
            self._move_focus(1)
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
