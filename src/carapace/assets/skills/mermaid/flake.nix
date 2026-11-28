{
  description = "Instructions for Mermaid diagrams";

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
          name = "mermaid";
          description = "Write Mermaid diagrams that render as pictures in the carapace web UI. Use when an answer is easier to see than to read: architectures, request flows, state machines, database schemas, decision trees, schedules, org structures. Ships syntax references for every diagram type.";
          src = ./.;
        };
      });
    };
}
