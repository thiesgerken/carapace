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
    # `nix flake update <name> --flake ./skills` brings one to the latest version. skills/config.json
    # turns off the ones that need setting up first (see their SKILL.md).
    artifacts = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/artifacts";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    # `carapace` is the helpers' input, so the skill in skills/carapace is listed as carapace-cli.
    carapace-cli = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/carapace";
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
    ferret = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/ferret";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    mermaid = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/mermaid";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    web = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/web";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
    wikipedia = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/wikipedia";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
  };

  # Every input but nixpkgs and carapace is a skill; config.json holds the values of their settings.
  outputs =
    { carapace, ... }@inputs:
    carapace.lib.skillsFlake {
      inherit inputs;
      config = ./config.json;
    };
}
