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
        log.info("home: Home Assistant adapter -> %s", url)
        return HomeAssistantClient(lambda: WebSocketHAConnection(url), token)
    if url and not token:
        log.warning("HOMIE_HOME_URL=%s set but HOMIE_HOME_TOKEN missing; using LoggingHome "
                    "(no physical actuation). Create a long-lived token in HA and set it.", url)
    return LoggingHome()
