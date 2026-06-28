#!/usr/bin/env python3
"""camera_setup — turn deploy/cameras.toml into live (go2rtc) + NVR (Frigate) configs.

This is the "plug in a camera at any time" button. Edit deploy/cameras.toml (add a stanza,
list its zones), run this, and Homie's eyes are configured — same allowlist driving the live
stream, the on-device detector, and the bus adapter.

Usage:
    python3 scripts/camera_setup.py                  # dry run: print both configs
    python3 scripts/camera_setup.py --write          # write deploy/cameras/{go2rtc,frigate}.yml
    python3 scripts/camera_setup.py --cameras path/to/cameras.toml

What it does NOT do: it never touches a credential (sources keep their ${RTSP_PW}
placeholder, resolved on the box from /etc/homie-cameras.env), never reaches the internet,
and never invents a zone polygon — you draw each zone once in the Frigate UI; this names them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.camera import CameraRegistry, to_yaml  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render go2rtc + Frigate configs from cameras.toml")
    ap.add_argument("--cameras", default=str(ROOT / "deploy" / "cameras.toml"))
    ap.add_argument("--write", action="store_true", help="write the configs (default: print)")
    ap.add_argument("--out", default=str(ROOT / "deploy" / "cameras"))
    args = ap.parse_args(argv)

    path = Path(args.cameras)
    if not path.exists():
        print(f"no camera config at {path} — add a [camera.<name>] stanza first", file=sys.stderr)
        return 1

    reg = CameraRegistry.load(path)
    if not reg.cameras:
        print("cameras.toml has no [camera.*] stanzas yet — Homie has no eyes (that's valid).")
        return 0

    go2rtc = to_yaml(reg.go2rtc_config())
    frigate = to_yaml(reg.frigate_config())

    names = ", ".join(c.id for c in reg.cameras)
    if not args.write:
        print(f"# {len(reg.cameras)} camera(s): {names}\n")
        print("# ===== go2rtc.yml (live, max-quality passthrough) =====")
        print(go2rtc)
        print("# ===== frigate.yml (NVR + Hailo detect, zone-allowlist) =====")
        print(frigate)
        print("# dry run — pass --write to save these under deploy/cameras/")
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "go2rtc.yml").write_text(go2rtc, "utf-8")
    (out / "frigate.yml").write_text(frigate, "utf-8")
    print(f"wrote {out/'go2rtc.yml'} and {out/'frigate.yml'} for {len(reg.cameras)} camera(s): {names}")
    print("next: draw each zone's shape in the Frigate UI, then restart the camera stack.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
