# Homie Stage 4 — Steam + Proton for games.
#
# Separate module so a gaming-layer issue can never block the cortex: it is added
# on top of the working base with its own rebuild. Depends on apps.nix (gamescope)
# and nvidia-cuda.nix (the driver + 32-bit GL that Proton/Vulkan need — already
# enabled there via hardware.graphics.enable32Bit).
#
# Import by adding `./steam.nix` to the flake's module list (scripts/stage4.sh).
#
# Reminder (standing security rule): install games ONLY through Steam/Proton.
# Never run cracked repacks (SteamRIP etc.) on this box — they are a top
# infostealer vector and would hand over the brain of the home.

{ pkgs, ... }:

{
  programs.steam = {
    enable = true;
    # Launch Steam inside a gamescope session — the same micro-compositor the
    # cockpit launcher uses, so games own the display cleanly and hand it back.
    gamescopeSession.enable = true;
    remotePlay.openFirewall = false; # no inbound; keep the firewall tight
    dedicatedServer.openFirewall = false;
  };

  # Proton needs the Vulkan/GL userspace; the 32-bit half is enabled in
  # nvidia-cuda.nix (hardware.graphics.enable32Bit = true). Nothing else required.
}
