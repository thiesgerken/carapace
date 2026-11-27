{
  description = "Web search through Brave Search and readable page fetching";

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
          env = skill.uvEnv { root = ./.; };
        in
        {
          default = skill.mkSkill {
            name = "web";
            src = ./.;
            # Bind it to the entry that holds your Brave Search API key, in skills/config.json.
            credentials.BRAVE_API_KEY = {
              type = "secret";
              description = "A Brave Search API key";
            };
            commands = {
              web_search = {
                exec = "${env}/bin/web_search";
                description = "Search the web with Brave Search";
                needs.domains = [ "api.search.brave.com" ];
              };
              # Any URL: each domain is reviewed when the command reaches it.
              web_fetch = {
                exec = "${env}/bin/web_fetch";
                description = "Fetch a web page as readable text";
                needs.credentials = [ ];
              };
            };
          };
        }
      );
    };
}
