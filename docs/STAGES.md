# Bring-up stages — the runbook

The desktop reasoning node is installed. This is the staged path from a fresh box
to the full two-layer system. Each stage is one script, run as root on the box
(over SSH from your phone after Stage 0). All commands assume the repo at
`/opt/homie`. Pull latest first: `git -C /opt/homie pull`.

> Until Stage 0's rebuild lands, `git` isn't on PATH yet — bootstrap a pull with:
> `nix --extra-experimental-features 'nix-command flakes' shell nixpkgs#git --command git -C /opt/homie pull`

| Stage | What you get | Command |
|------:|--------------|---------|
| **0** | Brain alive + SSH/sudo + flakes & git permanent | `bash /opt/homie/scripts/stage0.sh` |
| **1** | Verify Layer 1 (the hidden brain) | `systemctl status homie` · `journalctl -u homie -f` |
| **2** | Movies: driver + gamescope + Stremio | `bash /opt/homie/scripts/stage2.sh` then `homie-watch` |
| **3** | CUDA toolkit + LLM cortex on the GPU | (set `homie.gpu.cuda.enable`, serve llama-server — see below) |
| **4** | Steam + Proton | `bash /opt/homie/scripts/stage4.sh` then `homie` → `/steam` |
| **5** | Layer 2 cockpit | `homie` (already shipped with Stage 0's pull) |

## Stage 0 — brain alive + remote management
Become root with `su -` (the **root** password from install — `sudo` won't work
until this stage grants it). Then `stage0.sh`:
- restarts `homie.service` and verifies `active (running)` (applies the crash-fix),
- installs `ssh.nix`: SSH + sudo for `homie`, **flakes + git enabled permanently**,
- rebuilds and prints the LAN IP.

Then SSH from the phone: `ssh homie@<IP>`. To go key-only, paste your public key
into `/etc/nixos/ssh.nix` `authorizedKeys.keys`, set `PasswordAuthentication` to
`lib.mkForce false`, and `sudo nixos-rebuild switch --flake /etc/nixos#homie`.

## Stage 2 — movies first
`stage2.sh` un-neuters the GPU to the **driver only** (`homie.gpu.cuda.enable`
stays off — no flaky CUDA download), adds `apps.nix` (gamescope + Stremio + mpv +
the `homie-watch` and `homie` commands), rebuilds, and checks `nvidia-smi`.
Watch a movie: `homie-watch`. Run it from the **physical console**, not SSH — SSH
has no local display for gamescope to grab.

## Stage 3 — the LLM cortex (the one flaky download)
The CUDA toolkit isn't cached; it's fetched from developer.download.nvidia.com.
On an unstable link it drops mid-transfer. When we reach this stage we'll pick a
resume-capable fetch (curl `-C -` loop / aria2c / a mirror) before:
1. set `homie.gpu.cuda.enable = true;` (in `nvidia-cuda.nix` or an overlay) and rebuild,
2. serve an 8B model with `llama-server` on the 3060,
3. add `HOMIE_LLM_URL=http://127.0.0.1:8080/v1/chat/completions` to the service env
   so `run.py` wires the Reason cortex (it logs "reasoning cortex up against …").
The cockpit chat (`homie`) answers from this model once it's serving.

## Stage 4 — Steam + Proton
`stage4.sh` adds `steam.nix` (Steam + a gamescope session) and rebuilds. Launch
from the cockpit (`homie` → `/steam`) or `gamescope -f -- steam -gamepadui`.
**Install games only via Steam/Proton — never cracked repacks.**

## Stage 5 — the Layer 2 cockpit
Shipped already (Stage 0's pull). `homie` opens the curses cockpit: a status
feed, chat with the brain, an app launcher (`/stremio`, `/steam`), and a **live
camera pane** rendered in the terminal's own colours (no web). **Arrow keys**
move focus between panes; **Enter** on a focused pane activates it (the camera's
crisp full view is `mpv --vo=drm`; apps launch fullscreen). Type + Enter chats
with the brain; `/cam` toggles the camera pane; `/help` lists commands.

The camera pane stays hidden until a webcam is present, then appears on its own.
Over SSH from a phone (256-colour) the thumbnail is a real picture; on the box's
bare console it falls back to coarser colour. Pixels read the local device
directly and never cross the bus. The cockpit reaches the brain over a local
0600 unix socket (read + chat only — it can drive no actuators).
