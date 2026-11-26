# The interface skill flakes see as `carapace.lib`, built from whichever inputs the caller has: the skills
# subflake for skills, the main flake for CI.
{
  nixpkgs,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
}:
let
  inherit (nixpkgs) lib;
  # Sandboxes run on Linux, on the builder's architecture.
  forSkillSystems = lib.genAttrs [
    "x86_64-linux"
    "aarch64-linux"
  ];
  # The types a skill's settings can have; the module system checks the values from skills/config.json.
  settingTypes = {
    str = lib.types.str;
    int = lib.types.int;
    bool = lib.types.bool;
  };

  # The packages and manifests of every skill for one system. The manifest is what Carapace reads of a skill
  # (docs/skill-flakes.md): its settings with this instance's values and each command's needs for them.
  skillsFor =
    skills: values: system:
    let
      packages = lib.mapAttrs (_: skill: skill.packages.${system}.default) skills;
      carapaceOf =
        attr: package:
        package.passthru.carapace.settings
          or (throw "skill ${attr}: its Carapace helpers are older than settings; let it follow carapace and run `nix flake update carapace --flake ./skills`");
      evaluated = lib.evalModules {
        modules = [
          {
            options.skills = lib.mapAttrs (attr: package: {
              enable = lib.mkOption {
                type = lib.types.bool;
                default = true;
                description = "Whether ${attr} is a skill of this instance.";
              };
              settings = lib.mapAttrs (
                _: setting:
                lib.mkOption (
                  {
                    type = settingTypes.${setting.type};
                    inherit (setting) description;
                  }
                  // lib.optionalAttrs (setting ? default) { inherit (setting) default; }
                )
              ) (carapaceOf attr package);
            }) packages;
          }
          {
            _file = "skills/config.json";
            skills = values;
          }
        ];
      };
      manifest =
        attr: package:
        let
          cfg = evaluated.config.skills.${attr};
          options = evaluated.options.skills.${attr}.settings;
          missing = lib.filter (setting: !options.${setting}.isDefined) (lib.attrNames options);
        in
        # Lazily: a skill that is off needs no values, and its manifest says only that.
        if !cfg.enable then
          { enable = false; }
        else
          assert lib.assertMsg (missing == [ ])
            "skill ${attr}: no value for its setting ${lib.concatStringsSep ", " missing}; set it in skills/config.json, e.g. {\"${attr}\": {\"settings\": {\"${builtins.head missing}\": …}}}";
          {
            enable = true;
            inherit (package.passthru.carapace) name skillDir;
            inherit (cfg) settings;
            commands = lib.mapAttrs (
              cmd: command: command // { needs = (package.passthru.carapaceNeeds cfg.settings).${cmd}; }
            ) package.passthru.carapace.commands;
          };
    in
    {
      inherit packages;
      manifests = lib.mapAttrs manifest packages;
    };
in
{
  inherit forSkillSystems;

  # The outputs of skills/flake.nix: every input but nixpkgs and carapace is a skill. `config` is the
  # path of skills/config.json, the values of their settings; without the file every skill takes its defaults.
  skillsFlake =
    { inputs, config }:
    let
      skills = removeAttrs inputs [
        "self"
        "nixpkgs"
        "carapace"
      ];
      values = if builtins.pathExists config then lib.importJSON config else { };
      perSystem = forSkillSystems (skillsFor skills values);
    in
    {
      packages = lib.mapAttrs (_: system: system.packages) perSystem;
      manifests = lib.mapAttrs (_: system: system.manifests) perSystem;
    };
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
        settingTypes
        ;
    };
}
