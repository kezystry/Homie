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

  # The X session script. Two hard-won fixes baked in:
  #  - Stremio's UI is embedded Chromium; its GPU process CRASHES on interaction
  #    on headless NVIDIA (window vanishes on click). Disable the GPU for the
  #    (lightweight) UI — video still plays at full quality via Stremio's separate
  #    mpv/NVDEC path. Override with HOMIE_STREMIO_FLAGS for experiments.
  #  - Start the WM and let it SETTLE before Stremio maps, otherwise Stremio opens
  #    as a small unmanaged window (not fullscreen). The 2s sleep wins the race.
  # When Stremio quits, the exec'd process ends, X tears down, back to console.
  stremioXinit = pkgs.writeShellScript "homie-watch-xinit" ''
    ${pkgs.xorg.xset}/bin/xset s off -dpms
    export QTWEBENGINE_DISABLE_SANDBOX=1
    export QTWEBENGINE_CHROMIUM_FLAGS="''${HOMIE_STREMIO_FLAGS:---disable-gpu --disable-gpu-compositing --no-sandbox}"
    ${pkgs.openbox}/bin/openbox --config-file ${openboxKiosk} &
    sleep 2
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
  # mkForce: configuration.nix (the headless base) sets `services.xserver.enable
  # = false`; this app layer opts X back in for on-demand startx, so it must win
  # the merge. Without mkForce the whole rebuild fails with a conflict error and
  # the old (broken) homie-watch silently stays in place.
  services.xserver.enable = lib.mkForce true;
  services.xserver.displayManager.startx.enable = true;

  # ---------------------------------------------------------------------------
  # Seat management for gamescope (Steam later) + DRM access for mpv-on-console.
  # Group is "seat" (NOT "seatd" — the NixOS module owns the socket as root:seat).
  # ---------------------------------------------------------------------------
  services.seatd.enable = true;
  users.users.homie.extraGroups = [ "video" "render" "seat" "input" "audio" ];

  # ---------------------------------------------------------------------------
  # Audio — PipeWire (modern server) with ALSA + PulseAudio compat, so Stremio,
  # mpv, and Steam/Proton all get sound out over HDMI to the TV. rtkit gives it
  # realtime priority for glitch-free playback. There are usually several sinks
  # (NVIDIA HDMI outputs + any motherboard audio); if the default lands on the
  # wrong one and you hear nothing, pick the HDMI sink over SSH:
  #     wpctl status                    # list sinks, note the HDMI one's ID
  #     wpctl set-default <ID>          # make it the default
  # (wpctl ships with wireplumber, which PipeWire enables by default.)
  # ---------------------------------------------------------------------------
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };
  security.rtkit.enable = true;

  environment.systemPackages = with pkgs; [
    mpv        # camera view (mpv --vo=drm) and a fallback media player
    stremio    # the streaming front-end; the owner manages his own addons/accounts
    openbox    # tiny WM that forces Stremio fullscreen in the X session
    ffmpeg     # cockpit camera: grabs single frames for the in-terminal thumbnail
    v4l-utils  # `v4l2-ctl --list-formats-ext` to confirm a webcam speaks MJPEG
    xdotool    # Homie's desktop eyes+hands: read the active window/title + send media keys
               # (HOMIE_DESKTOP=1). Fixed-argv only — the safe verb allowlist in core/desktop.py

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
