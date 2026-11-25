# The interface skill flakes see as `carapace.lib`, built from whichever inputs the caller has: the skills
# subflake for skills, the main flake for CI.
{
  nixpkgs,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
}:
{
  # Sandboxes run on Linux, on the builder's architecture.
  forSkillSystems = nixpkgs.lib.genAttrs [
    "x86_64-linux"
    "aarch64-linux"
  ];
  # The Carapace CLI client of this commit, without the server stack. A skill that pins a Carapace
  # commit pins its CLI with it; this reads the whole repository, which `?dir=nix/skills` fetches anyway.
  carapaceCli =
    pkgs:
    (import ../python.nix {
      inherit
        pkgs
        pyproject-nix
        uv2nix
        pyproject-build-systems
        ;
    }).cli;
  skill =
    pkgs:
    import ./lib.nix {
      inherit
        pkgs
        pyproject-nix
        uv2nix
        pyproject-build-systems
        ;
    };
}
