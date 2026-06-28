"""Canonicalize actuator values so a command and its home echo compare equal.

Homie drives structured commands (``{"state": "on", "brightness_pct": 40}``); Home
Assistant echoes state per attribute in its own units (brightness on 0-255, colour
temperature in mired). Without a shared normal form, ``CommandLog.take_echo``'s
equality test misses the echo, and the ``StateReconciler`` reads Homie's *own*
command as a human reversal — silently poisoning the friction loop.

``ha_canonical`` is that shared normal form, and it is the SINGLE SOURCE OF TRUTH:
it is injected into ``CommandLog`` (``core/act.py``) so the recorded command and the
inbound echo are both reduced to one hashable, comparable value. Both the in-process
tiles and the real HA adapter must use this one function — never a private copy — so
the two sides can never drift (the same discipline ``core/perceive.py`` follows by
sharing the positive ``core/schema.py`` validator with the mesh guard).

It normalizes UP to HA's integer units (0-255 brightness, mired) because those round
stably; the lossy direction (255 -> percent) is never taken here.
"""
from __future__ import annotations

from typing import NamedTuple


class Canon(NamedTuple):
    """A representation-independent actuator state. Hashable + comparable, which is
    all ``CommandLog`` needs to match a command against its echo."""

    state: str | None  # "on" | "off" | None (unknown)
    brightness: int | None  # 0-255, HA's native scale
    mired: int | None  # colour temperature in mired (1e6 / kelvin)


def _state(v: object) -> str | None:
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, str):
        s = v.lower()
        return s if s in ("on", "off") else None
    return None


def _pct_to_255(pct: float) -> int:
    return max(0, min(255, round(pct * 255 / 100)))


def _kelvin_to_mired(k: float) -> int:
    return round(1_000_000 / k)


def ha_canonical(value: object) -> Canon:
    """Reduce a command or echo value to its canonical form. Total (never raises on
    an odd shape) and idempotent: ``ha_canonical(ha_canonical(x)) == ha_canonical(x)``."""
    if isinstance(value, Canon):
        return value
    if isinstance(value, tuple):  # an already-canonical-ish tuple — pad/truncate to 3
        st, br, mi = (list(value) + [None, None, None])[:3]
        return Canon(_state(st) if isinstance(st, (bool, str)) else st, br, mi)
    if isinstance(value, (bool, str)):  # bare on/off
        return Canon(_state(value), None, None)
    if isinstance(value, dict):
        st = _state(value.get("state"))
        br = None
        if value.get("brightness_pct") is not None:
            br = _pct_to_255(value["brightness_pct"])
        elif value.get("brightness") is not None:
            br = max(0, min(255, int(value["brightness"])))
        mi = None
        if value.get("color_temp_kelvin"):
            mi = _kelvin_to_mired(value["color_temp_kelvin"])
        elif value.get("color_temp"):  # HA's legacy attribute is already mired
            mi = int(value["color_temp"])
        elif value.get("mired"):
            mi = int(value["mired"])
        if st is None and br is not None and br > 0:  # brightness with no state implies "on"
            st = "on"
        return Canon(st, br, mi)
    return Canon(None, None, None)  # unknown shape -> a defined, comparable value
