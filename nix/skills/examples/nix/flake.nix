{
  description = "Example skill built from nixpkgs alone, without a language package manager";

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
          pkgs = nixpkgs.legacyPackages.${system};
          skill = carapace.lib.skill pkgs;
          pages = pkgs.writeShellApplication {
            name = "demo-nix-pages";
            runtimeInputs = [
              pkgs.qpdf
              pkgs.jq
            ];
            text = ''qpdf --json --json-key=pages "$1" | jq '.pages | length' '';
          };
          ping = pkgs.writeShellApplication {
            name = "demo-nix-ping";
            runtimeInputs = [ pkgs.curl ];
            text = ''echo "api.example.com answered $(curl -sS -o /dev/null -w '%{http_code}' https://api.example.com/status)"'';
          };
        in
        {
          default = skill.mkSkill {
            name = "demo-nix";
            commands = {
              demo-nix-pages = {
                exec = "${pages}/bin/demo-nix-pages";
                description = "Count the pages of a PDF";
              };
              demo-nix-jq = {
                exec = "${pkgs.jq}/bin/jq";
                description = "jq from nixpkgs, as is";
              };
              demo-nix-ping = {
                exec = "${ping}/bin/demo-nix-ping";
                description = "Check whether api.example.com is up";
                needs.domains = [ "api.example.com" ];
              };
            };
          };
        }
      );
    };
}
