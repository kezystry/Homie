# Camera — Homie's eyes (the foundation you can plug into any time)

> Your words: *"camera is everything — set it up so I can stream it live anywhere in max
> quality and fps, and build the whole foundation so I can plug in a camera at any time."*
> This is that foundation. It was decided in a council (a streaming-media engineer, a
> computer-vision/NVR engineer, a privacy lawyer, and a home-network/security engineer) and
> the safety-critical parts ship tested today.

## What you get, in plain words

- **Watch live from anywhere, at full quality.** Open any camera on your phone and see
  exactly what the sensor produces — its native resolution and frame rate, sub-second
  latency, no quality lost to re-encoding. "Anywhere" means *over your own private tunnel*
  into your own network — not the internet, not a cloud account. Your eyes, your property,
  your wires.
- **Plug in a camera any time.** Adding a camera is one stanza in `deploy/cameras.toml` and
  one command. Nothing else changes. The system was built around that from day one.
- **It records, and it notices.** A small AI chip on the Pi watches for the things you care
  about (a person on the porch, a car in the drive, a package) — on the box, never in a
  cloud. Continuous recording is kept locally for the cameras you choose.
- **It cannot leak.** A camera image never leaves the Pi. Only tiny structured notes ("a
  person entered the porch") ever cross to the rest of Homie, and only for the zones you
  explicitly allow. This is enforced in code, not promised in a policy.

## The four pieces

| Piece | What it is | Plain job |
|---|---|---|
| **go2rtc** | a tiny live-stream router | passes each camera's native stream straight to your phone over WebRTC — **no transcode**, so max quality + fps |
| **Frigate + Hailo-8** | local NVR + on-device detector | records, and runs object detection on the Pi's AI chip — never in the cloud |
| **WireGuard** | a private VPN tunnel | lets you reach go2rtc "anywhere" by joining your own network remotely — the only thing that crosses the internet is *you*, encrypted |
| **`core/camera.py` + adapter** | Homie's registry + edge strainer | the single source of truth for what cameras exist and what may be seen; turns detections into bus events and **lets the frames die at the edge** |

## How "max quality and FPS" is achieved (honestly)

go2rtc **passes the source codec through untouched**. Your camera already emits H.264/H.265
at its full resolution and frame rate; go2rtc hands that exact stream to WebRTC. Because
nothing is re-encoded, there is no quality loss and no added CPU cost — what you see live is
bit-for-bit what the sensor sent. (Detection uses a separate low-res substream so the AI work
never steals from the live view.) The honest limit: live quality is whatever the *camera*
produces — Homie can't add detail the sensor didn't capture.

## How "stream anywhere" stays private

You don't expose a camera to the internet. You run **WireGuard**, a small VPN, on the
home-control box. From your phone you switch the tunnel on and you are *inside your own
network*, exactly as if you were home — then go2rtc serves you locally. To the outside world
there is no open camera port, no cloud relay, nothing to find or subpoena. Watching your own
cameras over your own tunnel is not "sending data out" — it's you looking through your own
window from the other room. (See `docs/SECURITY.md` on why this keeps the legal
field-of-view exemption intact.)

## The privacy contract (enforced in code)

1. **Raw imagery dies at the edge.** `perception/frigate_adapter.py` reads only three scalar
   fields from a detection — camera, zone, label — and builds the bus event from scratch.
   Snapshots, crops, bounding boxes, embeddings are never read, so they can never leak. The
   same `assert_emittable` guard that protects every perception event hard-fails if anything
   forbidden ever tried to ride along. (Tested: a detection fat with a snapshot yields a
   3-field note.)
2. **Positive zone-allowlist.** A detection becomes a Homie event **only** if its
   `(camera, zone, label)` is explicitly allowed in `cameras.toml`. The default is silence,
   not leak. A camera with no zones is live-view-only: watchable, but it emits nothing.
3. **The street is not yours to watch.** A camera whose field of view isn't wholly on your
   property may stream live but can **never** run identity inference — `identify` is forced
   off in code when `on_property = false`. (Ryneš, C-212/13 — see `docs/SECURITY.md`.)
4. **No motion sensors.** Per your call, presence comes from the cameras alone for now; there
   is no separate motion-sensor path to reason about or secure.

## Plug in a camera — the whole procedure

1. **Declare it.** Add a stanza to `deploy/cameras.toml` (the file documents every field):

   ```toml
   [camera.front_door]
   source = "rtsp://homie:${RTSP_PW}@192.168.1.50:554/stream1"
   zones = ["porch", "path"]      # only these zones ever emit events
   detect = ["person", "package"]
   on_property = true
   identify = true
   ```
   Put the RTSP password in `/etc/homie-cameras.env` on the box — **never in this file** (the
   repo is public; `${RTSP_PW}` is resolved on your machine only).

2. **Generate the configs.**
   ```
   python3 scripts/camera_setup.py            # preview
   python3 scripts/camera_setup.py --write     # write deploy/cameras/{go2rtc,frigate}.yml
   ```

3. **Draw the zones once.** Open the Frigate web UI and draw the shape of each zone you named
   (a zone is a polygon on the image; the repo can't invent your porch's outline). Restart the
   camera stack.

4. **Watch it.** Open go2rtc (`http://<box>:1984`) on your network, or over WireGuard from
   anywhere. It's live, at full quality.

## What ships today vs. what's next

- **Today (tested, in the repo):** the registry + validation, the positive zone-allowlist, the
  edge adapter that kills frames and emits clean events, the go2rtc + Frigate config
  generators, and the setup script. This is the *foundation* — the contracts and the seam
  that everything else bolts onto.
- **Next (on the box, declarative):** the go2rtc/Frigate/WireGuard containers in the NixOS
  deploy config, wiring the adapter into `build_daemon` behind the perception seam, and the
  returning-unknown faceprint (short-lived, on-device, vector-only) for `identify` cameras.

## Where the code lives

- `core/camera.py` — the registry, the allowlist gate, the config generators, the YAML emitter.
- `deploy/cameras.toml` — the one place you declare cameras.
- `perception/frigate_adapter.py` — the edge strainer (a `PerceptionSource`; frames die here).
- `scripts/camera_setup.py` — render the live + NVR configs from the registry.
- `tests/test_camera.py` — proves the allowlist, the fail-closed defaults, and the frame-drop.
