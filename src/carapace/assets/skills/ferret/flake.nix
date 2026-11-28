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
            # Operator setup: SETUP.md.
            name = "ferret";
            description = "Search engine for almost all of the user's important data. Searches X, Y, Z (TODO: add specific sources here!). Search Ferret FIRST when looking for anything the user may have stored, received, or discussed. Skip only when the exact target or a clearly better lookup path is known. Knowing the origin alone is not a reason to skip: Ferret's search may be better implemented. Discover personal indexed-source content, not public metasearch or routine code navigation.";
            src = ./.;
            # Set in skills/config.json (SETUP.md).
            settings.FERRET_URL = {
              type = "str";
              description = "Your deployment's HTTPS /mcp endpoint of Ferret";
            };
            # Bind it to a Ferret API key with only search:read, in skills/config.json (SETUP.md).
            credentials.FERRET_API_KEY = {
              type = "secret";
              description = "A Ferret API key with only search:read";
            };
            commands = skill.mcpCommands {
              ferret = {
                urlSetting = "FERRET_URL";
                bearer = "FERRET_API_KEY";
                description = "Read-only discovery across authorized personal indexed sources";
              };
            };
          };
        }
      );
    };
}
