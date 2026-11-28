{
  description = "Search and read Wikipedia articles, German by default";

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
            name = "wikipedia";
            description = "Suche und Lese-Funktion für Wikipedia-Artikel (Deutsch als Standard). Nutze diesen Skill, um nach Artikeln zu suchen oder deren Inhalt abzurufen. Unterstützt Deutsch und Englisch via --lang Flag.";
            src = ./.;
            needs.domains = [
              "de.wikipedia.org"
              "en.wikipedia.org"
            ];
            commands = {
              wiki-search = {
                exec = "${env}/bin/wiki-search";
                description = "Search Wikipedia articles (--lang de|en)";
              };
              wiki-fetch = {
                exec = "${env}/bin/wiki-fetch";
                description = "Read a Wikipedia article (--lang de|en)";
              };
            };
          };
        }
      );
    };
}
