# The wrapper contract: what a generated command does before the real one starts, and the manifests
# `skillsFlake` resolves from skills/config.json. Runs with a stand-in for cgate that logs its calls, so it
# needs no Carapace.
{
  pkgs,
  skillLib,
  skillsFlake,
}:
let
  inherit (pkgs) lib;
  inherit (pkgs.stdenv.hostPlatform) system;
  fixture = ./examples/nix;
  # A mistake in `needs` fails the metadata the builder evaluates, not only the build.
  rejects =
    needs:
    let
      bad = skillLib.mkSkill {
        src = fixture;
        name = "bad";
        commands.cmd = {
          exec = "true";
          description = "Invalid needs";
          inherit needs;
        };
      };
    in
    !(builtins.tryEval (builtins.toJSON (bad.passthru.carapaceNeeds { }))).success;
  rejected = map rejects [
    { domain = [ "api.example.com" ]; }
    # A literal vault path, the form before credential slots, and a slot the skill does not declare.
    { credentials.TOKEN = "demo/token"; }
    { credentials = [ "UNDECLARED" ]; }
    { credentials."A=B" = "demo/token"; }
    # An OAuth vault path, the form before OAuth slots.
    { oauth = [ "demo/tracker-oauth" ]; }
    { credentials."TOKEN; rm -rf ~" = "demo/token"; }
    { tunnels = [ "imap.example.com" ]; }
    { tunnels = [ "*.example.com:993" ]; }
    { tunnels = [ "imap.example.com:0" ]; }
    { tunnels = [ "imap.example.com:0993" ]; }
    { tunnels = [ "imap.example.com:65536" ]; }
    { tunnels = [ "10.0.0.1:5432" ]; }
  ];
  # MCP servers: the bridge's arguments and what each command declares follow from the server.
  mcp = skillLib.mkSkill {
    src = fixture;
    name = "mcp-contract";
    credentials = {
      UNRELATED.type = "secret";
      NOTES_TOKEN.type = "secret";
      TRACKER_OAUTH.type = "oauth";
    };
    settings.SEARCH_URL.type = "str";
    commands = skillLib.mcpCommands {
      tracker = {
        url = "https://mcp.example.com/mcp";
        oauth = "TRACKER_OAUTH";
        description = "An OAuth HTTP server";
      };
      search = {
        urlSetting = "SEARCH_URL";
        description = "An HTTP server at an instance's URL";
      };
      notes = {
        url = "https://notes.example.com:8443/mcp";
        bearer = "NOTES_TOKEN";
        description = "A bearer HTTP server";
      };
      local = {
        command = "local-mcp --stdio";
        description = "A stdio server";
      };
    };
  };
  # Instructions only: no commands, just the skill directory.
  notes = skillLib.mkSkill {
    name = "notes";
    src = fixture;
  };
  mcpNeeds = mcp.passthru.carapaceNeeds { SEARCH_URL = "https://search.example.com:8443/mcp"; };
  # The URL a setting gives is checked like a fixed one, when the manifest is evaluated.
  badSearchUrl = map (url: fails (mcp.passthru.carapaceNeeds { SEARCH_URL = url; }).search) [
    "http://search.example.com/mcp"
    "https://10.0.0.1/mcp"
    "https://user@search.example.com/mcp"
  ];
  # Only MCP commands are marked, so `read_skill` lists tools for them and nothing else.
  marks = package: pkgs.lib.mapAttrs (_: command: command.mcp) package.passthru.carapace.commands;
  rejectsMcp =
    server:
    !(builtins.tryEval (
      builtins.toJSON (
        (skillLib.mkSkill {
          src = fixture;
          name = "bad-mcp";
          commands = skillLib.mcpCommands {
            bad = {
              description = "Invalid server";
            }
            // server;
          };
        }).passthru.carapaceNeeds
          { }
      )
    )).success;
  rejectedMcp = map rejectsMcp [
    {
      url = "https://mcp.example.com/mcp";
      bearer = "demo/token";
    }
    {
      url = "https://mcp.example.com/mcp";
      oauth = "demo/tracker-oauth";
    }
    # A setting the skill does not declare.
    { urlSetting = "MISSING_URL"; }
    {
      url = "https://mcp.example.com/mcp";
      urlSetting = "SEARCH_URL";
    }
    { url = "http://mcp.example.com/mcp"; }
    { url = "https://user:secret@mcp.example.com/mcp"; }
    { url = "https://user@mcp.example.com/mcp"; }
    { url = "https://[::1]/mcp"; }
    { url = "https://10.0.0.1/mcp"; }
    {
      url = "https://mcp.example.com/mcp";
      command = "local-mcp";
    }
    {
      command = "local-mcp";
      bearer = "demo/token";
    }
  ];
  skill = skillLib.mkSkill {
    src = fixture;
    name = "contract";
    credentials.DEMO_TOKEN = {
      type = "secret";
      description = "The demo API's token";
    };
    needs.domains = [ "api.example.com" ];
    commands = {
      show-token = {
        exec = "${pkgs.coreutils}/bin/printenv FROM_CGATE";
        description = "Print what the wrapper took from cgate";
      };
      local = {
        exec = "${pkgs.coreutils}/bin/echo local";
        description = "Needs nothing";
        needs = {
          domains = [ ];
          credentials = [ ];
        };
      };
      mail = {
        exec = "${pkgs.coreutils}/bin/echo mail";
        description = "Needs a tunnel and nothing else";
        needs = {
          domains = [ ];
          credentials = [ ];
          # Any case, like the server, which lowercases it.
          tunnels = [ "Imap.example.com:993" ];
        };
      };
    };
  };
  # A skill with settings: its needs follow from their values, which skills/config.json sets.
  weather = skillLib.mkSkill {
    src = fixture;
    name = "weather";
    settings = {
      CITY = {
        type = "str";
        description = "The city to report on";
      };
      PORT = {
        type = "int";
        default = 443;
      };
    };
    needs = settings: { domains = [ "${lib.toLower settings.CITY}.example.com" ]; };
    commands.show = {
      exec = "${pkgs.coreutils}/bin/printenv FROM_CGATE";
      description = "Print what cgate exported";
    };
  };
  manifestsWith =
    values:
    (skillsFlake {
      inputs = {
        self = { };
        nixpkgs = { };
        carapace = { };
        weather.packages.${system}.default = weather;
        contract.packages.${system}.default = skill;
        notes.packages.${system}.default = notes;
        # A local skill whose flake.nix is broken, or missing from the archive of another skill's build.
        broken.packages.${system}.default = throw "skills/broken/flake.nix: syntax error";
      };
      config = builtins.toFile "config.json" (builtins.toJSON values);
    }).manifests.${system};
  configured = manifestsWith {
    weather.settings.CITY = "Berlin";
    contract.credentials.DEMO_TOKEN = "demo/token";
    # Named in config.json, so the module system would read its flake while checking the definitions.
    broken.enable = false;
  };
  fails = value: !(builtins.tryEval (builtins.toJSON value)).success;
in
assert pkgs.lib.assertMsg (pkgs.lib.all (x: x) rejected) "mkSkill accepted invalid needs";
assert pkgs.lib.assertMsg (pkgs.lib.all (
  x: x
) rejectedMcp) "mcpCommands accepted an invalid server";
assert pkgs.lib.assertMsg (
  mcpNeeds == {
    tracker = {
      domains = [ "mcp.example.com" ];
      credentials = [ ];
      oauth = [ "TRACKER_OAUTH" ];
      tunnels = [ ];
    };
    search = {
      domains = [ "search.example.com" ];
      credentials = [ ];
      oauth = [ ];
      tunnels = [ ];
    };
    notes = {
      domains = [ "notes.example.com" ];
      credentials = [ "NOTES_TOKEN" ];
      oauth = [ ];
      tunnels = [ ];
    };
    local = {
      domains = [ ];
      credentials = [ ];
      oauth = [ ];
      tunnels = [ ];
    };
  }
) "mcpCommands declared the wrong needs: ${builtins.toJSON mcpNeeds}";
assert pkgs.lib.assertMsg
  (
    marks mcp == {
      tracker = true;
      search = true;
      notes = true;
      local = true;
    }
    &&
      marks skill == {
        show-token = false;
        local = false;
        mail = false;
      }
  )
  "mkSkill marked the wrong commands as MCP servers: ${
    builtins.toJSON [
      (marks mcp)
      (marks skill)
    ]
  }";
assert pkgs.lib.assertMsg (
  configured.weather.settings == {
    CITY = "Berlin";
    PORT = 443;
  }
  && configured.weather.commands.show.needs.domains == [ "berlin.example.com" ]
  && configured.weather.enable
  &&
    configured.notes == {
      enable = true;
      name = "notes";
      skillDir = notes.passthru.carapace.skillDir;
      settings = { };
      credentials = { };
      commands = { };
    }
  &&
    configured.contract.credentials.DEMO_TOKEN == {
      type = "secret";
      description = "The demo API's token";
      binding = "demo/token";
    }
  && configured.contract.commands.show-token.needs.credentials == { DEMO_TOKEN = "demo/token"; }
  && configured.contract.commands.local.needs.credentials == { }
) "skillsFlake resolved the wrong manifests: ${builtins.toJSON configured}";
# An unbound slot stays in the manifest as null, for Carapace to refuse the commands that need it.
assert pkgs.lib.assertMsg (
  let
    unbound = (manifestsWith { weather.settings.CITY = "Berlin"; }).contract;
  in
  unbound.credentials.DEMO_TOKEN.binding == null
  && unbound.commands.show-token.needs.credentials == { DEMO_TOKEN = null; }
) "skillsFlake did not leave an unbound slot null";
assert pkgs.lib.assertMsg (fails
  (manifestsWith {
    weather.settings.CITY = "Berlin";
    contract.credentials.DEMO_TOKEN = "not a vault path";
  }).contract
) "skillsFlake accepted a binding that is no vault path";
# A required setting without a value fails, also for every other key of config.json; a skill that is off
# needs none.
assert pkgs.lib.assertMsg (fails
  (manifestsWith { }).weather
) "skillsFlake accepted a missing setting";
assert pkgs.lib.assertMsg (fails
  (manifestsWith {
    weather.settings = {
      CITY = "Berlin";
      COLOR = "red";
    };
  }).weather
) "skillsFlake accepted an undeclared setting";
assert pkgs.lib.assertMsg (
  fails (manifestsWith { weather.settings.CITY = 7; }).weather
  && !fails (manifestsWith { weather.settings.CITY = 7; }).notes
) "skillsFlake accepted a setting of the wrong type, or failed another skill for it";
assert pkgs.lib.assertMsg (fails
  (manifestsWith { typo.enable = false; }).notes
) "skillsFlake accepted a skill that is not listed";
# The others' manifests never touch it (the asserts above evaluate them next to it), only its own fails.
assert pkgs.lib.assertMsg (fails configured.broken) "skillsFlake evaluated a broken skill";
assert pkgs.lib.assertMsg (
  (manifestsWith { weather.enable = false; }).weather == { enable = false; }
) "skillsFlake did not turn weather off";
assert pkgs.lib.assertMsg (fails
  (skillLib.mkSkill {
    src = fixture;
    name = "bad-settings";
    settings."NOT-A-VAR".type = "str";
  }).passthru.carapace
) "mkSkill accepted a setting that is no shell identifier";
assert pkgs.lib.assertMsg (fails
  (skillLib.mkSkill {
    src = fixture;
    name = "bad-settings";
    settings.URL.type = "url";
  }).passthru.carapace
) "mkSkill accepted an unknown setting type";
assert pkgs.lib.assertMsg (fails
  (skillLib.mkSkill {
    src = fixture;
    name = "bad-slot";
    credentials.TOKEN = {
      type = "secret";
      default = "demo/token";
    };
  }).passthru.carapace
) "mkSkill accepted a credential slot with a default";
assert pkgs.lib.assertMsg (fails
  (skillLib.mkSkill {
    src = fixture;
    name = "bad-skill-wide";
    needs.credentials.TOKEN = "demo/token";
  }).passthru.carapace
) "mkSkill accepted a skill-wide vault path on a skill without commands";
assert pkgs.lib.assertMsg (pkgs.lib.all (
  x: x
) badSearchUrl) "mcpCommands accepted an invalid URL from a setting";
assert pkgs.lib.assertMsg (
  let
    server =
      settings: extra:
      skillLib.mkSkill {
        src = fixture;
        name = "url-checks";
        inherit settings;
        commands = skillLib.mcpCommands {
          search = {
            description = "A server whose needs override the derived domains";
            needs.domains = [ "search.example.com" ];
          }
          // extra;
        };
      };
    str.SEARCH_URL.type = "str";
  in
  # A fixed URL is checked although the needs override its domain.
  fails (server { } { url = "http://search.example.com/mcp"; }).passthru.carapace.commands
  # A setting's URL too, when the manifest resolves the needs.
  && fails (
    (server str { urlSetting = "SEARCH_URL"; }).passthru.carapaceNeeds {
      SEARCH_URL = "http://search.example.com/mcp";
    }
  )
  # The setting must exist and be a string, already for the package.
  && fails (server { } { urlSetting = "SEARCH_URL"; }).drvPath
  && fails (server { SEARCH_URL.type = "int"; } { urlSetting = "SEARCH_URL"; }).drvPath
  && !fails (server str { urlSetting = "SEARCH_URL"; }).drvPath
) "mcpCommands let a URL past its checks";
pkgs.runCommand "skill-wrapper-contract" { } ''
  mkdir stubs
  # Carapace answers with the setting values and credentials as shell code; here a marker stands for them.
  cat > stubs/cgate <<'STUB'
  #!${pkgs.runtimeShell}
  echo "cgate $*" >> "$CALLS"
  [ -z "''${CGATE_DENY:-}" ] || { echo "error: denied" >&2; exit 1; }
  echo "export FROM_CGATE=$5 TRACKER_OAUTH=demo/tracker-oauth SEARCH_URL=https://search.example.com:8443/mcp"
  STUB
  chmod +x stubs/*
  export PATH="$PWD/stubs:$PATH" CALLS="$PWD/calls"

  # A command with needs asks Carapace once by name, takes what it exports, then runs.
  [ "$(${skill}/bin/show-token)" = show-token ]
  ${skill}/bin/mail
  printf '%s\n' \
    "cgate request --store-path ${skill} --command show-token" \
    "cgate request --store-path ${skill} --command mail" | diff - calls

  # A command whose override drops all needs asks for nothing.
  rm calls
  [ "$(${skill}/bin/local)" = local ]
  [ ! -e calls ]

  # Settings make every command ask, for their values; here the stand-in's marker reaches the command.
  rm -f calls
  [ "$(${weather}/bin/show)" = show ]
  echo "cgate request --store-path ${weather} --command show" | diff - calls

  # A denial stops the wrapper before the command runs. `if` rather than `!`, which errexit ignores.
  if CGATE_DENY=1 ${weather}/bin/show > out; then exit 1; fi
  [ ! -s out ]

  # MCP commands ask like any other; the bridge gets its server's address. The skill has a setting, so
  # even the stdio server without needs asks, for its value.
  cat > stubs/mcp <<'STUB'
  #!${pkgs.runtimeShell}
  echo "mcp $* FROM_CGATE=''${FROM_CGATE:-}" >> "$CALLS"
  STUB
  chmod +x stubs/mcp
  rm calls
  ${mcp}/bin/tracker --list-tools
  ${mcp}/bin/notes search --query 'a b'
  ${mcp}/bin/search --list-tools
  ${mcp}/bin/local --list-tools
  printf '%s\n' \
    "cgate request --store-path ${mcp} --command tracker" \
    "mcp --name tracker --url https://mcp.example.com/mcp --oauth demo/tracker-oauth --list-tools FROM_CGATE=tracker" \
    "cgate request --store-path ${mcp} --command notes" \
    "mcp --name notes --url https://notes.example.com:8443/mcp --bearer-env NOTES_TOKEN search --query a b FROM_CGATE=notes" \
    "cgate request --store-path ${mcp} --command search" \
    "mcp --name search --url https://search.example.com:8443/mcp --list-tools FROM_CGATE=search" \
    "cgate request --store-path ${mcp} --command local" \
    "mcp --name local --stdio local-mcp --stdio --list-tools FROM_CGATE=local" | diff - calls

  # The package holds the wrappers and a reference to the skill directory the metadata names.
  [ "$(ls -A ${skill} | tr '\n' ' ')" = "bin share " ]
  [ "$(cat ${skill}/share/carapace/skill-dir-*)" = ${skill.passthru.carapace.skillDir} ]
  cmp ${skill.passthru.carapace.skillDir}/SKILL.md ${fixture}/SKILL.md
  [ -z "$(ls -A ${notes}/bin)" ]
  cmp ${notes.passthru.carapace.skillDir}/SKILL.md ${fixture}/SKILL.md
  touch $out
''
