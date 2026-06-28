"""DesktopAdapter — Homie's eyes on the main PC, as derived FACTS, never frames.

The owner wants Homie to see what he does on his main PC (which app, what he's watching in
Stremio). The council pinned the safe shape: this box is a headless **X11** kiosk, so the
active window (EWMH) and its title are readable via `xdotool` — and that's all we read. NO
screen pixels, NO OCR, NO keystrokes: a `PerceptionSource` exactly like `frigate_adapter`,
where the raw view dies at the edge and only scalar facts cross to the bus.

Two event kinds, edge-triggered (emitted on CHANGE, so a 2-hour film is a handful of events):
  * `desktop.focus.changed {app}`        — the foreground app changed.
  * `media.activity {app, state, kind?, title?}` — a media session changed (playing/paused).
    `title` is a LIVE-ONLY fact for in-the-moment help ("what was that?" / resume); the GIST
    distill reads ONLY app+kind (see `gist_store.event_tokens`), so a title is never folded
    into the durable memory — sensitive like a self-photo (Charter 23a).

The probe is injected (`DesktopProbe`): the real one shells `xdotool` under the kiosk's
`DISPLAY` (marked for live validation on the box); tests drive a fake. The adapter logic —
the diffing, the scalar-only payloads — is what's unit-tested here.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Protocol

from core.tile import Event

log = logging.getLogger("homie.desktop")

FOCUS = "desktop.focus.changed"   # out: {app}
MEDIA = "media.activity"          # out: {app, state, kind?, title?}  (title live-only; GIST ignores)
_MEDIA_KINDS = ("film", "series")


class DesktopProbe(Protocol):
    """One read of the desktop. Returns a small scalar dict or None/{} when nothing is up:
    {"ts": float, "app": str, "state": "playing"|"paused"|"stopped"|None,
     "kind": "film"|"series"|None, "title": str|None}. The real probe never returns a frame,
    a poster URL, or any blob — only these plain fields, so a pixel can't ride along."""

    def snapshot(self) -> dict | None: ...


class DesktopAdapter:
    """Poll the probe, emit a normalized event whenever the foreground app or the media state
    changes. A `PerceptionSource` (yields `events()`), so it flows through the same
    `assert_emittable` privacy guard as every other perception source."""

    def __init__(self, probe: DesktopProbe, *, poll_seconds: float = 2.0,
                 sleep=None, max_polls: int | None = None) -> None:
        self.probe = probe
        self.poll_seconds = poll_seconds
        self._sleep = sleep or asyncio.sleep
        self._max_polls = max_polls          # None = run forever; tests cap it

    async def events(self) -> AsyncIterator[Event]:
        last: dict = {}
        polls = 0
        while True:
            snap = self._safe_snapshot()
            for event in self._diff(last, snap):
                yield event
            last = snap
            polls += 1
            if self._max_polls is not None and polls >= self._max_polls:
                return
            await self._sleep(self.poll_seconds)

    def _safe_snapshot(self) -> dict:
        try:
            snap = self.probe.snapshot()
            return snap if isinstance(snap, dict) else {}
        except Exception as ex:               # a flaky probe never kills perception
            log.warning("desktop: probe failed (%r)", ex)
            return {}

    def _diff(self, last: dict, snap: dict) -> list[Event]:
        out: list[Event] = []
        ts = float(snap.get("ts", 0.0) or 0.0)

        app = snap.get("app")
        if app and app != last.get("app"):
            out.append(Event(FOCUS, ts, {"app": str(app)}, source="desktop"))

        # A media event when the (app, state, title) tuple changes and there IS a play state.
        cur = (snap.get("app"), snap.get("state"), snap.get("title"))
        prev = (last.get("app"), last.get("state"), last.get("title"))
        if snap.get("state") and cur != prev:
            payload = {"app": str(snap.get("app", "")), "state": str(snap["state"])}
            if snap.get("kind") in _MEDIA_KINDS:
                payload["kind"] = str(snap["kind"])
            if snap.get("title"):             # live-only fact; gist_store.event_tokens ignores it
                payload["title"] = str(snap["title"])
            out.append(Event(MEDIA, ts, payload, source="desktop"))
        return out


# --------------------------------------------------------------------------- #
# The real probe — xdotool over the kiosk X session. Marked for live validation:
# the daemon must run it with DISPLAY=:0 + XAUTHORITY in the env (deploy note), and
# `xdotool` must be in the system packages. The adapter above is what's unit-tested.
# --------------------------------------------------------------------------- #
class XdotoolProbe:
    """Read the active window's class + title via a FIXED-ARGV `xdotool` call (no shell, no
    interpolation — the cockpit Launcher discipline). Returns app/title/state; never a blob.

    Honest limits (council): Stremio's :11470 is a streaming server, not a control/title API,
    and MPRIS may be absent — so the window title is the robust source of 'what's playing'.
    Poster/art fields are never read, so no file:// pixel path can leak."""

    def __init__(self, *, display: str = ":0", run=None, now=None) -> None:
        self.display = display
        self._run = run            # injected subprocess runner (real one set up in deploy)
        self._now = now

    def snapshot(self) -> dict | None:
        if self._run is None:      # not wired on this host → nothing to see, honestly
            return None
        try:
            wm_class = self._run(["xdotool", "getactivewindow", "getwindowclassname"]).strip().lower()
            title = self._run(["xdotool", "getactivewindow", "getwindowname"]).strip()
        except Exception as ex:
            log.warning("desktop: xdotool read failed (%r)", ex)
            return None
        if not wm_class:
            return None
        ts = float(self._now()) if self._now else 0.0
        state = "playing" if wm_class == "stremio" and title else None
        return {"ts": ts, "app": wm_class, "state": state, "kind": None,
                "title": title if state else None}
