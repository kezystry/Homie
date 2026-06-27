# Installing Homie OS (dual-boot)

This installs the Homie reasoning node onto a machine **alongside an existing
OS**, on a separate LUKS-encrypted root partition. The existing OS is preserved
and stays bootable; Homie's GRUB menu chainloads it via `os-prober`.

> **Read this whole document before starting.** Partitioning is destructive if
> done wrong. Homie never writes to the existing OS partition in normal
> operation, but the *install* step edits the partition table and the ESP.

The config files referenced here live in [`os/boot/`](boot/): `configuration.nix`
and `flake.nix`. They are templates — copy them into `/etc/nixos/` alongside the
machine's generated `hardware-configuration.nix` (step 5).

## 0. Prerequisites

- **UEFI firmware** (not legacy BIOS/CSM). On a running Linux:
  `[ -d /sys/firmware/efi ] && echo UEFI || echo BIOS`.
- **A full backup** of the existing OS and any data you care about.
- **Secure Boot disabled** (stock NixOS/GRUB are unsigned).
- **Free space** for Homie — shrink the existing OS first; **60–100 GB** suggested.
- A **NixOS installer USB** (https://nixos.org/download) and a wired network.

Back up the partition table first: `sudo sfdisk -d /dev/<DISK> > ~/parttable.txt`.

Placeholders used throughout: `<DISK>` (e.g. `nvme0n1`/`sda`), `<ESP>` (EFI
System Partition), `<ROOT>` (the new partition for LUKS). **NVMe partitions are
`p`-suffixed (`/dev/nvme0n1p3`); SATA is not (`/dev/sda3`)** — adjust the examples.

## 1. Shrink the existing OS

Never resize a mounted filesystem.

- **Windows:** Disk Management → *Shrink Volume*. Disable Fast Startup and
  suspend BitLocker first. Leave EFI/Recovery partitions alone.
- **Linux:** boot a live USB, then `e2fsck -f` + `resize2fs` the root, and shrink
  the partition with `parted`/`gdisk`. (XFS can't shrink — plan around it.)

You should end with **unallocated free space** on `<DISK>`.

## 2. Create partitions

```sh
lsblk -o NAME,SIZE,FSTYPE,PARTTYPENAME,MOUNTPOINTS
sudo gdisk -l /dev/<DISK>        # note the existing ESP partition number
```

- **Reuse the existing ESP** if it is ≥ 512 MiB — a single ESP holds multiple
  bootloaders. Set `<ESP>` to it and **do not reformat it.** Create a new ~1 GiB
  FAT32 ESP (type `EF00`) only if the existing one is tiny.
- **Create the LUKS root** in the free space (`gdisk` → `n`, type `8300` → `w`).
  Set `<ROOT>` to it.

## 3. Create and open the LUKS container

```sh
sudo cryptsetup luksFormat --type luks2 /dev/<ROOT>   # set the disk passphrase
sudo cryptsetup open /dev/<ROOT> cryptroot            # mapper name used by the config
sudo blkid -s UUID -o value /dev/<ROOT>               # record this -> <LUKS_UUID>
```

Use the UUID of the **raw partition** `/dev/<ROOT>`, not the opened mapper.

## 4. Format and mount

```sh
sudo mkfs.ext4 -L homie-root /dev/mapper/cryptroot
# Only if you CREATED a new ESP (never on a reused one):
# sudo mkfs.fat -F32 -n HOMIE-ESP /dev/<ESP>
sudo mount /dev/mapper/cryptroot /mnt
sudo mkdir -p /mnt/boot
sudo mount /dev/<ESP> /mnt/boot          # ESP at /boot matches efiSysMountPoint
```

## 5. Generate hardware config and drop in Homie's modules

```sh
sudo nixos-generate-config --root /mnt   # writes hardware-configuration.nix (keep it)

sudo cp /path/to/homie/os/boot/configuration.nix /mnt/etc/nixos/configuration.nix
sudo cp /path/to/homie/os/boot/flake.nix          /mnt/etc/nixos/flake.nix
# hardware-configuration.nix stays as generated, beside these.

# The daemon runs from /opt/homie. Clone it as a GIT CHECKOUT (not a copy) so the box
# has an update channel from day one (see "Updating Homie" below):
sudo mkdir -p /mnt/opt
sudo git clone https://github.com/kezystry/Homie.git /mnt/opt/homie
# (offline install? fall back to `cp -a /path/to/homie /mnt/opt/homie`, then convert it to a
#  checkout later with the bootstrap in "Updating Homie".)
```

Edit `/mnt/etc/nixos/configuration.nix` and fill in every `<PLACEHOLDER>`:
`<LUKS_UUID>`, the password hashes (`mkpasswd -m yescrypt`), `<TIMEZONE>`,
`<KEYMAP>`, and `<NIXOS_RELEASE>` (must match the flake's `nixpkgs.url`).

## 6. Install

```sh
sudo nixos-install --root /mnt --flake /mnt/etc/nixos#homie
# (non-flake fallback: sudo nixos-install --root /mnt)
sudo reboot
```

## 7. First boot

1. GRUB shows **Homie** (default) and the **existing OS** (found by os-prober).
2. Select Homie → enter the **LUKS passphrase** to unlock root in initrd.
3. The system boots headless; `getty` autologins `homie` on tty1.
4. `homie.service` starts `python3 /opt/homie/scripts/run.py`. Check:
   `systemctl status homie` · `journalctl -u homie -b`.

If the existing OS is missing from the menu: confirm it's a UEFI install, ensure
Windows isn't hibernated, then `sudo nixos-rebuild boot` to re-run os-prober.
os-prober mounts the other OS **read-only and transiently** — Homie never writes
to it.

## Updating Homie

The box runs a **git checkout** at `/opt/homie`, so updates are pull + health-check +
restart. The helper does the health check for you and refuses to call an update "safe"
unless the full test suite passes:

```sh
cd /opt/homie
python3 scripts/update.py            # pull + run the suite; reports safe / not-safe
sudo systemctl restart homie         # apply it (or: python3 scripts/update.py --restart)
```

Roll back a bad update:

```sh
sudo git -C /opt/homie reset --hard HEAD@{1}   # previous commit
sudo systemctl restart homie                   # (or pick an older NixOS generation at GRUB)
```

**One-time bootstrap** if an existing box has a *copied* `/opt/homie` (older installs used
`cp -a`, which is not a git repo and cannot pull):

```sh
sudo systemctl stop homie
sudo mv /opt/homie /opt/homie.bak                              # keep the old copy as a backup
sudo git clone https://github.com/kezystry/Homie.git /opt/homie
sudo chown -R homie:users /opt/homie                           # future pulls need no sudo
sudo systemctl start homie
```

The repo is public, so the clone needs no credentials. `scripts/update.py` runs entirely on
the box (stdlib only) and never grants Homie new authority — it only decides whether new
*code* is safe to run; this is the channel the nightly self-upgrade (roadmap M11) builds on.

## Recovery / self-healing

NixOS gives OS-level self-healing on top of the supervisor's tile restarts:

- Every `nixos-rebuild switch` builds a new **generation** and leaves the old one
  intact and bootable — a bad update never destroys a working system.
- Recover with `sudo nixos-rebuild --rollback switch`, or pick an older
  generation at the GRUB menu (`configurationLimit = 20`).
- Rescue from the installer USB: `cryptsetup open /dev/<ROOT> cryptroot`,
  `mount /dev/mapper/cryptroot /mnt`, `nixos-enter`.

The dual-boot relationship is one-directional: Homie can *boot* the existing OS,
but never modifies it.
