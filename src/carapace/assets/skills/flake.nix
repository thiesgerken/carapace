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

    # Bundled with Carapace and taken from its main branch, so they stay current without a copy here:
    # `nix flake update <name> --flake ./skills` brings one to the latest version.
    artifacts = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/artifacts";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    create-skill = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/create-skill";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    credentials = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/credentials";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    mermaid = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/mermaid";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    wikipedia = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/wikipedia";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };

    # Bundled and copied into this repo, because their flake carries settings for this instance.
    carapace-cli = {
      url = "path:./carapace";
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
