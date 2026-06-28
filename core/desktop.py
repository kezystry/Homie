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

# The desktop actuators a tile may drive (manifest) and the identity act-map that binds each
# `desktop.<verb>` actuator to the `desktop:<verb>` entity the DesktopExecutor handles. Merged
# into the live act-map only when HOMIE_DESKTOP=1 (scripts/run.py), so desktop control is mapped
# exactly when it is enabled — and refused (unmapped) otherwise.
DESKTOP_ACTUATORS = ("play_pause", "next", "prev", "seek_fwd", "seek_back", "stop", "close")


def desktop_act_map() -> dict[str, str]:
    """`{'desktop.play_pause': 'desktop:play_pause', …}` — the identity binding for the act-map."""
    return {f"desktop.{v}": f"desktop:{v}" for v in DESKTOP_ACTUATORS}


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

    # Closing a window is still a window-manager action, NOT a process kill or a shell — it asks
    # the focused (or an allowlisted) window to close, so a refusing app keeps its unsaved work.
    # `close` with no target shuts the ACTIVE window (the common "I'm watching Stremio, close it").
    ACTIVE_CLOSE = ["getactivewindow", "windowclose"]
    # Closing a NAMED app: a FIXED argv per app, keyed by name. The owner's typed name only
    # SELECTS a key here — it is never interpolated into the command — so this stays a closed
    # allowlist (no window-target injection from a malicious addon, same rule as the verbs).
    CLOSE_TARGETS: dict[str, list[str]] = {
        "stremio": ["search", "--class", "stremio", "windowclose"],
    }

    def __init__(self, *, run=None) -> None:
        self._run = run            # injected fixed-argv runner (set up in deploy); None = no-op
        # NB: the X11 DISPLAY is set on the injected runner's environment in deploy/home.py
        # (_xdotool_env → HOMIE_DESKTOP_DISPLAY); the executor never needs it directly.
        self.driven: list[str] = []   # verbs issued (telemetry / tests)

    def handles(self, entity_id: object) -> bool:
        return isinstance(entity_id, str) and entity_id.startswith(self.PREFIX)

    async def drive(self, entity_id: str, command: object) -> None:
        verb = entity_id[len(self.PREFIX):]
        if verb == "close":
            return await self._close(command)
        args = self.VERBS.get(verb)
        if args is None:           # not in the allowlist → refuse, NEVER fall through to a shell
            raise ValueError(f"desktop: refused unknown verb {verb!r} (not in the safe allowlist)")
        self.driven.append(verb)
        if self._run is not None:
            self._run(["xdotool", *args])   # fixed argv only — no shell, no string interpolation
        log.info("desktop: %s", verb)

    async def _close(self, command: object) -> None:
        """Close the active window, or an allowlisted named app (`{'target': 'stremio'}`). The
        name only picks a fixed argv from CLOSE_TARGETS — never interpolated — so an unknown app
        is refused, not run."""
        target = command.get("target") if isinstance(command, dict) else None
        if target:
            args = self.CLOSE_TARGETS.get(str(target).strip().lower())
            if args is None:
                raise ValueError(f"desktop: refused close of unknown app {target!r} "
                                 f"(not in the close allowlist: {', '.join(self.CLOSE_TARGETS)})")
        else:
            args = self.ACTIVE_CLOSE
        self.driven.append(f"close:{str(target).lower() if target else 'active'}")
        if self._run is not None:
            self._run(["xdotool", *args])
        log.info("desktop: close %s", target or "(active window)")

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
