#!/usr/bin/env bash
# scripts/stage2.sh — movies first: NVIDIA driver + gamescope + Stremio.
#
# Run as root on the box (over SSH from your phone is fine), AFTER Stage 0 and a
#   git -C /opt/homie pull
# to get the latest config. Idempotent — safe to re-run.
#
# It un-neuters the GPU module to the real DRIVER (CUDA toolkit stays OFF — no
# flaky download), adds the launch-on-command app layer (gamescope + Stremio +
# mpv + the `homie-watch` command), wires it into the flake, and rebuilds. After
# it finishes you run `homie-watch` to open Stremio fullscreen.

set -euo pipefail

REPO="/opt/homie"
NIXOS="/etc/nixos"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root:  su -  then  bash $REPO/scripts/stage2.sh" >&2
  exit 1
fi

# Stage new/modified config so the git-tree flake build can see it.
nixos_git_add() {
  if command -v git >/dev/null 2>&1; then
    git -C "$NIXOS" add -A
  else
    nix --extra-experimental-features 'nix-command flakes' \
      shell nixpkgs#git --command git -C "$NIXOS" add -A
  fi
}

echo ""
echo "== Stage 2: movies first (driver + gamescope + Stremio) =="

# ── 1. Real GPU driver module (CUDA toolkit stays off by default) ─────────────
echo ""
echo "-- 1/4  installing the real nvidia-cuda.nix (driver only; CUDA off)"
cp "$REPO/os/boot/nvidia-cuda.nix" "$NIXOS/nvidia-cuda.nix"
echo "   copied (homie.gpu.cuda.enable defaults false — no flaky download)"

# ── 2. App layer ──────────────────────────────────────────────────────────────
echo ""
echo "-- 2/4  installing apps.nix (gamescope + Stremio + mpv + homie-watch)"
cp "$REPO/os/boot/apps.nix" "$NIXOS/apps.nix"
echo "   copied"

# ── 3. Wire apps.nix into the flake (idempotent) ──────────────────────────────
echo ""
echo "-- 3/4  wiring apps.nix into the flake + rebuilding"
python3 - <<'PY'
import pathlib
p = pathlib.Path("/etc/nixos/flake.nix")
s = p.read_text()
if "./apps.nix" in s:
    print("   flake.nix: ./apps.nix already present")
elif "./nvidia-cuda.nix" in s:
    s = s.replace("./nvidia-cuda.nix",
                  "./nvidia-cuda.nix\n          ./apps.nix", 1)
    p.write_text(s)
    print("   flake.nix: added ./apps.nix")
else:
    raise SystemExit("   flake.nix: no anchor to insert ./apps.nix — add it by hand")
PY

nixos_git_add
NIX_CONFIG="experimental-features = nix-command flakes" \
  nixos-rebuild switch --flake "$NIXOS#homie"
echo "   rebuild complete"

# ── 4. Confirm the GPU is live ────────────────────────────────────────────────
echo ""
echo "-- 4/4  GPU check"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || \
    echo "   nvidia-smi present but query failed — check the card/driver on hardware"
else
  echo "   nvidia-smi not found yet (it ships with the driver) — check after reboot"
fi

echo ""
echo "== Stage 2 done =="
echo "Watch movies:  homie-watch    (opens Stremio fullscreen; quit returns to console)"
echo "If gamescope complains about the display, run it from the physical console"
echo "(tty1), not over SSH — SSH has no local display to grab."
