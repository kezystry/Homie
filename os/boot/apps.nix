# Homie launch-on-command app layer — the "open a fullscreen app from the TTY"
# surface that the Layer 2 cockpit (and a bare `homie-watch` command) drive.
#
# Headless by design: there is NO desktop environment. Instead, a single
# gamescope micro-compositor grabs the display on demand and hosts ONE fullscreen
# client (Stremio now; Steam in Stage 4; the camera via mpv). gamescope owns DRM
# master for the session, so app-exit returns cleanly to the console with no VT
# thrash — the architecture the cockpit council settled on.
#
# Everything here is cached on cache.nixos.org (no flaky CUDA download), so a
# rebuild that adds this module needs only the reliable NVIDIA *driver*
# (nvidia-cuda.nix with cuda off). That is what makes "movies first" possible
# before the CUDA toolkit is sorted.
#
# Import by adding `./apps.nix` to the flake's module list.

{ lib, pkgs, ... }:

{
  # gamescope: the micro-compositor. capSysNice lets it raise scheduling priority
  # for smooth playback; it is launched per-command, never a long-running session.
  programs.gamescope = {
    enable = true;
    capSysNice = true;
  };

  # ---------------------------------------------------------------------------
  # SEAT MANAGEMENT — what lets gamescope grab the display on a bare console.
  #
  # There is no desktop/display-manager here, so when gamescope launches from the
  # auto-login TTY it has no "seat" (the permission to own the GPU + VT). Without
  # one it dies with: "Could not connect to /run/seatd.sock", "failed to open
  # seat", "Permission denied /dev/dri/cardN", "Could not open VT" -> segfault
  # (exactly the Stage-2 first-run failure).
  #
  # seatd is a tiny standalone seat manager; gamescope's libseat tries it first.
  # Enabling it (and putting `homie` in the seat + GPU/input groups) gives
  # gamescope a seat without a full logind graphical session. Run apps as the
  # plain `homie` user from the console — NOT via sudo, which breaks seat access.
  # ---------------------------------------------------------------------------
  services.seatd.enable = true;
  users.users.homie.extraGroups = [ "video" "render" "seatd" "input" ];

  environment.systemPackages = with pkgs; [
    mpv      # camera view (mpv --vo=drm) and a fallback media player
    stremio  # the streaming front-end; the owner manages his own addons/accounts
    ffmpeg   # cockpit camera: grabs single frames for the in-terminal thumbnail
    v4l-utils  # `v4l2-ctl --list-formats-ext` to confirm a webcam speaks MJPEG

    # `homie-watch` — the one-line "watch movies" command (plan Stage 2). Runs
    # Stremio fullscreen under gamescope straight from the console. Extra args
    # pass through to gamescope (e.g. `homie-watch -w 1920 -h 1080`).
    (writeShellScriptBin "homie-watch" ''
      exec ${pkgs.gamescope}/bin/gamescope -f "$@" -- ${pkgs.stremio}/bin/stremio
    '')

    # `homie` — open the Layer 2 cockpit (the curses control plane: chat with the
    # brain, watch status, launch apps). Works at the console and over SSH.
    (writeShellScriptBin "homie" ''
      cd /opt/homie || exit 1
      exec ${pkgs.python311}/bin/python3 -m cockpit "$@"
    '')
  ];
}
