"""Homie reasoning-node daemon entrypoint — a THIN caller of build_daemon.

This is what the OS `homie.service` launches. It constructs nothing of substance
itself: it reads config from the environment, injects the real `HomeClient` (and the
real `LLMClient` when a model is served), and hands everything to
`core.daemon.build_daemon` — the single assembler of the whole graph. The spine demo
and every test call that same assembler, so a green suite is a proof THIS daemon
works (there is no second wiring for production to diverge into — see core/daemon.py).

The reasoning cortex is present iff HOMIE_LLM_URL is set (the desktop node serving
the local model). Unset — the Pi anchor — runs the bus + Remember + tiles + Act +
friction floor with the anchor chat voice and no GPU/serving dependency.

    python3 scripts/run.py            # state in $HOMIE_STATE (default /var/lib/homie)
    HOMIE_STATE=./.state python3 scripts/run.py
    HOMIE_LLM_URL=http://127.0.0.1:8080/v1/chat/completions python3 scripts/run.py  # + cortex
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

log = logging.getLogger("homie.run")

from core.act import ActMap  # noqa: E402
from core.daemon import DaemonConfig, build_daemon  # noqa: E402

STATE = Path(os.environ.get("HOMIE_STATE", "/var/lib/homie"))


def _llm_client():
    """The reasoning cortex client, iff HOMIE_LLM_URL is set. deploy.llm is imported
    lazily so the anchor (no URL) never even imports the network path."""
    if not os.environ.get("HOMIE_LLM_URL"):
        print("homie: no HOMIE_LLM_URL — running the anchor floor (no cortex)", flush=True)
        return None
    from deploy.llm import client_from_env  # lazy: keep the anchor dependency-free
    print(f"homie: reasoning cortex up against {os.environ['HOMIE_LLM_URL']}", flush=True)
    return client_from_env()


def _act_map() -> ActMap | None:
    """The actuator allowlist + never-touch guard, from deploy/act_map.toml. An
    unreadable map means no actuators are mapped (the loop still runs)."""
    path = ROOT / "deploy" / "act_map.toml"
    try:
        return ActMap.load(path)
    except Exception as ex:
        log.warning("act map %s unreadable (%r); no actuators mapped", path, ex)
        return None


async def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    from deploy.home import home_from_env  # the injected HomeClient (LoggingHome until HA lands)

    config = DaemonConfig(
        state=STATE,
        act_map=_act_map(),
        llm=_llm_client(),
        cockpit_sock=os.environ.get("HOMIE_COCKPIT_SOCK", str(STATE / "cockpit.sock")),
        compact_threshold=int(os.environ.get("HOMIE_COMPACT_THRESHOLD", "5000")),
        compact_interval=float(os.environ.get("HOMIE_COMPACT_INTERVAL", "3600")),
    )
    # perception=None for now: the live MQTT/mesh intake adapter lands in M2 and is
    # injected here exactly like the home and the model — one more seam, no rewiring.
    daemon = build_daemon(home_from_env(), None, config=config)
    await daemon.start()
    print(f"homie: up with tiles {daemon.sup.status()}", flush=True)
    try:
        await daemon.run_forever()  # until the service stops us
    finally:
        await daemon.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
