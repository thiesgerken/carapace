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
            src = ./.;
            # Bind it to a Ferret API key with only search:read, in skills/config.json (SETUP.md).
            credentials.FERRET_API_KEY = {
              type = "secret";
              description = "A Ferret API key with only search:read";
            };
            commands = skill.mcpCommands {
              ferret = {
                # Your deployment's HTTPS /mcp endpoint (SETUP.md).
                url = "https://ferret.example.invalid/mcp";
                bearer = "FERRET_API_KEY";
                description = "Read-only discovery across authorized personal indexed sources";
              };
            };
          };
        }
      );
    };
}
