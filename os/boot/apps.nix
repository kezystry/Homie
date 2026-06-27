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

  environment.systemPackages = with pkgs; [
    mpv      # camera view (mpv --vo=drm) and a fallback media player
    stremio  # the streaming front-end; the owner manages his own addons/accounts

    # `homie-watch` — the one-line "watch movies" command (plan Stage 2). Runs
    # Stremio fullscreen under gamescope straight from the console. Extra args
    # pass through to gamescope (e.g. `homie-watch -w 1920 -h 1080`).
    (writeShellScriptBin "homie-watch" ''
      exec ${pkgs.gamescope}/bin/gamescope -f "$@" -- ${pkgs.stremio}/bin/stremio
    '')
  ];
}
