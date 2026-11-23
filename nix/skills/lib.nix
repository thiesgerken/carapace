# Functions a skill flake uses to package its commands. See docs/skill-flakes.md.
#
# Skills pin a released Carapace commit and keep using these functions after Carapace moves on, so
# their arguments only grow, and the wrappers keep to the `cgate`/`ccred` contract in docs/sandbox.md.
{
  pkgs,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
}:
let
  inherit (pkgs) lib;

  # What a command needs from outside the sandbox: domains, credentials as env var -> vault path, and
  # tunnels as "host:port".
  noNeeds = {
    domains = [ ];
    credentials = { };
    tunnels = [ ];
  };

  # A command's own `needs` replaces the skill-wide default per kind, so a command can drop or narrow
  # what the rest of the skill asks for. Checked here, which the metadata forces: a mistake fails
  # `nix eval` of `passthru.carapace` as well as the build.
  needsOf =
    where: defaults: command:
    let
      needs = noNeeds // defaults // (command.needs or { });
      unknown = lib.subtractLists (lib.attrNames noNeeds) (lib.attrNames needs);
      # Spliced into the wrapper as `VAR="$(ccred get …)"; export VAR`.
      badVars = lib.filter (var: builtins.match "[A-Za-z_][A-Za-z0-9_]*" var == null) (
        lib.attrNames needs.credentials
      );
    in
    assert lib.assertMsg (unknown == [ ])
      "${where}: unknown kinds in needs: ${lib.concatStringsSep ", " unknown} (known: domains, credentials, tunnels)";
    assert lib.assertMsg (
      badVars == [ ]
    ) "${where}: credential variables must be shell identifiers: ${lib.concatStringsSep ", " badVars}";
    assert lib.assertMsg (needs.tunnels == [ ]) "${where}: tunnels are not supported by cgate yet";
    needs;

  wrapper =
    command: needs:
    let
      gateArgs =
        map (domain: "--domain ${lib.escapeShellArg domain}") needs.domains
        ++ map (path: "--credential ${lib.escapeShellArg path}") (lib.attrValues needs.credentials);
      # Assignment and export apart: `export X="$(…)"` would hide a failing ccred from `set -e`.
      exports = lib.mapAttrsToList (var: path: ''
        ${var}="$(ccred get ${lib.escapeShellArg path})"
        export ${var}'') needs.credentials;
    in
    ''
      #!${pkgs.runtimeShell}
      set -eu
    ''
    # cgate and ccred come from the sandbox image, not from the skill: they talk to this Carapace.
    + lib.optionalString (gateArgs != [ ]) ''
      cgate request --store-path "@out@" ${lib.concatStringsSep " " gateArgs}
    ''
    + lib.concatMapStrings (line: line + "\n") exports
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
  # The skill's package: nothing but one wrapper per command in bin/, so skills never collide on
  # interpreters or libraries in the session profile. The declarations travel as `passthru.carapace`,
  # which the builder evaluates without building anything.
  #
  #   mkSkill {
  #     name = "weather";
  #     needs = { domains = [ "api.example.com" ]; credentials.WEATHER_TOKEN = "personal/weather"; };
  #     commands.weather = { exec = "${env}/bin/weather"; description = "Current weather"; };
  #     commands.weather-offline = { exec = "..."; description = "..."; needs = { domains = [ ]; }; };
  #   }
  mkSkill =
    {
      name,
      commands,
      needs ? { },
    }:
    let
      declared = lib.mapAttrs (cmd: command: {
        inherit (command) description;
        needs = needsOf "skill ${name}, command ${cmd}" needs command;
      }) commands;
    in
    pkgs.runCommand "skill-${name}"
      {
        passthru.carapace = {
          inherit name;
          commands = declared;
        };
      }
      (
        ''
          mkdir -p $out/bin
        ''
        + lib.concatStrings (
          lib.mapAttrsToList (cmd: command: ''
            substitute ${pkgs.writeText "${cmd}-wrapper" (wrapper command declared.${cmd}.needs)} \
              $out/bin/${cmd} --subst-var out
            chmod +x $out/bin/${cmd}
          '') commands
        )
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

  # The same for pnpm. pnpm-lock.yaml lacks the hashes Nix needs, so the dependencies are a
  # fixed-output derivation: `hash` changes whenever the lock file does (build once with
  # `lib.fakeHash`, then take the hash from the error).
  pnpmApp =
    {
      root,
      hash,
      nodejs ? pkgs.nodejs,
      pnpm ? pkgs.pnpm,
    }:
    let
      src = lockFiles root [
        "package.json"
        "pnpm-lock.yaml"
      ];
    in
    nodeApp root (
      pkgs.stdenvNoCC.mkDerivation {
        name = "skill-node-modules";
        inherit src;
        nativeBuildInputs = [
          nodejs
          pnpm
          pkgs.pnpmConfigHook
        ];
        pnpmDeps = pkgs.fetchPnpmDeps {
          pname = "skill-node-modules";
          version = "0";
          inherit src pnpm hash;
          fetcherVersion = 5;
        };
        installPhase = ''
          mkdir -p $out
          cp -r node_modules $out/
        '';
      }
    );
}
