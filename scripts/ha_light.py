#!/usr/bin/env python3
"""ha_light — drive one light through Homie's HA adapter, for testing / manual control.

Reads HOMIE_HOME_URL + HOMIE_HOME_TOKEN from the ENVIRONMENT (never an argument), so you
source the root-only secrets file instead of ever typing the token:

    sudo bash -c 'set -a; . /etc/homie-ha.env; set +a; \
        python3 /opt/homie/scripts/ha_light.py light.nachttisch on 70'

The target may be a Homie actuator name from deploy/act_map.toml (e.g. light.nachttisch) or a
raw HA entity_id (light.schlafzimmer_nachttisch). The never-touch guard is honored: a
forbidden entity is refused here exactly as the daemon would.

    python3 scripts/ha_light.py <actuator-or-entity> <on|off> [brightness_pct]
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.act import ActMap  # noqa: E402
from core.ha import HomeAssistantClient, WebSocketHAConnection  # noqa: E402

ACT_MAP_PATH = ROOT / "deploy" / "act_map.toml"


def resolve(target: str) -> str:
    """Map a Homie actuator name to its HA entity_id (refusing never-touch), or pass a raw
    entity_id straight through."""
    if ACT_MAP_PATH.exists():
        amap = ActMap.load(ACT_MAP_PATH)
        if target in amap.forward:
            return amap.forward[target]
        if target in amap.never_touch:
            raise SystemExit(f"refused: {target} is in [never_touch]")
    return target  # already an entity_id (or no map yet)


async def main(entity: str, state: str, pct: int) -> None:
    url, token = os.environ.get("HOMIE_HOME_URL"), os.environ.get("HOMIE_HOME_TOKEN")
    if not url or not token:
        raise SystemExit("set HOMIE_HOME_URL + HOMIE_HOME_TOKEN (source /etc/homie-ha.env)")
    if state == "off":
        cmd = {"state": "off"}
    elif pct is None:
        cmd = {"state": "on"}                       # plain on — no brightness (most compatible)
    else:
        cmd = {"state": "on", "brightness_pct": pct}
    # A sluggish hub (DIRIGERA) can take ~10s to confirm; wait generously so a working command
    # isn't reported as a timeout. Tunable via HOMIE_HOME_RESULT_TIMEOUT.
    timeout = float(os.environ.get("HOMIE_HOME_RESULT_TIMEOUT", "30"))
    ha = HomeAssistantClient(lambda: WebSocketHAConnection(url), token, result_timeout=timeout)
    await ha.start()
    try:
        await asyncio.wait_for(ha.connected.wait(), 10)
        await ha.drive(entity, cmd)
        print(f"✓ {entity} <- {cmd}")
    finally:
        await ha.stop()


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[2] not in ("on", "off"):
        raise SystemExit("usage: ha_light.py <actuator-or-entity> <on|off> [brightness_pct]")
    target, state = sys.argv[1], sys.argv[2]
    brightness = int(sys.argv[3]) if len(sys.argv) > 3 else None  # omit → plain on/off
    asyncio.run(main(resolve(target), state, brightness))
