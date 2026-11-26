{
  # The skills of this knowledge repo: every input except nixpkgs and carapace is one, named by its
  # attribute. See docs/skill-flakes.md.
  description = "Carapace skills";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    carapace = {
      url = "github:thiesgerken/carapace?dir=nix/skills";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    carapace-cli = {
      url = "path:./carapace";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    wikipedia = {
      url = "path:./wikipedia";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };

    # Bundled, but they need setting up first (see their SKILL.md). To turn one on, uncomment it and run
    # `nix flake lock ./skills`.
    # web = {
    #   url = "path:./web";
    #   inputs.nixpkgs.follows = "nixpkgs";
    #   inputs.carapace.follows = "carapace";
    # };
    # ferret = {
    #   url = "path:./ferret";
    #   inputs.nixpkgs.follows = "nixpkgs";
    #   inputs.carapace.follows = "carapace";
    # };
  };

  outputs =
    { carapace, ... }@inputs:
    let
      skills = removeAttrs inputs [
        "self"
        "nixpkgs"
        "carapace"
      ];
    in
    {
      packages = carapace.lib.forSkillSystems (
        system: builtins.mapAttrs (_name: skill: skill.packages.${system}.default) skills
      );
    };
}
