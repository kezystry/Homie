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


def _off_zones() -> frozenset:
    """Off-limits zones (Charter law 4) from BOTH sources, unioned: the env var
    HOMIE_OFF_ZONES (comma-separated) and deploy/off_zones.txt (one per line, # comments).
    Empty by default — the owner currently has no off-limits zone (one camera, main room)."""
    zones: set[str] = set()
    for part in (os.environ.get("HOMIE_OFF_ZONES", "") or "").split(","):
        z = part.strip()
        if z:
            zones.add(z)
    path = ROOT / "deploy" / "off_zones.txt"
    try:
        for line in path.read_text("utf-8").splitlines():
            z = line.split("#", 1)[0].strip()
            if z:
                zones.add(z)
    except FileNotFoundError:
        pass
    if zones:
        log.info("off-limits zones (never learned/distilled): %s", ", ".join(sorted(zones)))
    return frozenset(zones)


def _llm_client():
    """The reasoning cortex client, iff HOMIE_LLM_URL is set. deploy.llm is imported
    lazily so the anchor (no URL) never even imports the network path."""
    if not os.environ.get("HOMIE_LLM_URL"):
        print("homie: no HOMIE_LLM_URL — running the anchor floor (no cortex)", flush=True)
        return None
    # Cortex is on — let the ACTIVE model profile (switchable general/dev brains, /model)
    # override which endpoint+model it talks to. A plain HOMIE_LLM_URL with no profiles works
    # as before.
    from core.models import ModelRegistry
    active = ModelRegistry.load(ROOT / "deploy" / "models.toml",
                                state_path=STATE / "model.active").active()
    if active:
        os.environ["HOMIE_LLM_URL"] = active.url
        os.environ["HOMIE_LLM_MODEL"] = active.model
        print(f"homie: cortex up — {active.name} brain ({active.role}) -> {active.url}", flush=True)
    else:
        print(f"homie: reasoning cortex up against {os.environ['HOMIE_LLM_URL']}", flush=True)
    from deploy.llm import client_from_env  # lazy: keep the anchor dependency-free
    return client_from_env()


def _perception():
    """The injected perception source. With HOMIE_FAKE_PERCEPTION=<scenario> set, boot
    the REAL daemon against a deterministic synthetic day (no camera/Pi/GPU) — the
    acceptance harness for the whole graph until the live mesh/device adapter lands.
    Unset = no live intake yet (events arrive via tests/mesh)."""
    name = os.environ.get("HOMIE_FAKE_PERCEPTION")
    if not name:
        if os.environ.get("HOMIE_DESKTOP") == "1":
            # On the desktop node: the eyes are the X11 DesktopAdapter (active app + media
            # title/state via xdotool — facts, never frames). Feeds the WatchLog + GIST.
            import subprocess
            from core.perceive import Perceive
            from perception.desktop_adapter import DesktopAdapter, XdotoolProbe

            display = os.environ.get("HOMIE_DESKTOP_DISPLAY", ":0")
            env = dict(os.environ, DISPLAY=display)

            def run(args):
                return subprocess.run(args, capture_output=True, text=True, env=env, timeout=3).stdout

            print(f"homie: desktop eyes — xdotool on DISPLAY={display}", flush=True)
            return Perceive(DesktopAdapter(XdotoolProbe(display=display, run=run, now=__import__("time").time)))
        return None
    from core.perceive import Perceive  # lazy: only the demo path needs these
    from core.scenarios import build
    from core.synthetic import SyntheticPerception

    speed = float(os.environ.get("HOMIE_FAKE_SPEED", "1.0"))
    print(f"homie: synthetic perception — replaying {name!r} (speed={speed})", flush=True)
    return Perceive(SyntheticPerception(build(name), speed=speed))


def _act_map() -> ActMap | None:
    """The actuator allowlist + never-touch guard, from deploy/act_map.toml. An
    unreadable map means no actuators are mapped (the loop still runs)."""
    path = ROOT / "deploy" / "act_map.toml"
    try:
        return ActMap.load(path)
    except Exception as ex:
        log.warning("act map %s unreadable (%r); no actuators mapped", path, ex)
        return None


def _shell_runner():
    """Let owner-typed system /commands (/update, /restart, /reboot…) actually run — but ONLY
    when HOMIE_SHELL_COMMANDS=1 (needs a polkit rule so the homie user may restart/reboot).
    Off by default → those commands just reply with the command to paste."""
    if os.environ.get("HOMIE_SHELL_COMMANDS") != "1":
        return None
    import subprocess

    def run(argv: list) -> str:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        return (r.stdout or r.stderr or "").strip()[:2000]

    return run


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
        shell_runner=_shell_runner(),
        off_zones=_off_zones(),
    )
    # Perception is one more injected seam: a synthetic scenario (HOMIE_FAKE_PERCEPTION)
    # today, the live MQTT/mesh adapter later — no rewiring, just a different source.
    daemon = build_daemon(home_from_env(), _perception(), config=config)
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
