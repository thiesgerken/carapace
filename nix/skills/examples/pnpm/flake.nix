{
  description = "Example skill packaged with the Carapace pnpm helper";

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
          app = skill.pnpmApp {
            root = ./.;
            # Changes with pnpm-lock.yaml: build once with `pkgs.lib.fakeHash` and take the hash from the error.
            hash = "sha256-nWi4zyIaLKHD6wrM+k7SiWreZEkS8TGfToIvH8HJ628=";
          };
          node = "${pkgs.nodejs}/bin/node";
        in
        {
          default = skill.mkSkill {
            name = "demo-pnpm";
            commands = {
              demo-pnpm-hello = {
                exec = "${node} ${app}/src/hello.mjs";
                description = "Greet a name in color";
              };
              demo-pnpm-ping = {
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
