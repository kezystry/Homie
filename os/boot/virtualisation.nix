# Containers on the Homie box — so Home Assistant (and any other service) runs in Docker.
#
# On NixOS you don't `apt install docker`; you enable it declaratively here and rebuild.
# After a `nixos-rebuild switch` the `docker` and `docker compose` commands exist and the
# `homie` user can run them without sudo (it's added to the docker group below).
#
# This is what lets `deploy/homeassistant/docker compose up -d` work on this machine.
# Import is wired in flake.nix's module list.
{ config, lib, pkgs, ... }:

{
  virtualisation.docker = {
    enable = true;
    # Tidy dangling images/stopped containers weekly so the box doesn't fill up.
    autoPrune = {
      enable = true;
      dates = "weekly";
    };
  };

  # The standalone `docker-compose` binary, for the deploy/homeassistant workflow.
  # (`docker compose` v2 ships inside the docker package above as well.)
  environment.systemPackages = [ pkgs.docker-compose ];

  # Let the owner run docker without sudo. extraGroups is a list option, so this MERGES
  # with the ["video"] set in configuration.nix → homie ends up in both groups.
  users.users.homie.extraGroups = [ "docker" ];

  # Open the LAN-facing service ports. NixOS's firewall is default-deny, so without this
  # only the box itself (loopback) could reach these — the phone/laptop on your LAN can't.
  # These are LOCAL ports on your own network; nothing here is exposed to the internet.
  #   8123  Home Assistant web UI
  #   1984  go2rtc  — live camera view (WebRTC API/UI)
  #   8555  go2rtc  — WebRTC media (also opened on UDP below)
  #   5000  Frigate — recordings + zone drawing
  networking.firewall.allowedTCPPorts = [ 8123 1984 8555 5000 ];

  # go2rtc WebRTC media + the WireGuard tunnel are UDP.
  #   8555  go2rtc WebRTC media
  #  51820  WireGuard — the ONLY port you forward on the router for "watch from anywhere".
  #         It reveals nothing without your key; cameras themselves stay un-exposed.
  networking.firewall.allowedUDPPorts = [ 8555 51820 ];
}
