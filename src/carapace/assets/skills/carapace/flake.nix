{
  description = "Drive a Carapace server from the sandbox with the carapace CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    carapace = {
      url = "github:thiesgerken/carapace?dir=nix/skills";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, carapace, ... }:
    let
      # Your deployment's public API domain and the vault path of a scoped API key (see REFERENCE.md).
      # The proxy refuses loopback and internal hosts, so localhost does not work.
      server = "carapace.example.com";
      apiKey = "<backend>/<your-carapace-api-key-id>";
    in
    {
      packages = carapace.lib.forSkillSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          skill = carapace.lib.skill pkgs;
          # The CLI of the pinned Carapace commit, without the server stack.
          cli = carapace.lib.carapaceCli pkgs;
        in
        {
          default = skill.mkSkill {
            name = "carapace";
            needs = {
              domains = [ server ];
              credentials.CARAPACE_API_KEY = apiKey;
            };
            commands.carapace = {
              exec = "${pkgs.coreutils}/bin/env CARAPACE_SERVER=https://${server} ${cli}/bin/carapace";
              description = "Sessions, messages, approvals and jobs on a Carapace server, as JSON";
            };
          };
        }
      );
    };
}
