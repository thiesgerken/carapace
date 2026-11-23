{
  description = "Example skill packaged with the Carapace npm helper";

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
          app = skill.npmApp { root = ./.; };
          node = "${pkgs.nodejs}/bin/node";
        in
        {
          default = skill.mkSkill {
            name = "demo-npm";
            commands = {
              demo-npm-hello = {
                exec = "${node} ${app}/src/hello.mjs";
                description = "Greet a name in color";
              };
              demo-npm-ping = {
                exec = "${node} ${app}/src/ping.mjs";
                description = "Check whether api.example.com is up";
                needs.domains = [ "api.example.com" ];
              };
            };
          };
        }
      );
    };
}
