"""HA discovery — turn the bulbs Home Assistant already sees into Homie's act-map.

The owner adopted Home Assistant with a DIRIGERA hub + Tradfri bulbs. Once HA has paired
them, every bulb is an HA `light.*` entity. The remaining chore is binding each to a
semantic Homie actuator name (`light.kitchen`) in `deploy/act_map.toml` — the allowlist the
act path enforces. Typing those by hand is error-prone; this module derives them from HA's
own entity list.

It is PURE (no I/O): `entities_to_actmap(states)` takes the result of HA's `get_states` and
returns `{actuator_name: entity_id}`. `scripts/ha_setup.py` is the thin CLI that fetches the
states over the live WebSocket and writes the toml. Splitting it this way means the naming
logic — the part that can get a room wrong — is unit-tested with no live HA.

Naming: strip the `light.` domain and vendor noise (`tradfri_`, `dirigera_`, `ikea_`, …) from
the entity_id to get a room/role slug, prefer that for stability, and fall back to the
friendly name. Collisions get the vendor word back, then a numeric suffix — never a silent
overwrite (two bulbs must never collapse to one actuator).
"""
from __future__ import annotations

import re

# Domains worth mapping as actuators by default (lights first; switches/scenes opt-in).
DEFAULT_DOMAINS = ("light",)
# Vendor / hub noise stripped from an entity slug to reveal the room/role.
VENDOR_PREFIXES = ("tradfri", "dirigera", "ikea", "smart", "signify", "hue", "zigbee")


def _slug(text: str) -> str:
    """Lowercase, non-alphanumerics → single underscores, trimmed. Stable + filename-safe."""
    s = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    return s.strip("_")


def _strip_vendor(slug: str) -> str:
    """Drop leading vendor/hub words so `tradfri_living_room` → `living_room`. Keeps the slug
    if stripping would empty it (a bulb literally named only 'tradfri')."""
    parts = [p for p in slug.split("_") if p]
    while parts and parts[0] in VENDOR_PREFIXES:
        parts = parts[1:]
    return "_".join(parts) if parts else slug


def suggest_name(entity_id: str, friendly_name: str | None = None) -> str:
    """The semantic actuator name for one entity, e.g. `light.kitchen`. Prefers the
    vendor-stripped entity slug (stable across HA restarts); falls back to the friendly name."""
    domain, _, rest = entity_id.partition(".")
    slug = _strip_vendor(_slug(rest))
    if not slug or _is_opaque(slug):         # an opaque id (light.0x00158d000…) — use the name
        slug = _slug(friendly_name or "") or slug
    return f"{domain}.{slug}"


def _is_opaque(slug: str) -> bool:
    """True for a machine id (all hex/underscore AND containing a digit), e.g. a Zigbee
    address `0x00158d0001` — not a real room word. 'cafe' (hex letters, no digit) is fine."""
    return bool(re.fullmatch(r"[0-9a-fx_]+", slug)) and any(ch.isdigit() for ch in slug)


def entities_to_actmap(states: list[dict], *, domains: tuple[str, ...] = DEFAULT_DOMAINS,
                       exclude: set[str] | None = None) -> dict[str, str]:
    """Map HA `get_states` output → `{actuator_name: entity_id}` for the chosen domains.

    `states` is HA's native shape: each item has `entity_id` and `attributes.friendly_name`.
    Collisions are resolved deterministically (vendor word restored, then `_2`, `_3`, …) so no
    two distinct entities ever fold onto one actuator. `exclude` drops entity_ids outright
    (e.g. the never-touch set)."""
    exclude = exclude or set()
    taken: dict[str, str] = {}          # actuator -> entity_id
    # Sort by entity_id for a stable, reproducible map (and deterministic collision order).
    for st in sorted(states, key=lambda s: s.get("entity_id", "")):
        eid = st.get("entity_id", "")
        if not eid or eid in exclude:
            continue
        if eid.split(".", 1)[0] not in domains:
            continue
        fname = (st.get("attributes") or {}).get("friendly_name")
        name = suggest_name(eid, fname)
        if name in taken and taken[name] != eid:
            name = _disambiguate(name, eid, taken)
        taken[name] = eid
    return dict(sorted(taken.items()))


def _disambiguate(name: str, eid: str, taken: dict[str, str]) -> str:
    """Two entities want the same actuator name. Try the full (un-stripped) entity slug, then
    a numeric suffix — anything but a silent collision."""
    domain, _, rest = eid.partition(".")
    full = f"{domain}.{_slug(rest)}"
    if full not in taken:
        return full
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    return f"{name}_{i}"


def render_act_map(actuators: dict[str, str], *, never_touch: list[str] | None = None) -> str:
    """Serialize an act-map to the same TOML shape `deploy/act_map.toml` already uses (stdlib
    `tomllib` reads but cannot write, so we hand-format). Preserves the never-touch guard."""
    never_touch = never_touch or []
    out = [
        "# The ONLY binding from Homie actuator names to Home Assistant entity_ids.",
        "# Generated by scripts/ha_setup.py from your live Home Assistant — edit freely;",
        "# an actuator with no entry here is refused, and a [never_touch] entity is never driven.",
        "",
        "[actuators]",
    ]
    width = max((len(a) + 2 for a in actuators), default=0)  # +2 for the surrounding quotes
    for actuator, entity in actuators.items():
        quoted = f'"{actuator}"'.ljust(width)
        out.append(f'{quoted} = "{entity}"')
    out += ["", "[never_touch]",
            "# Entities Homie must never control under any circumstance.",
            f"entities = [{', '.join(chr(34)+e+chr(34) for e in never_touch)}]", ""]
    return "\n".join(out)
