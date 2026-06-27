# Homie launch-on-command app layer — the "open a fullscreen app from the TTY"
# surface that the Layer 2 cockpit (and a bare `homie-watch` command) drive.
#
# Headless by design: there is NO desktop environment and NO display manager, so
# the box boots to the plain console. Apps are launched on demand:
#
#   * MOVIES (homie-watch): Stremio under a MINIMAL XORG session. We use X (not
#     gamescope/Wayland) deliberately — on the RTX 3060 + driver 550, gamescope
#     flickers/black-frames (NVIDIA's Wayland explicit-sync only arrived at 555,
#     and 565 broke this display entirely). NVIDIA-under-X is the rock-solid path
#     with none of that. Decided by council after a long bring-up.
#   * GAMES (later, Stage 4): Steam/Proton via gamescope — kept enabled below.
#   * CAMERA: mpv --vo=drm straight on the console (cockpit launcher).
#
# Everything here is cached on cache.nixos.org (no flaky CUDA download).
#
# Import by adding `./apps.nix` to the flake's module list.

{ lib, pkgs, ... }:

let
  # Openbox kiosk config: every window opens fullscreen + undecorated, so Stremio
  # fills the TV with no titlebar and no way to lose the window. (class="*" is the
  # catch-all match — Stremio is the only client in the session.)
  openboxKiosk = pkgs.writeText "homie-openbox-rc.xml" ''
    <?xml version="1.0" encoding="UTF-8"?>
    <openbox_config xmlns="http://openbox.org/3.4/rc">
      <applications>
        <application class="*">
          <decor>no</decor>
          <maximized>yes</maximized>
          <fullscreen>yes</fullscreen>
          <focus>yes</focus>
        </application>
      </applications>
    </openbox_config>
  '';

  # The X session script: kill screen-blanking, start a tiny WM for focus +
  # forced-fullscreen, then exec Stremio as the sole client. When Stremio quits,
  # the exec'd process ends, X tears down, and you're back at the console.
  stremioXinit = pkgs.writeShellScript "homie-watch-xinit" ''
    ${pkgs.xorg.xset}/bin/xset s off -dpms
    ${pkgs.openbox}/bin/openbox --config-file ${openboxKiosk} &
    exec ${pkgs.stremio}/bin/stremio
  '';
in
{
  # gamescope kept for the Steam/Proton stage; it is NOT used for movies anymore.
  programs.gamescope = {
    enable = true;
    capSysNice = true;
  };

  # ---------------------------------------------------------------------------
  # Minimal Xorg, started ON DEMAND via startx — there is NO display manager, so
  # enabling this does NOT change the boot (the box still lands at the plain
  # console). `startx.enable` provides xinit/startx and the console-user X
  # wrapper; the NVIDIA X driver comes from `services.xserver.videoDrivers =
  # [ "nvidia" ]` set in nvidia-cuda.nix. X and gamescope coexist fine — only one
  # owns the display at a time (sequential), never both at once.
  # ---------------------------------------------------------------------------
  services.xserver.enable = true;
  services.xserver.displayManager.startx.enable = true;

  # ---------------------------------------------------------------------------
  # Seat management for gamescope (Steam later) + DRM access for mpv-on-console.
  # Group is "seat" (NOT "seatd" — the NixOS module owns the socket as root:seat).
  # ---------------------------------------------------------------------------
  services.seatd.enable = true;
  users.users.homie.extraGroups = [ "video" "render" "seat" "input" ];

  environment.systemPackages = with pkgs; [
    mpv        # camera view (mpv --vo=drm) and a fallback media player
    stremio    # the streaming front-end; the owner manages his own addons/accounts
    openbox    # tiny WM that forces Stremio fullscreen in the X session
    ffmpeg     # cockpit camera: grabs single frames for the in-terminal thumbnail
    v4l-utils  # `v4l2-ctl --list-formats-ext` to confirm a webcam speaks MJPEG

    # `homie-watch` — the one-line "watch movies" command. Runs Stremio fullscreen
    # in a minimal X session straight from the console. Run as the `homie` user,
    # not root/sudo (the console-user X wrapper expects a normal user).
    (writeShellScriptBin "homie-watch" ''
      if [ "$(id -u)" = 0 ]; then
        echo "Run homie-watch as the 'homie' user, not via sudo/root." >&2
        exit 1
      fi
      exec ${pkgs.xorg.xinit}/bin/startx ${stremioXinit} -- vt1
    '')

    # `homie` — open the Layer 2 cockpit (the curses control plane: chat with the
    # brain, watch status, launch apps). Works at the console and over SSH.
    (writeShellScriptBin "homie" ''
      cd /opt/homie || exit 1
      exec ${pkgs.python311}/bin/python3 -m cockpit "$@"
    '')
  ];
}
