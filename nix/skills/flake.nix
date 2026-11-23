{
  # Its own flake so that a skill's flake.lock holds these few inputs, not everything Carapace builds with.
  description = "Nix functions for Carapace skill flakes; see docs/skill-flakes.md";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs: {
    lib = import ./. {
      inherit (inputs)
        nixpkgs
        pyproject-nix
        uv2nix
        pyproject-build-systems
        ;
    };
  };
}
