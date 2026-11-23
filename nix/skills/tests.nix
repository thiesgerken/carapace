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
    { tunnels = [ "imap.example.com:993" ]; }
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
    };
  };
in
assert pkgs.lib.assertMsg (pkgs.lib.all (x: x) rejected) "mkSkill accepted invalid needs";
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

  # A denial or a failing ccred stops the wrapper before the command runs. `if` rather than `!`, which
  # errexit ignores.
  if CGATE_DENY=1 ${skill}/bin/show-token > out; then exit 1; fi
  [ ! -s out ]
  if CCRED_FAIL=1 ${skill}/bin/show-token > out; then exit 1; fi
  [ ! -s out ]

  # The package holds the wrappers and nothing else.
  [ "$(ls -A ${skill})" = bin ]
  touch $out
''
