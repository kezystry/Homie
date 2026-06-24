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

## Dual-boot — ready to install

The setup is ready to install alongside an existing OS:

- **[INSTALL.md](INSTALL.md)** — step-by-step dual-boot install (shrink, LUKS,
  GRUB + os-prober, first boot). The existing OS is preserved and chainloaded.
- **[boot/configuration.nix](boot/configuration.nix)** — the headless, encrypted,
  hardened NixOS module: GRUB+os-prober, LUKS root, console autologin, the
  `homie` daemon service.
- **[boot/flake.nix](boot/flake.nix)** — reproducible build + atomic rollback.

```
os/
├── INSTALL.md          # dual-boot installation guide
└── boot/
    ├── configuration.nix   # the system definition (fill in the <PLACEHOLDER>s)
    └── flake.nix           # reproducible rebuilds / rollback
```
