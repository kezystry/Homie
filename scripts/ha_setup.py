#!/usr/bin/env python3
"""ha_setup — discover every bulb your Home Assistant sees and write Homie's act-map.

Run this once after Home Assistant has paired your DIRIGERA hub + Tradfri bulbs (see
docs/HA-SETUP.md). It connects to HA over the same WebSocket the live adapter uses, asks for
all states (`get_states`), turns the `light.*` entities into semantic Homie actuator names,
and prints — or writes — `deploy/act_map.toml`.

Usage:
    export HOMIE_HOME_URL=ws://mini-pc.local:8123/api/websocket
    export HOMIE_HOME_TOKEN=<long-lived access token from HA → Profile → Security>

    python3 scripts/ha_setup.py                 # dry run: print the proposed act-map
    python3 scripts/ha_setup.py --write         # write deploy/act_map.toml (backs up the old)
    python3 scripts/ha_setup.py --domains light,switch,scene
    python3 scripts/ha_setup.py --url ws://... --token ...   # override the env

Nothing leaves your machines: this talks ONLY to your local HA, never the internet. It
preserves the existing [never_touch] guard and never overwrites without --write.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.act import ActMap  # noqa: E402
from core.ha_discovery import entities_to_actmap, render_act_map  # noqa: E402

ACT_MAP_PATH = ROOT / "deploy" / "act_map.toml"


async def fetch_states(url: str, token: str, *, timeout: float = 10.0) -> list[dict]:
    """Auth to HA and pull `get_states` once, then close. Reuses the real WebSocket
    connection seam (core/ha.py) so this exercises the same transport the daemon uses."""
    from core.ha import WebSocketHAConnection
    conn = WebSocketHAConnection(url)
    await conn.connect()
    try:
        hello = await asyncio.wait_for(conn.recv(), timeout)
        if hello.get("type") != "auth_required":
            raise ConnectionError(f"unexpected HA greeting: {hello.get('type')!r}")
        await conn.send({"type": "auth", "access_token": token})
        reply = await asyncio.wait_for(conn.recv(), timeout)
        if reply.get("type") != "auth_ok":
            raise ConnectionError("HA auth failed — check HOMIE_HOME_TOKEN")
        await conn.send({"id": 1, "type": "get_states"})
        while True:
            msg = await asyncio.wait_for(conn.recv(), timeout)
            if msg.get("id") == 1 and msg.get("type") == "result":
                if not msg.get("success"):
                    raise ConnectionError("HA get_states failed")
                return msg.get("result") or []
    finally:
        await conn.close()


def _existing_never_touch() -> list[str]:
    if ACT_MAP_PATH.exists():
        try:
            return sorted(ActMap.load(ACT_MAP_PATH).never_touch)
        except Exception:
            pass
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Discover HA bulbs and write Homie's act-map.")
    ap.add_argument("--url", default=os.environ.get("HOMIE_HOME_URL"))
    ap.add_argument("--token", default=os.environ.get("HOMIE_HOME_TOKEN"))
    ap.add_argument("--domains", default="light",
                    help="comma-separated HA domains to map (default: light)")
    ap.add_argument("--write", action="store_true", help="write deploy/act_map.toml")
    args = ap.parse_args(argv)

    if not args.url or not args.token:
        print("error: set HOMIE_HOME_URL and HOMIE_HOME_TOKEN (or pass --url/--token).\n"
              "       See docs/HA-SETUP.md to create a long-lived token in Home Assistant.",
              file=sys.stderr)
        return 2

    domains = tuple(d.strip() for d in args.domains.split(",") if d.strip())
    never_touch = _existing_never_touch()
    try:
        states = asyncio.run(fetch_states(args.url, args.token))
    except Exception as ex:
        print(f"error: could not reach Home Assistant at {args.url}: {ex}", file=sys.stderr)
        return 1

    actuators = entities_to_actmap(states, domains=domains, exclude=set(never_touch))
    toml = render_act_map(actuators, never_touch=never_touch)

    if not actuators:
        print(f"No entities found in domains {domains}. Is HA paired with your bulbs yet?",
              file=sys.stderr)
        return 1

    print(f"Discovered {len(actuators)} actuator(s) across {domains}:\n", file=sys.stderr)
    if args.write:
        if ACT_MAP_PATH.exists():
            backup = ACT_MAP_PATH.with_suffix(".toml.bak")
            backup.write_text(ACT_MAP_PATH.read_text("utf-8"), "utf-8")
            print(f"  (backed up the old map to {backup.name})", file=sys.stderr)
        ACT_MAP_PATH.write_text(toml, "utf-8")
        print(f"  wrote {ACT_MAP_PATH}", file=sys.stderr)
    else:
        print("  (dry run — re-run with --write to save)\n", file=sys.stderr)
    print(toml)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
