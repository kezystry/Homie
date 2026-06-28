# Homie — the commands (copy-paste cheat-sheet)

Everything you actually type, in order. Nothing here is a full PC reboot — `nixos-rebuild
switch` applies the changes and restarts Homie for you.

---

## 0. Get the latest code onto the box

The box runs a git checkout at `/opt/homie`. Pull the newest version:

```bash
cd /opt/homie
git pull
```

> First time only (if `/opt/homie` isn't a git checkout yet):
> ```bash
> sudo systemctl stop homie
> sudo mv /opt/homie /opt/homie.bak
> sudo git clone https://github.com/kezystry/Homie.git /opt/homie
> sudo git -C /opt/homie checkout claude/homie-overview-bo4l8v
> sudo chown -R homie:users /opt/homie
> ```

## 1. Apply OS changes + restart Homie (this is your "reboot")

Whenever the NixOS config changed (new packages like `xdotool`, the watchdog, the nightly
timer), rebuild — it applies everything and restarts the service:

```bash
sudo nixos-rebuild switch
```

If only Python code changed (no OS config), a plain restart is enough:

```bash
sudo systemctl restart homie
```

A true reboot is only needed for a kernel/driver change:

```bash
sudo reboot
```

## 2. Turn on the desktop eyes + hands (the main PC / Stremio)

Edit the config and uncomment the desktop lines, then rebuild:

```bash
sudo nano /opt/homie/os/boot/configuration.nix     # uncomment: "HOMIE_DESKTOP=1"
sudo nixos-rebuild switch
```

Quick test without editing the config (one session, current shell):

```bash
sudo HOMIE_DESKTOP=1 HOMIE_DESKTOP_DISPLAY=:0 systemctl restart homie
```

With desktop control on, you can drive playback and **close windows from chat** (`python3 -m
cockpit`): `/close` shuts the focused window; `/close stremio` closes Stremio by name. Closing is
a window-manager action (it asks the window to close), never a process-kill or a shell — only the
focused window or an app on the fixed close-allowlist (`core/desktop.py:CLOSE_TARGETS`) can be
named, so nothing arbitrary is ever targeted.

## 3. See what Homie sees — status, "now watching", recommendations

```bash
python3 /opt/homie/scripts/status.py --text --state /var/lib/homie
```

Shows: the milestone board, what Homie has learned, **▶ now watching**, and **your picks &
taste** (the recommendation page). Add `--tests` for a live pass/fail.

## 4. Check / control the camera + media stack

```bash
python3 /opt/homie/scripts/camera_setup.py --write      # regenerate go2rtc + Frigate configs
cd /opt/homie/deploy/cameras && docker compose up -d     # start live view + NVR
```

## 5. Update safely later (health-gated, auto-rollback)

```bash
cd /opt/homie && python3 scripts/update.py               # pull + run the suite; says if safe
sudo systemctl restart homie                             # apply it (if safe)
```

The **nightly** self-upgrade does this for you at 04:00 (pull → test → roll back if broken →
hold any permission change for your yes → restart). Read what it did:

```bash
cat /opt/homie/update-changelog.txt
```

## 6. If something misbehaves — roll back

```bash
sudo git -C /opt/homie reset --hard HEAD@{1}             # back to the previous version
sudo systemctl restart homie
```

Or boot an older NixOS generation from the GRUB menu at startup.

## 7. Logs / is it running?

```bash
systemctl status homie                                   # is the daemon up?
journalctl -u homie -f                                    # follow its live log
journalctl -u homie-nightly --since today                 # last night's self-upgrade
```
