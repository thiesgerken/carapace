# Skill flakes

Every skill is a Nix flake: `flake.nix` and `flake.lock` live in the skill directory next to its `SKILL.md`. The flake's package holds the skill directory and one wrapper per command. The Carapace builder builds it whenever the skill changes; the server reads `SKILL.md` from the build, and every session gets the commands on its `PATH` and the skill directory in its store. A skill that only carries instructions is a [flake of a few lines](#skills-with-only-instructions).

The functions below come from the skills subflake of the Carapace repo, `github:thiesgerken/carapace?dir=nix/skills` ([`nix/skills/flake.nix`](../nix/skills/flake.nix)). It has only `nixpkgs` and the uv2nix stack as inputs, so a skill's `flake.lock` stays small. Three working examples live in [`nix/skills/examples`](../nix/skills/examples): uv, npm and plain nixpkgs. CI builds them against the helpers of the current checkout. The bundled skills with commands (`src/carapace/assets/skills`) are flakes too; CI builds them both against the commit their `flake.lock` pins and against the current helpers.

## The flake

```nix
{
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
          pkgs = nixpkgs.legacyPackages.${system};
          skill = carapace.lib.skill pkgs;
          env = skill.uvEnv { root = ./.; };
        in
        {
          default = skill.mkSkill {
            name = "weather";
            src = ./.;
            needs = {
              domains = [ "api.example.com" ];
              credentials.WEATHER_TOKEN = "personal/weather-token";
            };
            commands = {
              weather = {
                exec = "${env}/bin/weather";
                description = "Current weather for a city";
              };
              weather-units = {
                exec = "${env}/bin/weather-units";
                description = "List the supported units, offline";
                needs = {
                  domains = [ ];
                  credentials = { };
                };
              };
            };
          };
        }
      );
    };
}
```

- Each skill locks its own `nixpkgs`, so one skill can move to a newer one without touching the others. `inputs.nixpkgs.follows` makes the Carapace helpers use the same one.
- `carapace` pins a Carapace commit in `flake.lock`. The wrappers keep working when Carapace moves on; a skill updates its pin when it wants something new. Helpers whose `mkSkill` takes no `src` build packages without `skillDir`, which the server cannot read: such a skill shows as failed until it updates its pin.
- `flake.lock` must be committed and complete: the builder never writes locks. Run `nix flake lock` after changing inputs.
- The build sees nothing but the skill directory (`nix build path:<dir>`). Evaluation runs with import-from-derivation off, which all helpers support.
- `forSkillSystems` covers `x86_64-linux` and `aarch64-linux`, the architectures sandboxes run on.

## Commands and what they need

`mkSkill { name, src, commands ? { }, needs ? { } }` builds the package. `src` is the skill directory, normally `./.`: it becomes a store path of its own, linked as `skill/` in the package, so the sandbox gets `SKILL.md`, scripts and references together with the commands. Each command has:

- `exec`: what the wrapper runs, with the wrapper's arguments appended. It is shell words, not quoted for you: it gets word-split and expanded, which is what lets a store path carry fixed arguments (`"${pkgs.nodejs}/bin/node ${app}/src/main.mjs"`). A path with spaces needs its own quoting.
- `description`: one short line, shown to the agent.
- `needs` (optional): overrides the skill-wide `needs`, per kind. A command that sets `domains = [ ]` asks for no domains, whatever the default says.

`needs` declares what a command will want from outside the sandbox. Any other key, an invalid variable name or a malformed tunnel fails the evaluation, also of the metadata below:

- `domains`: host names, or `*.` plus a name of at least two labels.
- `credentials`: environment variable to vault path. The wrapper exports each one before the command starts. Variable names must be shell identifiers.
- `oauth`: vault paths of OAuth entries whose access token the command fetches itself with `ccred get --access-token`, as the MCP bridge does. Declared up front, exported nothing.
- `tunnels`: `"host:port"` with an exact host name (not an IP address) and a port from 1 to 65535, for clients that do not speak HTTP. Requested with `cgate request --tunnel` and open when the command starts; see [sandbox.md](sandbox.md#tunnels).

A command that declares something gets a wrapper that first asks for all of it at once, then fetches the credentials, then runs the command:

```sh
cgate request --store-path "/nix/store/…-skill-weather" --domain api.example.com --credential personal/weather-token
WEATHER_TOKEN="$(ccred get personal/weather-token)"
export WEATHER_TOKEN
exec /nix/store/…-skill-env/bin/weather "$@"
```

The sentinel decides once, with the whole `exec` in view. A denial or a failing `ccred` stops the wrapper before the command runs, with the reason on stderr. Declarations are a batching hint and carry no trust; what a command was not declared to need still works and is reviewed when it is requested (see [Declaring needs up front](sandbox.md#declaring-needs-up-front-cgate)). A command with no needs gets a plain `exec` wrapper.

`cgate` and `ccred` come from the sandbox image, not from the skill. Their contract is documented in [sandbox.md](sandbox.md#cli-contract), and it is what keeps wrappers built against an older Carapace working.

## Metadata for the builder: `passthru.carapace`

The package carries what the builder and the session need to know about the commands, readable without building anything:

```sh
nix eval --json 'path:<skill dir>#packages.x86_64-linux.default.carapace'
```

```json
{
  "name": "weather",
  "skillDir": "/nix/store/…-skill-weather-src",
  "commands": {
    "weather": {
      "description": "Current weather for a city",
      "needs": {
        "domains": ["api.example.com"],
        "credentials": { "WEATHER_TOKEN": "personal/weather-token" },
        "oauth": [],
        "tunnels": []
      },
      "mcp": false
    },
    "weather-units": {
      "description": "List the supported units, offline",
      "needs": { "domains": [], "credentials": {}, "oauth": [], "tunnels": [] },
      "mcp": false
    }
  }
}
```

- `skillDir` is the store path of `src`. The evaluation already copies it into the store, so the builder can read `SKILL.md` from it before the commands are built.
- `commands` has one entry per wrapper in `bin/`, under the same name.
- `needs` is already resolved: the skill-wide default with the command's override applied, every kind present.
- `mcp` is `true` for a command made by `mcpCommands`; `read_skill` lists its tools. Packages built with an older `mkSkill` have no `mcp`, which counts as `false`.
- The builder passes this on as opaque JSON; the server reads it. Fields are only ever added.

## Skills with only instructions

A skill without commands still needs a flake, so that it is built and listed like any other:

```nix
{
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
      packages = carapace.lib.forSkillSystems (system: {
        default = (carapace.lib.skill nixpkgs.legacyPackages.${system}).mkSkill {
          name = "notes";
          src = ./.;
        };
      });
    };
}
```

Its package has an empty `bin/` and the skill directory. The bundled `artifacts`, `mermaid`, `create-skill` and `credentials` skills are built this way.

## MCP servers

An MCP server becomes a command like any other: `<server> --list-tools`, `<server> <tool> --help`, `<server> <tool> --flag value`. `mcpCommands` makes one command per attribute, for `mkSkill`'s `commands`:

```nix
default = skill.mkSkill {
  name = "tracker";
  commands = skill.mcpCommands {
    tracker = {
      url = "https://mcp.example.com/mcp";
      oauth = "personal/tracker-oauth";
      description = "Issues in the example tracker";
    };
    notes = {
      command = "${notesServer}/bin/notes-mcp --stdio";
      description = "Local notes, over stdio";
      needs.credentials.NOTES_TOKEN = "personal/notes-token";
    };
  };
};
```

- `url` (streamable HTTP) or `command` (a shell command that starts the server on stdio), exactly one. The URL must be `https://` with a host name: no `http://`, since tokens go along, and no user info or IP address, which the domain review cannot express. A mistake fails the evaluation.
- For an HTTP server, `bearer` names a vault path whose value is sent as `Authorization: Bearer`, and `oauth` names an OAuth entry (see below). At most one; neither applies to stdio, which takes its credentials as environment variables through `needs`.
- `needs` is derived from the server: the URL's host, and the `bearer` credential or the `oauth` entry. The skill-wide `needs` do not apply. A `needs` given here overrides the derived one per kind.

`read_skill` shows the agent each server's tools by running `<server> --list-tools` in the sandbox, reviewed like any call of the command; nothing is cached. The commands run the `mcp` bridge from the sandbox image, one connection per call; a server that keeps state between calls does not work. The bridge turns the tool's input schema into flags (see the [contract](sandbox.md#mcp)). `mcp --url …` also works directly in the sandbox, without a skill: the proxy then reviews the domain when the bridge connects.

### OAuth

The vault entry of an OAuth server holds the OAuth state as a compact JSON object:

```json
{"token_url":"https://issuer.example.com/oauth2/token","client_id":"...","client_secret":"...","refresh_token":"...","access_token":"...","expires_at":1750000000,"scope":"..."}
```

`token_url`, `client_id` and `refresh_token` are required; `client_secret` is left out for public clients, and Carapace fills in `access_token` and `expires_at`. Carapace refreshes the token when it is missing or about to expire, writes the result back (a rotated refresh token included), so the vault backend must support writes. The refresh token never enters the sandbox: the bridge asks for an access token with `ccred get --access-token`, and for a fresh one, once per `exec`, after the server answered `401`. Carapace refuses to hand out the entry itself, in any form.

The one-time authorization that produces the first refresh token (typically dynamic client registration, PKCE and a browser login) happens outside Carapace. `scripts/mcp_oauth_blob.py` assembles the object from its result.

## Python with uv

`uvEnv { root = ./.; overrides ? …; python ? pkgs.python3; }` builds a virtualenv from `pyproject.toml` and `uv.lock` with uv2nix, preferring wheels. Commands are the `[project.scripts]` entries in `${env}/bin`.

`uv.lock` does not record the build system of a Git dependency or a package that only ships an sdist. Name it in `overrides`, a pyproject-nix overlay:

```nix
env = skill.uvEnv {
  root = ./.;
  overrides = final: prev: {
    docopt = prev.docopt.overrideAttrs (old: {
      nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem { setuptools = [ ]; };
    });
  };
};
```

A build that fails with `No module named 'setuptools'` (or `hatchling`, `flit_core`, …) for one package needs such an entry.

## Node with npm

`npmApp { root = ./.; }` installs the dependencies from `package.json` and `package-lock.json`. It returns the skill directory with `node_modules` linked in, so a command is `"${pkgs.nodejs}/bin/node ${app}/src/main.mjs"`.

`node_modules` is its own derivation, built from the two lock files only. Editing the skill's code does not install the dependencies again.

## Plain nixpkgs

A command that only glues tools together needs no language package manager. nixpkgs pins every tool, and `exec` can point at any store path: a nixpkgs binary directly, or a script from `pkgs.writeShellApplication`, which puts its `runtimeInputs` on `PATH` and runs ShellCheck at build time.

```nix
pages = pkgs.writeShellApplication {
  name = "pdf-pages";
  runtimeInputs = [ pkgs.qpdf pkgs.jq ];
  text = ''qpdf --warning-exit-0 --json --json-key=pages "$1" | jq '.pages | length' '';
};
```

The commands are then `exec = "${pages}/bin/pdf-pages";` and `exec = "${pkgs.jq}/bin/jq";`. See the [`nix` example](../nix/skills/examples/nix).

## Developing a skill

`nix shell path:./skills/<name> -c <command>` builds a skill from the workspace and runs one of its commands, without pushing it. `path:` matters: inside the knowledge repo a plain `./skills/<name>` is a Git flake that only sees committed files. After changing inputs, `nix flake lock path:./skills/<name>` writes the lock file to commit. The `cgate` request then reports the workspace build's store path. The sentinel sees that path, but whether it matches what the builder built for the committed skill is not checked yet.
