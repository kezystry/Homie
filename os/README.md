# OS

Homie runs on its own base rather than as an app on a general-purpose desktop: a
hardened, text-first image that boots straight into the system and dual-boots
alongside an existing OS.

## Choices

- **Base** — an immutable, declaratively built distro (NixOS preferred):
  reproducible images and atomic rollback, so a failed update reverts itself —
  self-healing at the OS layer.
- **No desktop** — the console is the only screen. The sole graphics are
  pulled-in camera frames and recognized faces, on demand.
- **Encryption** — full-disk (LUKS), encrypted state, encrypted mesh keys.
- **Quiet** — no telemetry, no accounts, no cloud.

## Boot

- A dual-boot entry alongside the existing OS.
- Boots directly into the Homie supervisor; no login shell needed for normal use.

## Self-* at the OS layer

- **Self-healing** — atomic/rollback updates; the supervisor restarts failed
  services and tiles.
- **Self-sustaining** — an immutable base means no drift; rebuild from the image
  definition.
- *Self-learning* lives above the OS, in Remember and the tiles.

## Layout

```
os/
├── image/   # the declarative image definition (build inputs)
└── boot/    # bootloader and dual-boot configuration
```
