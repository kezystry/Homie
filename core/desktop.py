"""Desktop hands — control the main PC safely (a fixed allowlist, capability-gated).

The owner wants Homie to control Stremio (play/pause, skip). The security council's ruling is
binding here because the main PC runs Stremio — a browser WITHOUT its sandbox — next to his
data: Homie's hands must NEVER become a way for a malicious movie addon to run arbitrary
things. So control is a **fixed allowlist of named safe verbs**, each a fixed `xdotool` argv —
there is **no general-exec, no free-string launch, no keystroke-injection** actuator, by
construction. An unknown verb is refused, not run.

Every desktop effect still flows through the ONE chokepoint (`Act` + the capability gate): the
`CompositeHome` is a single `HomeClient` that routes `desktop:*` entities to the
`DesktopExecutor` and everything else to the real home (Home Assistant). A forged command with
no capability handle is refused before it ever reaches here, exactly like any other actuator.
"""
from __future__ import annotations

import logging

log = logging.getLogger("homie.desktop")


class DesktopExecutor:
    """The ONLY desktop actions Homie can take — a closed set of safe media verbs, each a fixed
    `xdotool` argv (no shell, no interpolation). This list IS the allowlist; nothing outside it
    can execute. Synthetic keystrokes are limited to these media keys into the focused kiosk
    window — never arbitrary text, never a shell."""

    PREFIX = "desktop:"
    VERBS: dict[str, list[str]] = {
        "play_pause": ["key", "--clearmodifiers", "space"],
        "pause":      ["key", "--clearmodifiers", "space"],
        "next":       ["key", "--clearmodifiers", "n"],
        "prev":       ["key", "--clearmodifiers", "p"],
        "seek_fwd":   ["key", "--clearmodifiers", "Right"],
        "seek_back":  ["key", "--clearmodifiers", "Left"],
        "stop":       ["key", "--clearmodifiers", "Escape"],
    }

    def __init__(self, *, run=None, display: str = ":0") -> None:
        self._run = run            # injected fixed-argv runner (set up in deploy); None = no-op
        self.display = display
        self.driven: list[str] = []   # verbs issued (telemetry / tests)

    def handles(self, entity_id: object) -> bool:
        return isinstance(entity_id, str) and entity_id.startswith(self.PREFIX)

    async def drive(self, entity_id: str, command: object) -> None:
        verb = entity_id[len(self.PREFIX):]
        args = self.VERBS.get(verb)
        if args is None:           # not in the allowlist → refuse, NEVER fall through to a shell
            raise ValueError(f"desktop: refused unknown verb {verb!r} (not in the safe allowlist)")
        self.driven.append(verb)
        if self._run is not None:
            self._run(["xdotool", *args])   # fixed argv only — no shell, no string interpolation
        log.info("desktop: %s", verb)

    def on_state_change(self, handler) -> None:
        return  # desktop control emits no state echo; nothing to reconcile


class CompositeHome:
    """One `HomeClient` seam that routes `desktop:*` entities to the `DesktopExecutor` and
    everything else to the real home. Keeps `Act` + the capability gate the single chokepoint —
    desktop control gets no side path around it."""

    def __init__(self, home, desktop: DesktopExecutor) -> None:
        self.home = home
        self.desktop = desktop

    async def drive(self, entity_id: str, command: object) -> None:
        if self.desktop.handles(entity_id):
            await self.desktop.drive(entity_id, command)
        else:
            await self.home.drive(entity_id, command)

    def on_state_change(self, handler) -> None:
        self.home.on_state_change(handler)   # only the real home echoes state

    async def start(self) -> None:
        start = getattr(self.home, "start", None)
        if callable(start):
            await start()

    async def stop(self) -> None:
        stop = getattr(self.home, "stop", None)
        if callable(stop):
            await stop()
