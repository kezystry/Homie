# Homie OS — the install walkthrough (Homie-OS-only + Proton)

A guided, checkpointed path from a Windows desktop to a running Homie cortex on
your RTX 3060. This is the **Homie-OS-only** path (Windows is replaced; you game
via Steam + Proton). For the dual-boot/keep-Windows variant, see
[`../os/INSTALL.md`](../os/INSTALL.md).

> **How to use this with me:** do one phase, then tell me "Phase N done" or paste
> any error. I'll verify you're clear to proceed and walk you into the next phase.
> Don't run a destructive step (Phase 2) until Phase 0 + 1 are green.

## The timeline at a glance

| Phase | What | Time | Risk | You'll see |
|---|---|---|---|---|
| **0** | Pre-flight & backup (the hard gate) | 1–3 h | — (protects you) | Windows data safe, BitLocker key saved, NixOS USB ready |
| **1** | Dry-run the OS in a VM | 1–2 h | none | Homie OS booting in a window — zero disk risk |
| **2** | Install Homie OS on the desktop | 1.5–3 h | **destructive** (erases Windows) | GRUB → LUKS prompt → console |
| **3** | First boot + the LLM cortex | 1–2 h (+ model DL) | low | `homie.service` up; the model answering on novelty |
| **4** | Steam + Proton (gaming layer) | ~1 h (+ game DL) | low | a game running on Homie OS |
| **5** | The always-on floor: Pi + HA + edges | days, incremental | low | lights reacting, presence, the friction loop |

Phases 0–3 get you a working, private cortex you boot into and game on. Phase 5 is
the wider colony (the Pi 24/7 floor, Home Assistant, perception) and is incremental
— each step in [`BRINGUP.md`](BRINGUP.md) is independently useful.

---

## Phase 0 — Pre-flight & backup (do this first, no shortcuts)

This is the only irreversible junction in the whole project. Everything here is
about being able to undo a mistake.

1. **Back up everything on Windows you care about** to an external drive or another
   machine. Homie-OS-only **erases the Windows install** — treat it as gone.
2. **Save your BitLocker recovery key off the machine** and *read it back* to
   confirm. In Windows (admin PowerShell): `manage-bde -protectors -get C:` — copy
   the 48-digit key somewhere off-device. (Even though you're wiping the disk, if
   anything goes sideways mid-process you may need it to read the old volume.)
3. **Confirm UEFI** (not legacy BIOS): in Windows run `msinfo32` → "BIOS Mode" must
   say *UEFI*.
4. **Disable Secure Boot** in your firmware/BIOS setup (stock NixOS/GRUB are
   unsigned). Note: signed boot (lanzaboote) + TPM-sealed unlock is the planned
   hardening step *later* — for now, Secure Boot off, passphrase at boot.
5. **Make the installer USB:** download the NixOS **minimal ISO**
   (https://nixos.org/download) and write it with Rufus/balenaEtcher/`dd`. You want
   a wired Ethernet connection for the install.
6. **Record your disk's device name.** Boot the USB later and run `lsblk` — note
   whether your target is `nvme0n1` (NVMe → partitions are `p`-suffixed:
   `nvme0n1p1`) or `sda` (SATA → `sda1`). You'll substitute this as `<DISK>`.

**Checkpoint:** Windows data backed up ✔, BitLocker key saved & verified ✔, UEFI
confirmed ✔, Secure Boot off ✔, NixOS USB boots ✔. → Tell me, and I'll set up Phase 1.

---

## Phase 1 — Dry-run the OS in a VM (zero disk risk)

Validate the config in a virtual machine *before* touching the real disk. This
catches every config error safely.

On any Linux box (or the desktop while still in Windows, via WSL2/a live USB) with
Nix installed:

```sh
mkdir ~/vmtest && cp /path/to/homie/os/boot/*.nix ~/vmtest/ && cd ~/vmtest
nixos-generate-config --dir ./gen && cp gen/hardware-configuration.nix .   # a stub HW config for the VM
# fill the <PLACEHOLDER>s in configuration.nix (timezone, keymap, password hashes via `mkpasswd -m yescrypt`)
nix flake check
nixos-rebuild build-vm --flake .#homie
./result/bin/run-nixos-vm
```

Confirm in the VM window: GRUB appears → (LUKS prompt if you wired it in the VM) →
`getty` autologins `homie` → `systemctl status homie` shows the daemon. (Put the
repo at `/opt/homie` in the VM, or the service will ImportError — that's expected
and exactly the kind of thing this dry-run surfaces.)

**Checkpoint:** the VM boots to the Homie console and `homie.service` is active (or
fails only because the repo/LLM isn't present yet). → Tell me; we go destructive next.

---

## Phase 2 — Install Homie OS on the desktop (destructive)

> **This erases the disk.** Verify `<DISK>` with `lsblk` every single command. Boot
> the NixOS USB on the desktop (wired network) and open a root shell (`sudo -i`).

**2a. Partition (whole-disk, UEFI):**

```sh
lsblk -o NAME,SIZE,MODEL                      # find your disk → set DISK
DISK=/dev/nvme0n1                             # <-- EDIT to your disk; triple-check!
sgdisk --zap-all "$DISK"                       # wipe partition table (DESTRUCTIVE)
sgdisk -n1:0:+1G  -t1:ef00 -c1:ESP        "$DISK"   # 1 GiB EFI System Partition
sgdisk -n2:0:0    -t2:8309 -c2:cryptroot  "$DISK"   # rest = LUKS root (8309 = Linux LUKS)
partprobe "$DISK"; lsblk "$DISK"               # confirm two partitions
```
(NVMe: the partitions are `${DISK}p1` / `${DISK}p2`. SATA: `${DISK}1` / `${DISK}2`.)

**2b. Encrypt + format + mount** (set `P1`/`P2` to the partition names from `lsblk`):

```sh
P1=${DISK}p1; P2=${DISK}p2                      # SATA: ${DISK}1 / ${DISK}2
cryptsetup luksFormat --type luks2 "$P2"        # set the LUKS passphrase (you type this at every boot)
cryptsetup open "$P2" cryptroot                 # mapper name MUST be 'cryptroot' (the config expects it)
mkfs.ext4 -L homie-root /dev/mapper/cryptroot
mkfs.fat  -F32 -n HOMIE-ESP "$P1"
mount /dev/mapper/cryptroot /mnt
mkdir -p /mnt/boot && mount "$P1" /mnt/boot
blkid -s UUID -o value "$P2"                    # record this → <LUKS_UUID>
```

**2c. Generate hardware config + drop in Homie's modules:**

```sh
nixos-generate-config --root /mnt              # writes /mnt/etc/nixos/hardware-configuration.nix (KEEP it)
cp /path/to/homie/os/boot/*.nix /mnt/etc/nixos/   # configuration.nix, flake.nix, + the module files
```

Homie OS is assembled from `configuration.nix` plus these modules (this release):
`nvidia-cuda.nix` (the GPU + CUDA for the LLM), `ritual.nix` (the nightly
consolidation timer), `backup.nix` (encrypted off-box backup), and the Steam/Proton
layer (Phase 4). Make sure `configuration.nix`'s `imports = [ ... ]` lists them.

Then **edit `/mnt/etc/nixos/configuration.nix`** and fill every `<PLACEHOLDER>`:
`<LUKS_UUID>` (from 2b), the password hashes (`mkpasswd -m yescrypt` for `homie` and
`root`), `<TIMEZONE>` (e.g. `Europe/Berlin`), `<KEYMAP>` (e.g. `de`/`us`),
`<NIXOS_RELEASE>` (`24.11`). Set `boot.loader.grub.useOSProber = false` (no other OS
to find). Put the repo where the service expects it (the Nix-packaged path, or
`/mnt/opt/homie` for the manual interim).

**2d. Install + reboot:**

```sh
nixos-install --root /mnt --flake /mnt/etc/nixos#homie
reboot                                          # remove the USB
```

**Checkpoint:** it reboots to GRUB → you enter the LUKS passphrase → it reaches the
Homie console. → Tell me (or paste the error); Phase 3 brings the brain online.

---

## Phase 3 — First boot + the LLM cortex

1. **Confirm the daemon:** at the console, `systemctl status homie` and
   `journalctl -u homie -b`. The bus + Remember + Supervisor + tiles should be up.
2. **Serve the model** (the cortex's LLM). Concretely: an 8B abliterated model at
   Q5_K_M served by `llama-server` on `127.0.0.1` (the decided choice — fits the
   3060's 12 GB fully on-GPU). Download the GGUF, start the server, confirm it
   answers on `http://127.0.0.1:<port>/v1/chat/completions`.
3. **Wire Reason to it:** set `HOMIE_LLM_URL` to that endpoint. The daemon then
   constructs the cortex (`Reason`) with the real client; on a *novel* event it
   wakes the model, which proposes a tool call (validated) or a spoken line — it
   never drives an actuator directly.

**Checkpoint:** a deliberately unusual event (or a test publish) wakes the model and
you see a proposal in the log. The private brain is live. → Tell me; we add gaming.

---

## Phase 4 — Steam + Proton (your gaming layer)

A minimal graphical session (Wayland + gamescope) + `programs.steam.enable` +
Proton, added as a `nixos-rebuild switch` on top of the working base (kept separate
from the first boot so a gaming-layer issue never blocks the cortex). Enable Steam
Play / Proton-GE for your titles; most run unmodified.

> Reminder (security, not a lecture): this box holds your LUKS keys, the household's
> faceprints, the pattern of life, and the mesh identity. Install games **only via
> Steam** here. Do **not** run cracked repacks (SteamRIP etc.) on this machine — they
> are a top malware/infostealer vector and would hand over the brain of your home.
> Keep any such files entirely off every Homie node.

**Checkpoint:** a Steam game launches under Proton on Homie OS.

---

## Phase 5 — The always-on floor + the edges (incremental, days)

The desktop is the on-demand cortex; the rest of the colony makes Homie *ambient*.
Each step is independently useful — full detail and order in
[`BRINGUP.md`](BRINGUP.md):

1. **Pi 24/7 floor** — `scripts/run.py` on the Raspberry Pi (UPS, high-endurance SD):
   bus + Remember + Supervisor + tiles, always on, even while the desktop games.
2. **Home Assistant pillar** (mini-PC, wired) — HAOS + Mosquitto + the Dirigera
   integration; fill `deploy/act_map.toml` (the actuator map + never-touch). → a real
   bulb obeys Homie.
3. **Perception** (Pi) — Frigate + Hailo + the USB camera → `presence.*` events.
4. **Mesh** — the Noise-IK `Link` so the Pi and the desktop cortex are one bus.
5. **The friction loop comes alive** — presence lights a room; you flip it back; the
   lighting tile learns. (Already built + tested; `scripts/spine_demo.py` shows it.)
6. **Voice + gestures**, then the **nightly ritual** systemd timer.

---

## If something breaks

- **No GRUB / won't boot:** boot the USB, `cryptsetup open <P2> cryptroot`,
  `mount /dev/mapper/cryptroot /mnt`, `nixos-enter` — fix the config, re-`install`.
- **Bad config / regret an update:** pick an older generation at the GRUB menu, or
  `nixos-rebuild --rollback switch` (every build keeps the last 20).
- **GPU/CUDA not found:** that's the `nvidia-cuda.nix` module — paste
  `nvidia-smi` / `journalctl -u homie` output and I'll debug it with you.
- **Stuck anywhere:** paste the exact command + error. That's what I'm here for.
