#!/usr/bin/env bash
# scripts/stage4.sh — Steam + Proton for games.
#
# Run as root on the box, AFTER Stage 2 (apps.nix / gamescope present) and a
#   git -C /opt/homie pull
# Idempotent. Installs steam.nix, wires it into the flake, and rebuilds. Steam
# packages are cached (no flaky download). Launch from the cockpit (/steam) or
# `gamescope -f -- steam -gamepadui`.

set -euo pipefail

REPO="/opt/homie"
NIXOS="/etc/nixos"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root:  su -  then  bash $REPO/scripts/stage4.sh" >&2
  exit 1
fi

echo ""
echo "== Stage 4: Steam + Proton =="

if ! grep -q './apps.nix' "$NIXOS/flake.nix" 2>/dev/null; then
  echo "Stage 2 (apps.nix) doesn't look applied yet — run stage2.sh first." >&2
  exit 1
fi

echo "-- installing steam.nix"
cp "$REPO/os/boot/steam.nix" "$NIXOS/steam.nix"

echo "-- wiring steam.nix into the flake + rebuilding"
python3 - <<'PY'
import pathlib
p = pathlib.Path("/etc/nixos/flake.nix")
s = p.read_text()
if "./steam.nix" in s:
    print("   flake.nix: ./steam.nix already present")
elif "./apps.nix" in s:
    s = s.replace("./apps.nix", "./apps.nix\n          ./steam.nix", 1)
    p.write_text(s)
    print("   flake.nix: added ./steam.nix")
else:
    raise SystemExit("   flake.nix: no anchor to insert ./steam.nix — add it by hand")
PY

nixos-rebuild switch --flake "$NIXOS#homie"

echo ""
echo "== Stage 4 done =="
echo "Launch Steam:  homie  -> /steam     (or)  gamescope -f -- steam -gamepadui"
echo "Reminder: install games ONLY via Steam/Proton — never cracked repacks."
