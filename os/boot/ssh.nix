# Opt-in remote management: SSH + sudo for `homie`.
#
# NOT imported by the flake by default (the base design ships SSH off). Drop it
# into /etc/nixos/, add `./ssh.nix` to flake.nix's `modules`, and rebuild to
# turn on remote access — so you manage the box from a phone/laptop with
# copy-paste instead of the physical console.
#
# PasswordAuthentication is ON here ONLY to bootstrap: it lets you connect from
# the phone without typing a long public key at the console. Once your key is
# installed (authorizedKeys below), flip PasswordAuthentication to mkForce false
# and rebuild for key-only access.
{ lib, pkgs, ... }:
{
  # Manageability essentials, installed with the bootstrap so the box stops
  # fighting you at the console:
  #   - flakes/nix-command enabled PERMANENTLY, so `nixos-rebuild --flake` and
  #     plain `nix` commands work without `--extra-experimental-features` every
  #     time (the base install ships with them off).
  #   - git on PATH, so updates are just `git -C /opt/homie pull` — no nix-shell.
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  environment.systemPackages = [ pkgs.git ];

  services.openssh.enable = lib.mkForce true;
  services.openssh.settings.PasswordAuthentication = lib.mkForce true; # bootstrap; tighten to false after key install
  services.openssh.settings.PermitRootLogin = lib.mkForce "no";

  # Let `homie` run admin commands over SSH (sudo). Merges with the base groups.
  users.users.homie.extraGroups = [ "wheel" ];

  # Paste your phone/laptop public key here, then set PasswordAuthentication
  # false above for key-only login:
  # users.users.homie.openssh.authorizedKeys.keys = [ "ssh-ed25519 AAAA... homie@iphone" ];

  # SSH reachable on the LAN. The home router's NAT keeps it off the WAN; a
  # dedicated firewall rule / WireGuard comes in the hardening phase.
  networking.firewall.allowedTCPPorts = [ 22 ];
}
