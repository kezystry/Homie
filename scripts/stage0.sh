#!/usr/bin/env bash
# scripts/stage0.sh — bring the brain alive + turn on remote management.
#
# Run ONCE, as root, at the box's console, AFTER pulling the latest code:
#     sudo -i
#     nix-shell -p git --run 'git -C /opt/homie pull'
#     bash /opt/homie/scripts/stage0.sh
#
# It is idempotent — safe to re-run. It:
#   1. restarts homie.service and verifies it's running (applies the crash-fix),
#   2. installs os/boot/ssh.nix into /etc/nixos and wires it into the flake,
#   3. rebuilds the system (SSH + sudo for `homie`, password auth for bootstrap),
#   4. prints the LAN IP so you can SSH in from your phone.
#
# After this: SSH from the phone, paste your public key into /etc/nixos/ssh.nix,
# flip PasswordAuthentication to false, and `nixos-rebuild switch` for key-only.

set -euo pipefail

REPO="/opt/homie"
NIXOS="/etc/nixos"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root:  sudo -i  then  bash $REPO/scripts/stage0.sh" >&2
  exit 1
fi

# /etc/nixos is a git repo, and a flake build only copies GIT-TRACKED files into
# the store — a freshly cp'd module is invisible until staged. Stage everything
# before each rebuild. git isn't on PATH until this stage installs it, so fall
# back to a throwaway nix shell.
nixos_git_add() {
  if command -v git >/dev/null 2>&1; then
    git -C "$NIXOS" add -A
  else
    nix --extra-experimental-features 'nix-command flakes' \
      shell nixpkgs#git --command git -C "$NIXOS" add -A
  fi
}

echo ""
echo "== Stage 0: brain alive + remote management =="

# ── 1. Apply the crash-fix: restart the daemon and verify it stays up ─────────
echo ""
echo "-- 1/4  restarting homie.service"
systemctl restart homie
sleep 3
if systemctl is-active --quiet homie; then
  echo "   homie.service: active (running)"
else
  echo "   homie.service did NOT come up. Recent log:" >&2
  journalctl -u homie -n 30 --no-pager >&2 || true
  echo "   (Did the pull succeed? Is the b38d782 state_root fix present?)" >&2
  exit 1
fi

# ── 2. Install the SSH bootstrap module ───────────────────────────────────────
echo ""
echo "-- 2/4  installing ssh.nix into $NIXOS"
if [[ ! -f "$REPO/os/boot/ssh.nix" ]]; then
  echo "   $REPO/os/boot/ssh.nix missing — did the pull run?" >&2
  exit 1
fi
cp "$REPO/os/boot/ssh.nix" "$NIXOS/ssh.nix"
echo "   copied ssh.nix"

# ── 3. Wire ssh.nix into the flake module list (idempotent) ───────────────────
echo ""
echo "-- 3/4  wiring ssh.nix into the flake + rebuilding"
python3 - <<'PY'
import pathlib
p = pathlib.Path("/etc/nixos/flake.nix")
s = p.read_text()
if "./ssh.nix" in s:
    print("   flake.nix: ./ssh.nix already present")
elif "./nvidia-cuda.nix" in s:
    s = s.replace("./nvidia-cuda.nix",
                  "./nvidia-cuda.nix\n          ./ssh.nix", 1)
    p.write_text(s)
    print("   flake.nix: added ./ssh.nix")
else:
    raise SystemExit("   flake.nix: could not find an anchor to insert ./ssh.nix — add it by hand")
PY

# Stage the new/modified config so the flake build can see ssh.nix (git-tree
# flakes ignore untracked files).
nixos_git_add

# The base install ships with flakes off. nixos-rebuild has no flag for that, so
# enable the feature via NIX_CONFIG for this first rebuild. ssh.nix turns it on
# permanently, so later rebuilds need nothing special.
NIX_CONFIG="experimental-features = nix-command flakes" \
  nixos-rebuild switch --flake "$NIXOS#homie"
echo "   rebuild complete — sshd should be listening on :22"

# ── 4. Show the address to connect to ─────────────────────────────────────────
echo ""
echo "-- 4/4  this box's LAN addresses:"
ip -4 -o addr show scope global | awk '{print "   " $2 ": " $4}'

echo ""
echo "== Stage 0 done =="
echo "From your phone (Termius/Blink):  ssh homie@<the IP above>"
echo "Password auth is ON for bootstrap. To go key-only:"
echo "  1. on the phone, generate an ed25519 key and copy its PUBLIC half"
echo "  2. ssh in, then edit /etc/nixos/ssh.nix:"
echo "       - paste the key into users.users.homie.openssh.authorizedKeys.keys"
echo "       - change PasswordAuthentication to lib.mkForce false"
echo "  3. sudo nixos-rebuild switch --flake /etc/nixos#homie"
