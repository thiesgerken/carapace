# The wrapper contract: what a generated command does before the real one starts. Runs with stand-ins for
# cgate and ccred that log their calls, so it needs no Carapace.
{ pkgs, skillLib }:
let
  # A mistake in `needs` fails the metadata the builder evaluates, not only the build.
  rejects =
    needs:
    let
      bad = skillLib.mkSkill {
        name = "bad";
        commands.cmd = {
          exec = "true";
          description = "Invalid needs";
          inherit needs;
        };
      };
    in
    !(builtins.tryEval (builtins.toJSON bad.passthru.carapace)).success;
  rejected = map rejects [
    { domain = [ "api.example.com" ]; }
    { credentials."A=B" = "demo/token"; }
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
    name = "mcp-contract";
    needs.credentials.UNRELATED = "demo/unrelated";
    commands = skillLib.mcpCommands {
      tracker = {
        url = "https://mcp.example.com/mcp";
        oauth = "demo/tracker-oauth";
        description = "An OAuth HTTP server";
      };
      notes = {
        url = "https://notes.example.com:8443/mcp";
        bearer = "demo/notes-token";
        description = "A bearer HTTP server";
      };
      local = {
        command = "local-mcp --stdio";
        description = "A stdio server";
      };
    };
  };
  mcpNeeds = pkgs.lib.mapAttrs (_: command: command.needs) mcp.passthru.carapace.commands;
  rejectsMcp =
    server:
    !(builtins.tryEval (
      builtins.toJSON
        (skillLib.mkSkill {
          name = "bad-mcp";
          commands = skillLib.mcpCommands {
            bad = {
              description = "Invalid server";
            }
            // server;
          };
        }).passthru.carapace
    )).success;
  rejectedMcp = map rejectsMcp [
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
    name = "contract";
    needs = {
      domains = [ "api.example.com" ];
      credentials.DEMO_TOKEN = "demo/token";
    };
    commands = {
      show-token = {
        exec = "${pkgs.coreutils}/bin/printenv DEMO_TOKEN";
        description = "Print the token the wrapper exported";
      };
      local = {
        exec = "${pkgs.coreutils}/bin/echo local";
        description = "Needs nothing";
        needs = {
          domains = [ ];
          credentials = { };
        };
      };
      mail = {
        exec = "${pkgs.coreutils}/bin/echo mail";
        description = "Needs a tunnel and nothing else";
        needs = {
          domains = [ ];
          credentials = { };
          # Any case, like the server, which lowercases it.
          tunnels = [ "Imap.example.com:993" ];
        };
      };
    };
  };
in
assert pkgs.lib.assertMsg (pkgs.lib.all (x: x) rejected) "mkSkill accepted invalid needs";
assert pkgs.lib.assertMsg (pkgs.lib.all (
  x: x
) rejectedMcp) "mcpCommands accepted an invalid server";
assert pkgs.lib.assertMsg (
  mcpNeeds == {
    tracker = {
      domains = [ "mcp.example.com" ];
      credentials = { };
      oauth = [ "demo/tracker-oauth" ];
      tunnels = [ ];
    };
    notes = {
      domains = [ "notes.example.com" ];
      credentials.MCP_BEARER_TOKEN = "demo/notes-token";
      oauth = [ ];
      tunnels = [ ];
    };
    local = {
      domains = [ ];
      credentials = { };
      oauth = [ ];
      tunnels = [ ];
    };
  }
) "mcpCommands declared the wrong needs: ${builtins.toJSON mcpNeeds}";
pkgs.runCommand "skill-wrapper-contract" { } ''
  mkdir stubs
  cat > stubs/cgate <<'STUB'
  #!${pkgs.runtimeShell}
  echo "cgate $*" >> "$CALLS"
  [ -z "''${CGATE_DENY:-}" ] || { echo "error: denied" >&2; exit 1; }
  STUB
  cat > stubs/ccred <<'STUB'
  #!${pkgs.runtimeShell}
  echo "ccred $*" >> "$CALLS"
  [ -z "''${CCRED_FAIL:-}" ] || exit 1
  echo s3cret
  STUB
  chmod +x stubs/*
  export PATH="$PWD/stubs:$PATH" CALLS="$PWD/calls"

  # A declared command asks once up front, then fetches its credential, then runs.
  [ "$(${skill}/bin/show-token)" = s3cret ]
  printf '%s\n' \
    "cgate request --store-path ${skill} --domain api.example.com --credential demo/token" \
    "ccred get demo/token" | diff - calls

  # A command whose override drops all needs asks for nothing.
  rm calls
  [ "$(${skill}/bin/local)" = local ]
  [ ! -e calls ]

  # A tunnel is asked for up front like a domain; the server opens it before cgate returns.
  [ "$(${skill}/bin/mail)" = mail ]
  echo "cgate request --store-path ${skill} --tunnel Imap.example.com:993" | diff - calls

  # A denial or a failing ccred stops the wrapper before the command runs. `if` rather than `!`, which
  # errexit ignores.
  if CGATE_DENY=1 ${skill}/bin/show-token > out; then exit 1; fi
  [ ! -s out ]
  if CCRED_FAIL=1 ${skill}/bin/show-token > out; then exit 1; fi
  [ ! -s out ]

  # An MCP command asks for its server's domain and OAuth entry, then hands the bridge its address.
  cat > stubs/mcp <<'STUB'
  #!${pkgs.runtimeShell}
  echo "mcp $* MCP_BEARER_TOKEN=''${MCP_BEARER_TOKEN:-}" >> "$CALLS"
  STUB
  chmod +x stubs/mcp
  rm calls
  ${mcp}/bin/tracker --list-tools
  ${mcp}/bin/notes search --query 'a b'
  ${mcp}/bin/local --list-tools
  printf '%s\n' \
    "cgate request --store-path ${mcp} --domain mcp.example.com --oauth demo/tracker-oauth" \
    "mcp --name tracker --url https://mcp.example.com/mcp --oauth demo/tracker-oauth --list-tools MCP_BEARER_TOKEN=" \
    "cgate request --store-path ${mcp} --domain notes.example.com --credential demo/notes-token" \
    "ccred get demo/notes-token" \
    "mcp --name notes --url https://notes.example.com:8443/mcp --bearer-env MCP_BEARER_TOKEN search --query a b MCP_BEARER_TOKEN=s3cret" \
    "mcp --name local --stdio local-mcp --stdio --list-tools MCP_BEARER_TOKEN=" | diff - calls

  # The package holds the wrappers and nothing else.
  [ "$(ls -A ${skill})" = bin ]
  touch $out
''
