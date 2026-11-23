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
