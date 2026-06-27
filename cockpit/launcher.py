"""The cockpit launcher — a static allowlist of apps/games, launched safely.

Security stance (cockpit council): the launcher is a fixed map of label ->
argv-list. There is NO user-supplied command string and NO shell — a malicious
or fat-fingered input can only ever pick an existing label, never inject a
command. Adding an app is a code/config change, not a runtime input. This is the
concrete form of the standing rule: Steam/Proton + named apps only, never an
arbitrary path (the cracked-repack / infostealer vector).

Heavy pixels render as separate fullscreen surfaces: each app launches under a
gamescope micro-compositor that owns the display for the run and hands it back
on exit. The camera reads the LOCAL device directly (mpv av://v4l2) — never via
the bus, so a frame never crosses an event boundary.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class App:
    label: str
    argv: tuple[str, ...]
    summary: str = ""


# The allowlist. Each argv is a FIXED list — no shell, no interpolation. gamescope
# owns the display for the run; `-f` is fullscreen. Camera reads /dev/video0 via
# mpv's v4l2 source straight from the local device.
DEFAULT_APPS: tuple[App, ...] = (
    App("stremio", ("gamescope", "-f", "--", "stremio"), "Movies & TV (Stremio)"),
    App("steam", ("gamescope", "-f", "--", "steam", "-gamepadui"), "Games (Steam / Proton)"),
    App("camera", ("gamescope", "-f", "--", "mpv", "--profile=low-latency", "av://v4l2:/dev/video0"), "Live camera"),
)


class LaunchError(RuntimeError):
    pass


class Launcher:
    """Holds the allowlist and spawns the chosen app. `spawn` is injectable so the
    UI and tests never actually fork a compositor."""

    def __init__(self, apps: tuple[App, ...] = DEFAULT_APPS, *, spawn=None) -> None:
        self._apps = {a.label: a for a in apps}
        self._order = [a.label for a in apps]
        self._spawn = spawn or _spawn_detached

    def apps(self) -> list[App]:
        """The allowlisted apps, in display order."""
        return [self._apps[label] for label in self._order]

    def labels(self) -> list[str]:
        return list(self._order)

    def get(self, label: str) -> App:
        if label not in self._apps:
            raise LaunchError(f"unknown app {label!r} — not in the allowlist")
        return self._apps[label]

    def available(self, label: str) -> bool:
        """Whether the app's launcher binary is on PATH (so the UI can grey out
        what isn't installed yet, e.g. Steam before Stage 4)."""
        argv = self.get(label).argv
        return shutil.which(argv[0]) is not None

    def launch(self, label: str):
        """Launch an allowlisted app. Returns whatever `spawn` returns (a Popen by
        default). Raises LaunchError for an unknown label."""
        app = self.get(label)  # raises if not allowlisted
        return self._spawn(list(app.argv))


def _spawn_detached(argv: list[str]):
    """Start the app as a child process. No shell (argv list), so nothing is
    interpolated or word-split. The cockpit stays responsive while it runs."""
    return subprocess.Popen(argv)
