"""Child-side tile harness — runs one tile as a subprocess.

Speaks the tile wire protocol (PROTOCOL.md) as line-delimited JSON over stdin/
stdout. stdout is protocol-only; everything the tile does (act/emit/speak/log)
becomes an outbound message the parent forwards through its Context. This is the
one place tile code is loaded inside an isolated process.

    python3 -m core.tile_harness <tile_dir>
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from core.tile import (
    ActionRef,
    Event,
    FrictionSignal,
    InvalidManifest,
    TileContext,
    TileState,
    load_manifest,
    load_tile,
)


def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _friction(d: dict) -> FrictionSignal:
    d = dict(d)
    if d.get("reverses"):
        d["reverses"] = ActionRef(**d["reverses"])
    return FrictionSignal(**d)


def _make_ctx(manifest) -> TileContext:
    async def emit(event: Event) -> None:
        _write({"type": "emit", "event": asdict(event)})

    async def act(actuator: str, value) -> None:
        _write({"type": "act", "actuator": actuator, "value": value})

    async def speak(text: str) -> None:
        _write({"type": "speak", "text": text})

    async def recall(topic, zone, when):  # behavioral recall isn't bridged to subprocess tiles
        raise RuntimeError("recall is not available to out-of-process tiles")

    def log_fn(level: str, msg: str) -> None:
        _write({"type": "log", "level": level, "msg": msg})

    return TileContext(manifest, emit=emit, act=act, speak=speak, log_fn=log_fn, recall=recall)


async def _stdin_reader() -> asyncio.StreamReader:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    return reader


async def main(tile_dir: str) -> None:
    manifest = load_manifest(Path(tile_dir) / "tile.toml")
    reader = await _stdin_reader()
    s: dict = {}

    async for raw in reader:
        msg = json.loads(raw)
        kind = msg["type"]

        if kind == "init":
            if isinstance(manifest, InvalidManifest):
                _write({"type": "error", "error": "; ".join(manifest.errors)})
                return
            tile_cls, learn_fn, health_fn = load_tile(manifest)
            state = TileState(Path(msg.get("state_dir") or (manifest.path / "state")))
            tile = tile_cls()
            tile.manifest = manifest
            tile.state = state
            s.update(tile=tile, learn=learn_fn, health=health_fn, state=state, ctx=_make_ctx(manifest))
            _write({"type": "ready"})

        elif kind == "event":
            try:
                await s["tile"].on_event(Event(**msg["event"]), s["ctx"])
            except Exception as ex:
                _write({"type": "error", "error": repr(ex)})
            else:
                _write({"type": "done"})

        elif kind == "friction":
            try:
                if s["learn"]:
                    await s["learn"](s["state"], _friction(msg["signal"]))
            except Exception as ex:
                _write({"type": "error", "error": repr(ex)})
            else:
                _write({"type": "done"})

        elif kind == "call":
            try:
                value = await getattr(s["tile"], msg["fn"])(s["ctx"], **msg.get("args", {}))
            except Exception as ex:
                _write({"type": "error", "error": repr(ex)})
            else:
                _write({"type": "result", "value": value})

        elif kind == "health":
            health = s.get("health")
            ok = bool(await health(s["state"])) if health else True
            _write({"type": "health", "ok": ok})

        elif kind == "stop":
            break


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
