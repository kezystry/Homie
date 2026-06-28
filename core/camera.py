"""Camera — the registry and the edge contract for Homie's eyes.

This is the *foundation* the owner asked for: "build the whole foundation so I can plug in
a camera at any time, stream it live anywhere in max quality and fps." A camera becomes
real by adding one stanza to `deploy/cameras.toml`; everything downstream — the live view,
the on-device detector, the bus events — is generated from that single source of truth.

Three jobs, all stdlib:

  1. **Registry** (`CameraRegistry.load`) — parse + VALIDATE the camera list. A bad stanza
     fails loudly here, not at 3am on the Pi.
  2. **The positive zone-allowlist** (`allowed`) — a detection only crosses to the bus if its
     `(camera, zone, label)` is explicitly allowed. This is a *positive* schema (cf. the
     perception privacy guard): the default is silence, not leak. Cross-property views never
     get a detection seam at all.
  3. **Config generation** (`go2rtc_config`, `frigate_config`) — render the live-stream and
     NVR configs as plain dicts so the same allowlist drives BOTH the on-box services and the
     in-process adapter. Defense in depth: a zone the owner didn't allow doesn't exist in
     Frigate *and* would be dropped by the adapter even if it did.

What this module deliberately does NOT do: it never holds an RTSP credential (sources may
reference `${ENV}`, resolved on the box, never committed), never touches a frame, and never
decides *what the owner sees live* — live view is go2rtc over the owner's own WireGuard
tunnel (his eyes, his property, his network: not egress). Raw imagery dies at the edge; only
the structured events this allowlist permits ever leave the Pi.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# The object labels Homie's detector is allowed to track. A positive vocabulary: a stanza
# asking for a label outside this set is a typo or an overreach, and is refused at load.
KNOWN_LABELS = frozenset(
    {"person", "car", "bicycle", "motorcycle", "dog", "cat", "package"}
)


class CameraConfigError(ValueError):
    """A camera stanza is malformed or unsafe. Raised at load, never swallowed."""


@dataclass(frozen=True)
class Camera:
    """One camera, exactly as the owner declared it.

    `zones` is the POSITIVE allowlist — the only zones whose detections may become bus
    events. An empty `zones` means this camera is live-view-only: you can watch it, but it
    never emits a single detection. That is a valid, privacy-maximal choice, not a bug.

    `on_property` is the legal field-of-view assertion (Ryneš, C-212/13, see docs/SECURITY).
    A camera that is NOT wholly on the owner's property may stream live but must never run
    identity inference — `identify` is forced false for it, here, structurally.
    """

    id: str
    source: str                       # rtsp://… or ${ENV} — resolved on the box, never in-repo
    zones: frozenset[str] = frozenset()
    detect: frozenset[str] = frozenset({"person"})
    record: bool = True
    on_property: bool = True
    identify: bool = False            # returning-unknown faceprint; gated by on_property
    width: int = 0                    # 0 = let the source decide (native = max quality)
    height: int = 0
    fps: int = 0                      # 0 = native fps (no throttle on the live path)

    def allows(self, zone: str, label: str) -> bool:
        """The edge contract: does a `(zone, label)` detection on this camera cross to the bus?"""
        return zone in self.zones and label in self.detect


@dataclass(frozen=True)
class CameraRegistry:
    cameras: tuple[Camera, ...] = ()
    _by_id: dict[str, Camera] = field(default_factory=dict, repr=False)

    @classmethod
    def from_stanzas(cls, stanzas: dict[str, dict]) -> "CameraRegistry":
        cams: list[Camera] = []
        for cid, raw in stanzas.items():
            cams.append(_build_camera(cid, raw))
        reg = cls(cameras=tuple(cams), _by_id={c.id: c for c in cams})
        return reg

    @classmethod
    def load(cls, path: Path | str) -> "CameraRegistry":
        text = Path(path).read_text("utf-8")
        raw = tomllib.loads(text)
        return cls.from_stanzas(raw.get("camera", {}))

    def get(self, camera_id: str) -> Camera | None:
        return self._by_id.get(camera_id)

    def allowed(self, camera_id: str, zone: str, label: str) -> bool:
        """The single gate the adapter asks. Unknown camera → False (fail closed)."""
        cam = self._by_id.get(camera_id)
        return bool(cam and cam.allows(zone, label))

    # ----------------------------------------------------------------- config gen
    def go2rtc_config(self) -> dict:
        """The live-stream config. Every camera is published by its SOURCE codec, untouched —
        no transcode. That is what 'max quality and fps' means concretely: go2rtc passes the
        camera's native H.264/H.265 straight to WebRTC, so the owner sees exactly what the
        sensor produces, at the sensor's frame rate, with sub-second latency."""
        streams = {c.id: [c.source] for c in self.cameras}
        return {
            "streams": streams,
            # WebRTC is the low-latency live path; RTSP/HLS remain available as fallbacks.
            "webrtc": {"listen": ":8555"},
            "api": {"listen": ":1984"},
        }

    def frigate_config(self) -> dict:
        """The NVR + on-device detector config. Detection runs on the Hailo-8 at the edge;
        only the allowlisted zones exist here. Zone *coordinates* are drawn by the owner in
        the Frigate UI — we emit the zone NAME (the allowlist) and leave coordinates for him,
        because a polygon is a per-install fact the repo must not invent."""
        cameras: dict[str, dict] = {}
        for c in self.cameras:
            detect: dict = {"enabled": bool(c.zones)}
            if c.width and c.height:
                detect["width"] = c.width
                detect["height"] = c.height
            if c.fps:
                detect["fps"] = c.fps
            cameras[c.id] = {
                "ffmpeg": {
                    "inputs": [{"path": c.source, "roles": ["detect", "record"]}]
                },
                "detect": detect,
                "record": {"enabled": c.record},
                "objects": {"track": sorted(c.detect)},
                # The allowlist, rendered: only these zones exist for Frigate to fire on.
                "zones": {z: {"coordinates": ""} for z in sorted(c.zones)},
            }
        return {
            "detectors": {"hailo": {"type": "hailo8l", "device": "PCIe"}},
            "cameras": cameras,
        }


# --------------------------------------------------------------------------- #
# Minimal YAML emitter (go2rtc + Frigate read YAML; we have no third-party deps)
# --------------------------------------------------------------------------- #
def to_yaml(value, _indent: int = 0) -> str:
    """Serialize the config dicts to YAML. Deliberately tiny: it handles exactly the shapes
    `go2rtc_config`/`frigate_config` produce (nested dicts, lists, str/int/bool/empty). Not a
    general YAML library — just enough to write two config files deterministically, stdlib-only."""
    pad = "  " * _indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n"
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:\n{to_yaml(v, _indent + 1)}")
            else:
                out.append(f"{pad}{k}: {_scalar(v)}\n")
        return "".join(out)
    if isinstance(value, list):
        if not value:
            return pad + "[]\n"
        out = []
        for item in value:
            if isinstance(item, (dict, list)) and item:
                inner = to_yaml(item, _indent + 1)
                first, rest = inner.split("\n", 1)
                out.append(f"{pad}- {first.strip()}\n{rest}")
            else:
                out.append(f"{pad}- {_scalar(item)}\n")
        return "".join(out)
    return pad + _scalar(value) + "\n"


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v == {} or v is None:
        return "{}" if v == {} else "null"
    s = str(v)
    # quote anything YAML might misread (empty, leading special, embedded colon/${})
    if s == "" or s[0] in "!&*?{}[],#|>@`\"'%-" or ": " in s or "${" in s:
        return '"' + s.replace('"', '\\"') + '"'
    return s


# --------------------------------------------------------------------------- #
# Stanza → Camera (all validation lives here, so a bad config dies at load)
# --------------------------------------------------------------------------- #
def _build_camera(cid: str, raw: dict) -> Camera:
    if not cid or not isinstance(cid, str):
        raise CameraConfigError(f"camera id must be a non-empty string, got {cid!r}")
    source = raw.get("source", "")
    if not isinstance(source, str) or not source.strip():
        raise CameraConfigError(f"camera {cid!r}: 'source' (rtsp url) is required")

    zones = frozenset(raw.get("zones", []))
    detect = frozenset(raw.get("detect", ["person"]))
    bad = detect - KNOWN_LABELS
    if bad:
        raise CameraConfigError(
            f"camera {cid!r}: unknown detect labels {sorted(bad)}; "
            f"allowed: {sorted(KNOWN_LABELS)}"
        )

    on_property = bool(raw.get("on_property", True))
    # The privacy red line, enforced structurally: identity inference is impossible on a
    # camera that isn't wholly on your property, regardless of what the stanza asks for.
    identify = bool(raw.get("identify", False)) and on_property

    return Camera(
        id=cid,
        source=source,
        zones=zones,
        detect=detect,
        record=bool(raw.get("record", True)),
        on_property=on_property,
        identify=identify,
        width=int(raw.get("width", 0)),
        height=int(raw.get("height", 0)),
        fps=int(raw.get("fps", 0)),
    )
