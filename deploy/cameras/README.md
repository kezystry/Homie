# Camera stack (box-side) — live view, NVR, private remote access

This folder is the **on-the-box** half of Homie's eyes. The in-process half (the registry,
the privacy-clean detection adapter, the config generator) lives in `core/camera.py`,
`perception/frigate_adapter.py`, and `scripts/camera_setup.py`. The full design is in
[`docs/CAMERA.md`](../../docs/CAMERA.md).

## What's here

- `docker-compose.yml` — go2rtc (live, native-quality passthrough) + Frigate (NVR + Hailo-8
  detection).
- `go2rtc.yml`, `frigate.yml` — **generated**, not hand-written. Run
  `python3 scripts/camera_setup.py --write` to (re)create them from `deploy/cameras.toml`.
- `wireguard/wg0.conf.template` — the private tunnel for watching from anywhere without
  exposing a camera to the internet.
- `media/` — Frigate's recordings land here (created on first run; back it up / size for it).

## Bring-up (once)

```
python3 scripts/camera_setup.py --write          # 1. generate the configs
echo 'RTSP_PW=your-camera-password' | sudo tee /etc/homie-cameras.env   # 2. the secret, on the box only
cd deploy/cameras && docker compose up -d        # 3. start live + NVR
```

Then open `http://<box-ip>:5000` (Frigate) and **draw each zone** you named in
`cameras.toml` — a zone is a polygon on the image, a per-install fact the repo can't invent.
Live view is `http://<box-ip>:1984` (go2rtc), on your network or over WireGuard.

## Plug in another camera, any time

1. Add a `[camera.<name>]` stanza to `deploy/cameras.toml`.
2. `python3 scripts/camera_setup.py --write && docker compose up -d` (recreates configs,
   restarts the stack).
3. Draw the new zones in Frigate. Done.

## The lines that don't move

- **A frame never leaves the Pi.** Only `(camera, zone, label)` notes cross to Homie, and
  only for zones you allowlisted in `cameras.toml`. Enforced in `frigate_adapter.py`.
- **The street isn't yours to watch.** A camera with `on_property = false` can stream live
  but never runs identity inference (forced in `core/camera.py`). See `docs/SECURITY.md`.
- **No camera is ever exposed to the internet.** Remote viewing is WireGuard-only — you join
  your own network; nothing is published outward.

> This stack is bring-up scaffold: the Hailo device path (`/dev/hailo0`), your camera
> substreams, and `shm_size` are per-install facts to confirm on the box on first run.
