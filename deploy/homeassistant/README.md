# Running Home Assistant

The `docker-compose.yml` here starts Home Assistant — the device layer Homie drives
(`Homie → HA → DIRIGERA → Tradfri bulbs`). It's portable: run it on the main PC now, move it
to the always-on mini-PC later by copying this folder (with `./config`).

## Start it

```
cd deploy/homeassistant
docker compose up -d            # start HA in the background
```

First boot takes ~1 minute. Then **open it in any browser on your network:**

```
http://<this-machine's-ip>:8123
```

(Find the IP with `ip addr` on Linux or `ipconfig` on Windows. On the same machine,
`http://localhost:8123` works too.) Create your account, name your home — then follow
**[../../docs/HA-SETUP.md](../../docs/HA-SETUP.md)** to pair the DIRIGERA hub and pull every
bulb into Homie's act-map.

## Everyday commands

```
docker compose ps              # is it running?
docker compose logs -f         # watch its logs (Ctrl-C to stop watching)
docker compose restart         # restart HA
docker compose down            # stop HA (your config in ./config is kept)
docker compose pull && docker compose up -d   # update to the latest HA
```

No Docker yet? `sudo apt install docker.io docker-compose-v2` (Debian/Ubuntu) or
`sudo pacman -S docker docker-compose` (Arch), then `sudo systemctl enable --now docker`.

## Two notes for the "on the main PC for now" setup

- **The main PC sleeps** (it's the on-demand GPU brain). HA — and therefore the lights —
  only respond while that PC is awake. That's fine for trying it out; it's exactly why the
  plan moves HA to the always-on **mini-PC** once you're happy. To move it: `docker compose
  down` here, copy this whole folder to the mini-PC, `docker compose up -d` there. Same bulbs,
  no re-pairing.
- **No door lock on this machine.** Per the security review, the GPU/movie PC runs an
  unsandboxed browser next to your data — keep `lock.*` in `[never_touch]` (it already is) and
  don't add a real lock until HA lives on the mini-PC. Bulbs and scenes are fine.

## Windows / macOS

Docker Desktop can't use `network_mode: host`. In `docker-compose.yml`, delete that line and
uncomment the `ports: ["8123:8123"]` block. HA still works, but it can't auto-discover the
DIRIGERA hub — you'll add the integration by the hub's IP manually (HA walks you through it).
For real device discovery, Linux on the box is the better home.
