{
  description = "Example skill packaged with the Carapace uv helper";

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
          env = skill.uvEnv {
            root = ./.;
            # uv.lock does not record build systems; an sdist dependency needs its own named.
            overrides = final: prev: {
              docopt = prev.docopt.overrideAttrs (old: {
                nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem { setuptools = [ ]; };
              });
            };
          };
        in
        {
          default = skill.mkSkill {
            name = "demo-uv";
            needs = {
              domains = [ "api.example.com" ];
              credentials.DEMO_API_TOKEN = "demo/api-token";
            };
            commands = {
              demo-status = {
                exec = "${env}/bin/demo-status";
                description = "Check whether api.example.com is up";
              };
              demo-usage = {
                exec = "${env}/bin/demo-usage";
                description = "Greet a name, locally";
                needs = {
                  domains = [ ];
                  credentials = { };
                };
              };
            };
          };
        }
      );
    };
}
