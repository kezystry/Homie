{
  description = "Homie OS — reproducible, atomic-rollback NixOS for the reasoning node";

  inputs = {
    # Pin to a release channel for reproducible rebuilds; bump deliberately.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
  };

  outputs = { self, nixpkgs, ... }:
    let
      system = "x86_64-linux"; # reasoning node is a desktop with a discrete GPU
    in {
      # nixos-rebuild switch --flake .#homie   (or --rollback)
      nixosConfigurations.homie = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          ./configuration.nix
          ./hardware-configuration.nix
          ./nvidia-cuda.nix
          ./virtualisation.nix   # Docker (+ compose) for running Home Assistant
        ];
      };
    };
}
