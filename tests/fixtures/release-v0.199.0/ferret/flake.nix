{
  description = "Ferret: read-only discovery across the user's indexed sources, over MCP";

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
      packages = carapace.lib.forSkillSystems (
        system:
        let
          skill = carapace.lib.skill nixpkgs.legacyPackages.${system};
        in
        {
          default = skill.mkSkill {
            name = "ferret";
            commands = skill.mcpCommands {
              ferret = {
                # Your deployment's HTTPS /mcp endpoint (SETUP.md).
                url = "https://ferret.example.invalid/mcp";
                # A Ferret API key with only search:read, sent as a bearer token.
                bearer = "vault/ferret-api-key";
                description = "Read-only discovery across authorized personal indexed sources";
              };
            };
          };
        }
      );
    };
}
