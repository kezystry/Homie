"""The positive-schema privacy guard (M7) — the single source of truth for what may
cross a privacy boundary.

Homie has exactly two places where an event leaves the trusted edge: perception ingest
(`core/perceive.py:assert_emittable`, one layer before the bus) and the mesh bridge
(`core/mesh.py:PrivacyGuard.permits`, between nodes). Both call `validate()` here, so the
two enforcement points can never drift — the way they shared the old `FORBIDDEN` denylist,
but now positive: **anything not explicitly declared emittable is refused.**

Why positive, not a denylist (Charter Law 6 — "raw faces/audio and identity vectors never
cross a wire"). A denylist of six tokens is permissive by construction: a faceprint hidden
at `{"data": {"vector": [...]}}`, or under an innocuous key name, or one nesting level down,
sails through. A positive per-topic schema inverts the default — a payload is emittable only
if every key is declared and every leaf matches its declared scalar type. A float vector has
no declared home, so it is refused *structurally*, at any depth, regardless of key name. No
"is 24 floats a histogram or a faceprint?" heuristic — declared-or-refused.

Determinism + safety (the embedded-engineer's gates): the walk is iterative (no Python
recursion to blow), bounded (depth/node/list caps, fail-closed on every limit), and validates
the post-JSON-normalized shape (lists, not tuples — what actually crosses the mesh wire).

Law 8a: this file is an authority anchor. `SCHEMA_FINGERPRINT` is pinned and tested, and the
path `core/schema.py` is on the self-update authority-hint list — so a self-upgrade that
*widens* what may be emitted is frozen for the owner's explicit yes, even when the suite is
green. Stdlib only, no clock, no network.
"""
from __future__ import annotations

import hashlib
import json

# --------------------------------------------------------------------------- #
# Leaf-type tokens — a deliberately tiny, closed set. A leaf spec is one of these
# strings; a field spec is a leaf token, a ("list", elem_spec, max_len) tuple, a
# ("opaque", max_bytes) tuple, or a nested {key: field_spec} dict.
# --------------------------------------------------------------------------- #
STR = "str"     # a bounded text string
INT = "int"     # a python int (NOT bool — bool is checked first and refused for INT/NUM)
BOOL = "bool"
NUM = "num"     # a single int-or-float scalar reading (a rate, a confidence) — never a list

_LEAVES = frozenset((STR, INT, BOOL, NUM))

# Hard bounds — every one fails CLOSED (reject), because "too big/deep to check" is the most
# dangerous payload class, not the safest.
MAX_DEPTH = 6
MAX_NODES = 256
MAX_LIST_LEN = 16        # the absolute ceiling for ANY list, declared or not — a faceprint
                         # (128/512/768-d) dies here even if someone quantises it to int8.
MAX_STR_LEN = 512
MAX_PAYLOAD_BYTES = 4096


def list_of(elem_spec, max_len: int) -> tuple:
    """A bounded homogeneous list. `max_len` is clamped to MAX_LIST_LEN so no declaration can
    ever legitimise an embedding-sized array."""
    return ("list", elem_spec, min(int(max_len), MAX_LIST_LEN))


def opaque(max_bytes: int = MAX_PAYLOAD_BYTES) -> tuple:
    """An explicit, audited escape for a passthrough scalar of unknown internal shape (e.g. a
    timer's caller payload). Never recurses; counts against a byte cap; never a list/dict."""
    return ("opaque", int(max_bytes))


# --------------------------------------------------------------------------- #
# THE SCHEMA — every topic that may cross a privacy boundary, and its exact payload shape.
# Covers precisely the two guarded edges: perception ingest + the mesh allowlist
# (presence.** / motion.** / occupancy.** / security.** / node.**). A topic absent from this
# map is refused at those edges (fail-closed). Local-only topics (reason.*, briefing.*, …)
# never reach a guard and so need no entry.
#
# Note: NO covered payload legitimately carries a list, so in practice "any list anywhere is
# refused" — exactly the property that kills a faceprint. The list_of machinery exists for
# future bounded numeric fields and to make the ban structural rather than special-cased.
# --------------------------------------------------------------------------- #
SCHEMA: dict[str, dict] = {
    # --- perception ingest: a known label/zone entered a camera-allowed zone (frigate) ---
    "presence.detected": {"camera": STR, "zone": STR, "label": STR},
    # --- presence/occupancy/motion: the always-on life-shape signals (synthetic + live) ---
    "presence.arrived":  {"zone": STR, "camera": STR, "label": STR},
    "presence.departed": {"zone": STR},
    "presence.unknown":  {"zone": STR, "camera": STR},
    "occupancy.changed": {"zone": STR, "occupied": BOOL},
    "motion.detected":   {"zone": STR, "seq": INT},
    # --- security: a graduated alert; it flags the unusual, never identifies a person ---
    "security.alert": {"reason": STR, "topic": STR, "zone": STR, "novel": BOOL, "rate": NUM},
    # --- node: mesh link diagnostics (node.link.* is never forwarded, but declared for safety) ---
    "node.link.down": {"node": STR},
    "node.link.up":   {"node": STR},
    # --- desktop eyes: the active app + coarse media shape (NEVER pixels/keystrokes) ---
    "desktop.focus.changed": {"app": STR},
    # media.activity carries a live-only `title` (the watchlog reads it; the durable GIST never
    # does — gist_store.event_tokens ignores it, Charter 23a). Declaring it here permits the
    # live fact to flow on the local bus; it is not a meshed topic, so it never leaves the node.
    "media.activity": {"app": STR, "state": STR, "kind": STR, "title": STR},
}


class SchemaViolation(ValueError):
    """Raised (by the perceive wrapper) when a payload is not emittable on its topic."""


def _leaf_ok(spec: str, value) -> bool:
    """A declared leaf accepts its scalar type — or None (the absence of a value, never a
    vector). bool is checked BEFORE int so True can't masquerade as a numeric reading."""
    if value is None:
        return True
    if spec == BOOL:
        return value is True or value is False
    if spec == STR:
        return isinstance(value, str) and len(value) <= MAX_STR_LEN
    if spec == INT:
        return type(value) is int          # bool is a subclass of int — type() excludes it
    if spec == NUM:
        return (type(value) is int) or (type(value) is float)
    return False                            # unknown leaf token → refuse


def is_emittable(topic: str, payload) -> bool:
    """True iff `payload` matches the declared shape for `topic`. Pure, bounded, fail-closed.

    The whole verdict is a single iterative walk: every key must be declared, every leaf must
    match its declared type, no list may exceed MAX_LIST_LEN, and the walk may not exceed
    MAX_DEPTH / MAX_NODES. The first violation returns False — a valid payload pays the full
    walk, an invalid one bails early."""
    spec = SCHEMA.get(topic)
    if spec is None:                        # undeclared topic → refused at the boundary
        return False
    if not isinstance(payload, dict):
        return False
    # cheap pre-filter: a blob-sized payload is almost certainly imagery under an innocent key.
    try:
        if sum(len(str(v)) for v in payload.values()) > MAX_PAYLOAD_BYTES:
            return False
    except Exception:
        return False

    stack = [(payload, spec, 0)]
    nodes = 0
    while stack:
        value, fieldspec, depth = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            return False                    # too deep / too big to check → fail closed
        if isinstance(fieldspec, dict):
            if not isinstance(value, dict):
                return False
            if set(value) - set(fieldspec):  # any undeclared key
                return False
            for k, sub in fieldspec.items():
                if k in value:               # a declared key may be absent; present → walk it
                    stack.append((value[k], sub, depth + 1))
        elif isinstance(fieldspec, tuple) and fieldspec and fieldspec[0] == "list":
            _, elem, cap = fieldspec
            if not isinstance(value, list) or len(value) > min(cap, MAX_LIST_LEN):
                return False
            for item in value:
                stack.append((item, elem, depth + 1))
        elif isinstance(fieldspec, tuple) and fieldspec and fieldspec[0] == "opaque":
            _, cap = fieldspec
            if isinstance(value, (dict, list)) or len(str(value)) > cap:
                return False                 # opaque is a scalar escape, never a container
        else:                                # a leaf token
            if not _leaf_ok(fieldspec, value):
                return False
    return True


def validate(topic: str, payload) -> list[str]:
    """The shared verdict both guards call. Returns a list of human-readable reasons the
    payload is NOT emittable (empty == emittable). A list rather than a bool so the caller can
    log *why* — which key the developer must declare — instead of a silent drop."""
    if SCHEMA.get(topic) is None:
        return [f"topic {topic!r} is not declared emittable (positive-schema privacy guard)"]
    if is_emittable(topic, payload):
        return []
    return [f"payload for {topic!r} does not match its declared schema "
            f"(undeclared key, wrong type, oversized array, or too deep/large)"]


# --------------------------------------------------------------------------- #
# The recursive raw-imagery fence — for BROAD owner-facing surfaces (the cockpit) that the
# narrow positive schema can't enumerate.
#
# The mesh and perception cross only declared life-shape signals, so the positive schema fits
# them. The cockpit, by contrast, surfaces the whole owner-facing stream to the owner's OWN
# local screen — briefing text, chat replies, tile/wake telemetry — a surface too large and
# fluid to declare topic-by-topic. There the rule inverts: everything reaches the owner EXCEPT
# raw imagery. This fence enforces exactly that, and unlike the old denylist it is RECURSIVE —
# a faceprint nested at `{"data": {"vector": [...]}}` is caught, which the pre-M7 guard missed.
# --------------------------------------------------------------------------- #
FORBIDDEN_TOKENS = frozenset((
    "raw", "image", "frame", "vector", "faceprint", "crop", "embedding", "snapshot",
    "bbox", "box", "thumbnail", "pixels",
))


def _numeric_vector(value) -> bool:
    """A list with more than MAX_LIST_LEN numeric elements is an embedding/faceprint, never a
    legitimate owner-facing list (which holds dicts or short strings)."""
    if not isinstance(value, list) or len(value) <= MAX_LIST_LEN:
        return False
    return sum(1 for x in value if type(x) is int or type(x) is float) > MAX_LIST_LEN


def carries_raw_imagery(topic: str, payload) -> bool:
    """True if `topic`/`payload` carries raw imagery or an identity vector at ANY depth.
    Recursive, bounded (same depth/node caps, fail-closed: too-deep/too-big reads as imagery).
    Used by the cockpit fence; the positive schema makes this redundant on the narrow boundary
    but the two share `FORBIDDEN_TOKENS` and the vector shape, so 'what imagery is' is defined once."""
    if FORBIDDEN_TOKENS & set(topic.split(".")):
        return True
    stack = [(payload, 0)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            return True                      # too deep/large to vet → treat as imagery (fail closed)
        if isinstance(value, dict):
            if FORBIDDEN_TOKENS & {str(k).lower() for k in value}:
                return True
            for v in value.values():
                stack.append((v, depth + 1))
        elif isinstance(value, list):
            if _numeric_vector(value):
                return True
            for item in value:
                stack.append((item, depth + 1))
        elif isinstance(value, str) and len(value) > MAX_PAYLOAD_BYTES:
            return True                      # a blob string is almost certainly encoded imagery
    return False


class ImageryFence:
    """A `.permits(event)`-shaped guard for broad owner-facing surfaces: blocks only raw
    imagery / identity vectors (recursively), letting all other declared-by-policy content
    through. The cockpit's real authority is its topic allowlist (`CockpitPolicy`); this is the
    defense-in-depth that guarantees no pixels ever reach even the owner's screen."""

    def permits(self, event) -> bool:
        return not carries_raw_imagery(event.topic, event.payload or {})


# --------------------------------------------------------------------------- #
# Law 8a authority anchor: a canonical fingerprint of the emittable set. Any change — a new
# topic, a new key, a loosened leaf, a raised cap — changes this hash. The pinned value below
# is asserted by tests/test_privacy_schema.py, so the schema cannot be edited without a human
# consciously updating the pin; and `core/schema.py` is on the self-update authority-hint list,
# so a self-upgrade touching it is frozen for the owner even when green.
# --------------------------------------------------------------------------- #
def _canonical(spec) -> object:
    """A deterministic, JSON-safe form of a field spec (tuples → lists, dict keys sorted)."""
    if isinstance(spec, dict):
        return {k: _canonical(spec[k]) for k in sorted(spec)}
    if isinstance(spec, tuple):
        return [spec[0]] + [_canonical(x) for x in spec[1:]]
    return spec


def schema_fingerprint(schema: dict = SCHEMA) -> str:
    """sha256 of the canonical schema — stable across hosts, locales, and PYTHONHASHSEED."""
    canon = {t: _canonical(schema[t]) for t in sorted(schema)}
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


SCHEMA_FINGERPRINT = "sha256:928f08f774ac9a83ffb0bae86684c142f86ba22d82c3d8cf277af2acfb206ecb"
