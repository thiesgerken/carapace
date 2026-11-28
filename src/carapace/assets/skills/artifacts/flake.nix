{
  description = "Instructions for building HTML artifacts";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    carapace = {
      url = "github:thiesgerken/carapace?dir=nix/skills";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, carapace, ... }:
    {
      packages = carapace.lib.forSkillSystems (system: {
        default = (carapace.lib.skill nixpkgs.legacyPackages.${system}).mkSkill {
          name = "artifacts";
          description = "Build self-contained HTML artifacts: reports, dashboards, calculators, and interactive explainers that render in carapace chat and the knowledge browser. Use when the user needs a reusable page or local interaction rather than a short answer, a Mermaid diagram, or a downloadable file.";
          src = ./.;
        };
      });
    };
}
