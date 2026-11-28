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
            description = "Drive a carapace server non-interactively from inside the sandbox: list/inspect/create/update sessions, send messages and wait for turns, resolve pending approvals by id, and manage jobs (list/get/create/update/delete/run). Use this to let the agent configure, read, start, and interact with carapace sessions and jobs over the JSON CLI. Requires a scoped API key in the vault.";
            src = ./.;
            # Set and bound in skills/config.json (REFERENCE.md).
            settings.CARAPACE_HOST = {
              type = "str";
              # The proxy refuses loopback and internal hosts, so localhost does not work.
              description = "The public API domain of your Carapace deployment, e.g. carapace.example.com";
            };
            credentials.CARAPACE_API_KEY = {
              type = "secret";
              description = "A scoped Carapace API key";
            };
            needs = settings: { domains = [ settings.CARAPACE_HOST ]; };
            commands.carapace = {
              exec = "${pkgs.coreutils}/bin/env CARAPACE_SERVER=https://$CARAPACE_HOST ${cli}/bin/carapace";
              description = "Sessions, messages, approvals and jobs on a Carapace server, as JSON";
            };
          };
        }
      );
    };
}
