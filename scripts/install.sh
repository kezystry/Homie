#!/usr/bin/env bash
# scripts/install.sh — guided Homie OS install
#
# Run as root from the NixOS live installer.
# Installs onto /dev/nvme0n1 (LUKS-encrypted root, EFI on p1).
# Usage:
#   git -C /tmp/homie pull
#   bash /tmp/homie/scripts/install.sh

set -euo pipefail

DISK="/dev/nvme0n1"
ESP="${DISK}p1"
ROOT="${DISK}p2"
MAPPER="cryptroot"
MNT="/mnt"
NIXOS_CFG="${MNT}/etc/nixos"
HOMIE_REPO="/tmp/homie"
NIXOS_RELEASE="24.11"

# ── Sanity check ──────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo -i first)." >&2
  exit 1
fi
if [[ ! -b "${DISK}" ]]; then
  echo "Target disk ${DISK} not found. Check lsblk." >&2
  exit 1
fi

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║           Homie OS — guided install                  ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Target disk : ${DISK}                           ║"
echo "║  ESP         : ${ESP}  (1 GiB FAT32)            ║"
echo "║  Root        : ${ROOT}  (LUKS2 → ext4, rest)    ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  ⚠  THIS ERASES ALL DATA ON ${DISK}              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
read -rp "Type  YES  to continue, anything else to abort: " confirm
[[ "${confirm}" == "YES" ]] || { echo "Aborted — nothing written."; exit 0; }

# ── 1. Partition ──────────────────────────────────────────────────────────────
echo ""
echo "▶  Step 1/8 — partitioning ${DISK}"
sgdisk --zap-all "${DISK}"
sgdisk \
  -n 1:0:+1G   -t 1:ef00 -c 1:"HOMIE-ESP" \
  -n 2:0:0     -t 2:8300 -c 2:"homie-root" \
  "${DISK}"
partprobe "${DISK}"
sleep 1
echo "   Partitions written."

# ── 2. LUKS ──────────────────────────────────────────────────────────────────
echo ""
echo "▶  Step 2/8 — LUKS encryption on ${ROOT}"
echo "   You will be asked to SET the disk passphrase (twice), then ENTER it once."
cryptsetup luksFormat --type luks2 "${ROOT}"
cryptsetup open "${ROOT}" "${MAPPER}"

LUKS_UUID=$(blkid -s UUID -o value "${ROOT}")
echo "   LUKS UUID: ${LUKS_UUID}"

# ── 3. Format ─────────────────────────────────────────────────────────────────
echo ""
echo "▶  Step 3/8 — formatting"
mkfs.fat -F32 -n HOMIE-ESP "${ESP}"
mkfs.ext4 -L homie-root "/dev/mapper/${MAPPER}"
echo "   Done."

# ── 4. Mount ──────────────────────────────────────────────────────────────────
echo ""
echo "▶  Step 4/8 — mounting"
mount "/dev/mapper/${MAPPER}" "${MNT}"
mkdir -p "${MNT}/boot"
mount "${ESP}" "${MNT}/boot"
echo "   / and /boot mounted."

# ── 5. Hardware config ────────────────────────────────────────────────────────
echo ""
echo "▶  Step 5/8 — generating hardware-configuration.nix"
nixos-generate-config --root "${MNT}"
echo "   Generated."

# ── 6. Drop in Homie configs ──────────────────────────────────────────────────
echo ""
echo "▶  Step 6/8 — installing Homie OS config"
cp "${HOMIE_REPO}/os/boot/configuration.nix" "${NIXOS_CFG}/configuration.nix"
cp "${HOMIE_REPO}/os/boot/flake.nix"         "${NIXOS_CFG}/flake.nix"
cp "${HOMIE_REPO}/os/boot/nvidia-cuda.nix"   "${NIXOS_CFG}/nvidia-cuda.nix"
echo "   Copied."

# ── 7. Fill placeholders ──────────────────────────────────────────────────────
echo ""
echo "▶  Step 7/8 — personalisation"
echo ""

read -rp "   Your timezone (e.g. Europe/Berlin, America/New_York): " TZ_VAL
read -rp "   Console keymap (e.g. us, de, gb): " KEYMAP_VAL

echo ""
echo "   Now set the password for the 'homie' user (the one that autologins):"
HOMIE_HASH=$(mkpasswd -m yescrypt)

echo ""
echo "   Now set the root/rescue password:"
ROOT_HASH=$(mkpasswd -m yescrypt)

# Escape for sed (hashes can contain $, /, etc.)
escape_sed() { printf '%s\n' "$1" | sed 's/[&/\]/\\&/g'; }

LUKS_UUID_ESC=$(escape_sed "${LUKS_UUID}")
TZ_ESC=$(escape_sed "${TZ_VAL}")
KEYMAP_ESC=$(escape_sed "${KEYMAP_VAL}")
HOMIE_HASH_ESC=$(escape_sed "${HOMIE_HASH}")
ROOT_HASH_ESC=$(escape_sed "${ROOT_HASH}")

sed -i \
  -e "s/<LUKS_UUID>/${LUKS_UUID_ESC}/g" \
  -e "s/<TIMEZONE>/${TZ_ESC}/g" \
  -e "s/<KEYMAP>/${KEYMAP_ESC}/g" \
  -e "s/<HOMIE_PASSWORD_HASH>/${HOMIE_HASH_ESC}/g" \
  -e "s/<ROOT_PASSWORD_HASH>/${ROOT_HASH_ESC}/g" \
  -e "s/<NIXOS_RELEASE>/${NIXOS_RELEASE}/g" \
  "${NIXOS_CFG}/configuration.nix"

echo "   Placeholders filled."

# ── 8. Copy Homie app ─────────────────────────────────────────────────────────
echo ""
echo "▶  Step 8/8 — copying Homie app to /opt/homie"
mkdir -p "${MNT}/opt"
cp -a "${HOMIE_REPO}" "${MNT}/opt/homie"
echo "   Copied."

# ── Done — hand off to nixos-install ─────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  All done. Review the config if you like:            ║"
echo "║    grep -v '#' ${NIXOS_CFG}/configuration.nix | head -40"
echo "║                                                      ║"
echo "║  Then run the installer:                             ║"
echo "║    nixos-install --root /mnt --flake /mnt/etc/nixos#homie"
echo "║                                                      ║"
echo "║  It will download ~800 MB, set root password again,  ║"
echo "║  then say 'installation finished'. Reboot after.     ║"
echo "╚══════════════════════════════════════════════════════╝"
