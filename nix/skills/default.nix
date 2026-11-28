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

  # The options a skill declares in skills/config.json: whether it is on, its settings, its credential slots.
  skillOptions =
    attr: package:
    let
      # The newest declaration: helpers that have it have the settings too.
      slots =
        package.passthru.carapace.credentials
          or (throw "skill ${attr}: its Carapace helpers are older than credential slots; let it follow carapace and run `nix flake update carapace --flake ./skills`");
    in
    {
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
      ) package.passthru.carapace.settings;
      # A vault path, as `ccred get` takes it; null until bound.
      credentials = lib.mapAttrs (
        slot: _:
        lib.mkOption {
          type = lib.types.nullOr (lib.types.strMatching "[^/[:space:]]+/[^[:space:]]+");
          default = null;
          description = "The password-manager entry bound to ${attr}'s credential slot ${slot}.";
        }
      ) slots;
    };

  # The packages and manifests of every skill for one system. The manifest is what Carapace reads of a skill
  # (docs/skill-flakes.md): its settings and credential bindings with this instance's values, and each
  # command's needs for them.
  skillsFor =
    skills: values: overrides: system:
    let
      packages = lib.mapAttrs (
        attr: skill: (overrides.${attr} or lib.id) skill.packages.${system}.default
      ) skills;
      # A config.json entry of a skill that is not listed is ignored here; the server reports it.
      manifest =
        attr: package:
        let
          description =
            package.passthru.carapace.description
              or (throw "skill ${attr}: its Carapace helpers are older than mkSkill's description; let it follow carapace and run `nix flake update carapace --flake ./skills`");
          # The module system over this skill alone: one over all of them would read every skill's flake for
          # each manifest, and one broken skill must not fail the others.
          evaluated = lib.evalModules {
            modules = [
              { options.skills.${attr} = skillOptions attr package; }
              {
                _file = "skills/config.json";
                skills.${attr} = values.${attr} or { };
              }
            ];
          };
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
            inherit description;
            inherit (package.passthru.carapace) name skillDir;
            overridden = overrides ? ${attr};
            inherit (cfg) settings;
            credentials = lib.mapAttrs (
              slot: declared: declared // { binding = cfg.credentials.${slot}; }
            ) package.passthru.carapace.credentials;
            # An unbound slot stays in the needs as null: Carapace refuses the commands that need it.
            commands = lib.mapAttrs (
              cmd: command:
              let
                needs = (package.passthru.carapaceNeeds cfg.settings).${cmd};
              in
              command
              // {
                needs = needs // {
                  credentials = lib.genAttrs needs.credentials (slot: cfg.credentials.${slot});
                  oauth = lib.genAttrs needs.oauth (slot: cfg.credentials.${slot});
                };
              }
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
  # `overrides` adjusts skills this repo takes from elsewhere: per skill attribute, a function from the
  # package to the one to use, typically `skill: skill.override (old: { … })` (docs/sharing-skills.md).
  skillsFlake =
    {
      inputs,
      config,
      overrides ? { },
    }:
    let
      skills = removeAttrs inputs [
        "self"
        "nixpkgs"
        "carapace"
      ];
      values = if builtins.pathExists config then lib.importJSON config else { };
      unknown = lib.subtractLists (lib.attrNames skills) (lib.attrNames overrides);
      perSystem = forSkillSystems (skillsFor skills values overrides);
    in
    assert lib.assertMsg (unknown == [ ])
      "skills/flake.nix: overrides for ${lib.concatStringsSep ", " unknown}, which are not skill inputs (skills: ${lib.concatStringsSep ", " (lib.attrNames skills)})";
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
