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
}
