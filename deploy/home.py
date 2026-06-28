"""The deploy-side HomeClient seam — the binding from Act to the physical home.

`core/act.py` defines the `HomeClient` Protocol (`drive` + `on_state_change`); the
real implementation is an MQTT / Home Assistant client. That adapter is a later
deploy milestone — until it lands, `home_from_env()` returns a `LoggingHome` so the
WHOLE daemon graph (Act, the StateReconciler, the friction loop) runs end-to-end on
a box with no HA wired yet. This is deliberate: the keystone invariant is that
production runs the one assembled graph, differing from tests only by what
`HomeClient` is injected — so even the no-HA box must inject *a* home, never skip Act.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("homie.deploy.home")


class LoggingHome:
    """A HomeClient with no real home behind it yet: it logs each drive and never
    echoes a state change. The graph runs; nothing physical moves. Replace with the
    MQTT/HA adapter (a deploy milestone) to make actuation real."""

    def __init__(self) -> None:
        self._handler = None

    async def drive(self, entity_id: str, command: object) -> None:
        log.info("home(stub): drive %s <- %r", entity_id, command)

    def on_state_change(self, handler) -> None:
        self._handler = handler  # held; the stub home produces no echoes


def home_from_env():
    """Construct the HomeClient from the environment.

    With both HOMIE_HOME_URL (HA's WebSocket endpoint, e.g.
    ``ws://mini-pc.local:8123/api/websocket``) and HOMIE_HOME_TOKEN (a long-lived access
    token created in HA → Profile → Security) set, returns the real `HomeAssistantClient`
    that drives DIRIGERA/Tradfri through Home Assistant. Otherwise a `LoggingHome`, so the
    whole graph still runs on a box with no HA wired yet."""
    url = os.environ.get("HOMIE_HOME_URL")
    token = os.environ.get("HOMIE_HOME_TOKEN")
    if url and token:
        from core.ha import HomeAssistantClient, WebSocketHAConnection
        # Some hubs (notably IKEA DIRIGERA's local API) confirm a command slowly — HA only
        # acks the WebSocket call_service AFTER the device responds, which can take ~10s on a
        # sluggish hub. Default the confirm timeout generously and let it be tuned by env, so a
        # working-but-slow command isn't reported as a failure (HOMIE_HOME_RESULT_TIMEOUT).
        timeout = float(os.environ.get("HOMIE_HOME_RESULT_TIMEOUT", "30"))
        log.info("home: Home Assistant adapter -> %s (confirm timeout %.0fs)", url, timeout)
        return wrap_desktop(HomeAssistantClient(lambda: WebSocketHAConnection(url), token, result_timeout=timeout))
    if url and not token:
        log.warning("HOMIE_HOME_URL=%s set but HOMIE_HOME_TOKEN missing; using LoggingHome "
                    "(no physical actuation). Create a long-lived token in HA and set it.", url)
    return wrap_desktop(LoggingHome())


def _xdotool_env() -> dict:
    """The X session env the kiosk runs under, so xdotool reaches the right display."""
    env = dict(os.environ)
    env.setdefault("DISPLAY", os.environ.get("HOMIE_DESKTOP_DISPLAY", ":0"))
    return env


def wrap_desktop(home):
    """With HOMIE_DESKTOP=1, wrap the home so `desktop:*` actuators control the main PC via the
    fixed-argv DesktopExecutor (the safe verb allowlist), routing everything else to `home`. Off
    by default — desktop control only exists when the owner turns it on, on the desktop node."""
    if os.environ.get("HOMIE_DESKTOP") != "1":
        return home
    import subprocess
    from core.desktop import CompositeHome, DesktopExecutor

    def run(args: list[str]) -> None:
        subprocess.run(args, env=_xdotool_env(), timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    log.info("home: desktop control ENABLED (fixed verb allowlist via xdotool)")
    return CompositeHome(home, DesktopExecutor(run=run))
