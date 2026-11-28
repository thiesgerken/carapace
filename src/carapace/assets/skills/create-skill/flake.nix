{
  description = "Instructions for writing a new skill";

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
          name = "create-skill";
          description = "Create and refine carapace AgentSkills. Use when the user wants to add a new skill, reshape an existing one, or asks how a skill should be structured.";
          src = ./.;
        };
      });
    };
}
