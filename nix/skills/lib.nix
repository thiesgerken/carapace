# Functions a skill flake uses to package its commands. See docs/skill-flakes.md.
#
# Skills pin a Carapace commit and keep using these functions after Carapace moves on, so the wrappers
# keep to the `cgate`/`ccred` contract in docs/sandbox.md.
{
  pkgs,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
  settingTypes,
}:
let
  inherit (pkgs) lib;

  # What a command needs from outside the sandbox: domains, the skill's secret slots it gets as environment
  # variables, its OAuth slots whose access token it fetches itself (`ccred get --access-token "$SLOT"`),
  # and tunnels as "host:port".
  noNeeds = {
    domains = [ ];
    credentials = [ ];
    oauth = [ ];
    tunnels = [ ];
  };

  isIdentifier = var: builtins.match "[A-Za-z_][A-Za-z0-9_]*" var != null;

  # A command's own `needs` replaces the skill-wide default per kind, so a command can drop or narrow
  # what the rest of the skill asks for. Checked here, which the metadata forces: a mistake fails
  # `nix eval` of `passthru.carapace` as well as the build.
  needsOf =
    where: slots: defaults: command:
    let
      needs = noNeeds // defaults // (command.needs or { });
      unknown = lib.subtractLists (lib.attrNames noNeeds) (lib.attrNames needs);
      literal = builtins.isAttrs needs.credentials;
      slotsOfType = type: lib.attrNames (lib.filterAttrs (_: slot: slot.type == type) slots);
      undeclared = if literal then [ ] else lib.subtractLists (slotsOfType "secret") needs.credentials;
      undeclaredOauth = lib.subtractLists (slotsOfType "oauth") needs.oauth;
      # What `cgate request --tunnel` accepts: an exact host name (any case, not an IP address, which a
      # client would connect to directly) and a port from 1 to 65535.
      badTunnels = lib.filter (
        tunnel:
        let
          parts = builtins.match "([A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*):([1-9][0-9]{0,4})" tunnel;
        in
        parts == null
        || builtins.match "[0-9.]+" (builtins.head parts) != null
        || lib.toInt (builtins.elemAt parts 2) > 65535
      ) needs.tunnels;
    in
    assert lib.assertMsg (unknown == [ ])
      "${where}: unknown kinds in needs: ${lib.concatStringsSep ", " unknown} (known: ${lib.concatStringsSep ", " (lib.attrNames noNeeds)})";
    # Vault paths belong to an instance: a skill names a slot, skills/config.json binds it.
    assert lib.assertMsg (!literal)
      "${where}: needs.credentials lists credential slots, not vault paths: declare credentials.${
        lib.head (lib.attrNames needs.credentials ++ [ "<NAME>" ])
      } = { type = \"secret\"; description = \"…\"; } in mkSkill, list it in needs.credentials, and bind it in skills/config.json";
    assert lib.assertMsg (undeclared == [ ])
      "${where}: needs.credentials names no secret slots of the skill: ${lib.concatStringsSep ", " undeclared}";
    assert lib.assertMsg (undeclaredOauth == [ ])
      "${where}: needs.oauth lists OAuth slots, not vault paths: declare credentials.<NAME> = { type = \"oauth\"; description = \"…\"; } in mkSkill and bind it in skills/config.json. Not an OAuth slot of the skill: ${lib.concatStringsSep ", " undeclaredOauth}";
    assert lib.assertMsg (badTunnels == [ ])
      "${where}: tunnels must be host:port with an exact host name: ${lib.concatStringsSep ", " badTunnels}";
    needs;

  checkSettings =
    name: settings:
    let
      where = "skill ${name}";
      # Each becomes an environment variable of the skill's commands.
      badNames = lib.filter (var: !isIdentifier var) (lib.attrNames settings);
      badTypes = lib.filter (setting: !(settingTypes ? ${settings.${setting}.type or ""})) (
        lib.attrNames settings
      );
    in
    assert lib.assertMsg (
      badNames == [ ]
    ) "${where}: setting names must be shell identifiers: ${lib.concatStringsSep ", " badNames}";
    assert lib.assertMsg (badTypes == [ ])
      "${where}: settings need a type, one of ${lib.concatStringsSep ", " (lib.attrNames settingTypes)}: ${lib.concatStringsSep ", " badTypes}";
    lib.mapAttrs (_: setting: { description = ""; } // setting) settings;

  # Credential slots the skill declares; skills/config.json binds each to a password-manager entry.
  checkCredentials =
    name: settings: credentials:
    let
      where = "skill ${name}";
      names = lib.attrNames credentials;
      # Each becomes an environment variable of the commands that need it, like a setting.
      badNames = lib.filter (var: !isIdentifier var) names;
      clashes = lib.intersectLists names (lib.attrNames settings);
      badTypes = lib.filter (
        slot:
        !builtins.elem (credentials.${slot}.type or "") [
          "secret"
          "oauth"
        ]
      ) names;
      # Anything else (a `default` vault path, say) would carry instance data in the flake.
      extraKeys = lib.filter (
        slot:
        removeAttrs credentials.${slot} [
          "type"
          "description"
        ] != { }
      ) names;
    in
    assert lib.assertMsg (badNames == [ ])
      "${where}: credential slot names must be shell identifiers: ${lib.concatStringsSep ", " badNames}";
    assert lib.assertMsg (
      clashes == [ ]
    ) "${where}: names used for a setting and a credential slot: ${lib.concatStringsSep ", " clashes}";
    assert lib.assertMsg (
      badTypes == [ ]
    ) "${where}: credential slots need type = \"secret\" or \"oauth\": ${lib.concatStringsSep ", " badTypes}";
    assert lib.assertMsg (extraKeys == [ ])
      "${where}: credential slots take only type and description, a binding goes into skills/config.json: ${lib.concatStringsSep ", " extraKeys}";
    lib.mapAttrs (_: slot: { description = ""; } // slot) credentials;

  # `needs` may depend on the skill's settings: a function from their values to the needs.
  withSettings = settings: needs: if lib.isFunction needs then needs settings else needs;

  # The values of settings and needs belong to an instance, not to the package: Carapace hands them to the
  # wrapper when it runs (`cgate request --command`), so every instance runs the same build.
  wrapper =
    command: gated:
    ''
      #!${pkgs.runtimeShell}
      set -eu
    ''
    # cgate and ccred come from the sandbox image, not from the skill: they talk to this Carapace. Assignment
    # and eval apart: `eval "$(…)"` would hide a failing cgate from `set -e`.
    + lib.optionalString gated ''
      gate="$(cgate request --store-path "@out@" --command ${lib.escapeShellArg command.name})"
      eval "$gate"
    ''
    + ''
      exec ${command.exec} "$@"
    '';

  # Only the named files of the skill directory, so a derivation built from them survives code edits.
  lockFiles =
    root: names:
    lib.fileset.toSource {
      inherit root;
      fileset = lib.fileset.unions (map (name: root + "/${name}") names);
    };

  # The skill directory with the dependencies linked in where Node looks for them.
  nodeApp =
    root: modules:
    pkgs.runCommand "skill-app" { passthru.nodeModules = modules; } ''
      cp -r ${
        lib.cleanSourceWith {
          src = root;
          filter = path: _type: baseNameOf path != "node_modules";
        }
      } $out
      chmod -R u+w $out
      ln -s ${modules}/node_modules $out/node_modules
    '';
in
{
  # The skill's package: one wrapper per command in bin/, so skills never collide on interpreters or
  # libraries in the session profile, and a reference to the skill directory (SKILL.md, scripts,
  # references), which brings it into every sandbox that installs the commands. The declarations travel as
  # `passthru.carapace`, which `skillsFlake` turns into the manifest the builder evaluates without building
  # anything; its `skillDir` is already in the store after that evaluation, so SKILL.md can be read before
  # the commands are built. `settings` are typed values from skills/config.json; a command sees each as an
  # environment variable, and `needs` (skill-wide or per command) may be a function of them.
  #
  #   mkSkill { name = "notes"; src = ./.; }   # instructions only
  #
  #   mkSkill {
  #     name = "weather";
  #     src = ./.;
  #     settings.CITY = { type = "str"; description = "City to report on"; default = "Berlin"; };
  #     credentials.WEATHER_TOKEN = { type = "secret"; description = "A weather API token"; };
  #     needs.domains = [ "api.example.com" ];
  #     commands.weather = { exec = "${env}/bin/weather"; description = "Current weather"; };
  #     commands.weather-offline = { exec = "..."; description = "..."; needs = { domains = [ ]; }; };
  #   }
  mkSkill =
    {
      name,
      src,
      commands ? { },
      needs ? { },
      settings ? { },
      credentials ? { },
    }:
    let
      # A store path of its own: with a `path:` input `src` lies inside the whole skills tree, which
      # would otherwise come along and change with every other skill.
      skillDir = builtins.path {
        path = src;
        name = "skill-${name}-src";
      };
      declaredSettings = checkSettings name settings;
      declaredCredentials = checkCredentials name settings credentials;
      slotNames = type: lib.attrNames (lib.filterAttrs (_: slot: slot.type == type) declaredCredentials);
      # Every command gets every slot of its type unless the needs say otherwise.
      slotDefaults = {
        credentials = slotNames "secret";
        oauth = slotNames "oauth";
      };
      skillWideNeeds = lib.optionalAttrs (!lib.isFunction needs) (
        needsOf "skill ${name}" declaredCredentials slotDefaults { inherit needs; }
      );
      commandNeeds =
        values:
        lib.mapAttrs (
          cmd: command:
          needsOf "skill ${name}, command ${cmd}" declaredCredentials (slotDefaults // withSettings values needs) (
            command // { needs = withSettings values (command.needs or { }); }
          )
        ) commands;
      # Whether a command asks Carapace before it runs: for its settings, or for needs it has or may have.
      gated =
        cmd: command:
        declaredSettings != { }
        || lib.isFunction needs
        || lib.isFunction (command.needs or { })
        || (commandNeeds { }).${cmd} != noNeeds;
    in
    pkgs.runCommand "skill-${name}"
      {
        passthru = {
          # What the skills flake (`skillsFlake`) and the builder read, as JSON.
          carapace = {
            inherit name;
            skillDir = "${skillDir}";
            settings = declaredSettings;
            # Forcing it checks the skill-wide needs too, which no command checks in a skill without commands.
            credentials = builtins.seq skillWideNeeds declaredCredentials;
            commands = lib.mapAttrs (_: command: {
              inherit (command) description;
              # `read_skill` runs `<cmd> --list-tools` for an MCP server, so the agent sees its tools.
              mcp = command.mcp or false;
            }) commands;
          };
          # Each command's needs for the given setting values; checked when `skillsFlake` resolves them.
          carapaceNeeds = commandNeeds;
        };
      }
      (
        ''
          mkdir -p $out/bin $out/share/carapace
          # A file named after the package, not a link: the session profile merges linked directories
          # and refuses two skills with a SKILL.md, even the same one.
          echo ${skillDir} > "$out/share/carapace/skill-dir-$(basename $out)"
        ''
        + lib.concatStrings (
          lib.mapAttrsToList (cmd: command: ''
            substitute ${
              pkgs.writeText "${cmd}-wrapper" (wrapper (command // { name = cmd; }) (gated cmd command))
            } $out/bin/${cmd} --subst-var out
            chmod +x $out/bin/${cmd}
          '') commands
        )
      );

  # Commands for MCP servers, one per attribute, for `mkSkill.commands`: `<name> --list-tools`,
  # `<name> <tool> --flag …`. They run the `mcp` bridge from the sandbox image; what they need follows
  # from the server: the URL's host, and the credential of `bearer` (a credential slot of the skill, holding
  # a token) or `oauth` (a vault entry Carapace refreshes, whose access token the bridge fetches itself). A stdio server declares its own
  # `needs`, which also override the derived ones per kind; the skill-wide `needs` do not apply.
  #
  #   commands = skill.mcpCommands {
  #     tracker = { url = "https://mcp.example.com/mcp"; oauth = "personal/tracker"; description = "…"; };
  #     search = { url = "https://search.example.com/mcp"; bearer = "SEARCH_TOKEN"; description = "…"; };
  #     notes = { command = "${notes}/bin/notes-mcp"; description = "…"; };
  #   };
  mcpCommands = lib.mapAttrs (
    name:
    {
      description,
      url ? null,
      command ? null,
      bearer ? null,
      oauth ? null,
      needs ? { },
    }:
    let
      where = "MCP server ${name}";
      # A host name and an optional port: no userinfo, whose `u@` would become the declared domain, and no
      # IP literal, which the proxy's domain review does not cover. HTTPS only, since tokens go along.
      authority =
        if url == null then null else builtins.match "https://([A-Za-z0-9.-]+)(:[0-9]+)?([/?#].*)?" url;
      host = if authority == null then null else builtins.head authority;
    in
    assert lib.assertMsg (
      (url == null) != (command == null)
    ) "${where}: set exactly one of url and command";
    assert lib.assertMsg (url == null || (host != null && builtins.match "[0-9.]+" host == null))
      "${where}: url must be https://<host name>[:port][/path], without userinfo or IP address: ${toString url}";
    assert lib.assertMsg (
      command == null || (bearer == null && oauth == null)
    ) "${where}: bearer and oauth apply to url; a stdio server takes credentials through needs";
    assert lib.assertMsg (
      bearer == null || oauth == null
    ) "${where}: set at most one of bearer and oauth";
    assert lib.assertMsg (bearer == null || isIdentifier bearer)
      "${where}: bearer names a credential slot of the skill (credentials.<NAME> in mkSkill), not a vault path: ${toString bearer}";
    {
      inherit description;
      mcp = true;
      exec = lib.concatStringsSep " " (
        [ "mcp --name ${lib.escapeShellArg name}" ]
        ++ lib.optional (url != null) "--url ${lib.escapeShellArg url}"
        ++ lib.optional (command != null) "--stdio ${lib.escapeShellArg command}"
        ++ lib.optional (bearer != null) "--bearer-env ${bearer}"
        ++ lib.optional (oauth != null) "--oauth ${lib.escapeShellArg oauth}"
      );
      # Every kind set, so the skill-wide needs do not leak into the server's command.
      needs =
        noNeeds
        // lib.optionalAttrs (url != null) { domains = [ host ]; }
        // lib.optionalAttrs (bearer != null) { credentials = [ bearer ]; }
        // lib.optionalAttrs (oauth != null) { oauth = [ oauth ]; }
        // needs;
    }
  );

  # A virtualenv from the skill's pyproject.toml and uv.lock. `overrides` is a pyproject-nix overlay
  # for what uv.lock does not record, typically the build system of a Git or sdist dependency:
  #   overrides = final: prev: {
  #     docopt = prev.docopt.overrideAttrs (old: {
  #       nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem { setuptools = [ ]; };
  #     });
  #   };
  uvEnv =
    {
      root,
      overrides ? (_final: _prev: { }),
      python ? pkgs.python3,
    }:
    let
      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = root; };
      pythonSet = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
        lib.composeManyExtensions [
          pyproject-build-systems.overlays.wheel
          (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
          overrides
        ]
      );
    in
    pythonSet.mkVirtualEnv "skill-env" workspace.deps.default;

  # The skill directory with its npm dependencies next to it, from package.json and package-lock.json.
  # node_modules is its own derivation built from the two lock files only, so editing the skill's code
  # does not install the dependencies again.
  npmApp =
    {
      root,
      nodejs ? pkgs.nodejs,
    }:
    nodeApp root (
      pkgs.importNpmLock.buildNodeModules {
        npmRoot = lockFiles root [
          "package.json"
          "package-lock.json"
        ];
        inherit nodejs;
      }
    );
}
