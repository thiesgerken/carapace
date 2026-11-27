# Skill flakes

Every skill is a Nix flake: `flake.nix` and `flake.lock` live in the skill directory next to its `SKILL.md`. The flake's package holds one wrapper per command and a reference to the skill directory. The Carapace builder builds it whenever the skill changes; the server reads `SKILL.md` from the build, and every session gets the commands on its `PATH` and the skill directory in its store. The knowledge repo lists its skills in [`skills/flake.nix`](#the-skills-flake); a skill directory that is not listed there is not a skill. A skill that only carries instructions is a [flake of a few lines](#skills-with-only-instructions).

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

- Built standalone (`nix build path:<dir>`), a skill uses its own `flake.lock`. Built through [`skills/flake.nix`](#the-skills-flake), as the builder does, its `nixpkgs` and `carapace` follow the ones that file pins, so every skill of a repo shares them. `inputs.nixpkgs.follows` makes the Carapace helpers use the same `nixpkgs`.
- `carapace` pins a Carapace commit. The wrappers keep working when Carapace moves on. Helpers whose `mkSkill` takes no `src` build packages without `skillDir`, which the server cannot read: such a skill shows as failed until the pin moves.
- `flake.lock` must be committed and complete: the builder never writes locks. Run `nix flake lock` after changing inputs.
- Evaluation runs with import-from-derivation off, which all helpers support.
- `forSkillSystems` covers `x86_64-linux` and `aarch64-linux`, the architectures sandboxes run on.

## The skills flake

`skills/flake.nix` at the top of the knowledge repo is the only list of skills. Every input except `nixpkgs` and `carapace` is a skill, named by its attribute; a skill's `name` in `mkSkill` or in its frontmatter does not matter. A new knowledge repo gets this one, listing the bundled skills that need no setup (shortened):

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    carapace = {
      url = "github:thiesgerken/carapace?dir=nix/skills";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # A skill from elsewhere: bundled with Carapace, taken from its main branch.
    wikipedia = {
      url = "github:thiesgerken/carapace?dir=src/carapace/assets/skills/wikipedia";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };

    # A local skill: the directory skills/carapace, under the name carapace-cli.
    carapace-cli = {
      url = "path:./carapace";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.carapace.follows = "carapace";
    };
  };

  # Every input but nixpkgs and carapace is a skill; config.json holds the values of their settings.
  outputs =
    { carapace, ... }@inputs:
    carapace.lib.skillsFlake {
      inherit inputs;
      config = ./config.json;
    };
}
```

- A local skill is a `path:./<dir>` input, a skill from elsewhere any flake reference (e.g. `github:someone/skill-weather`). Every skill follows `nixpkgs` and `carapace`, so the lock holds one of each, and `nix flake update carapace --flake ./skills` moves the helpers of every skill at once.
- The bundled skills that need no setup (`artifacts`, `create-skill`, `credentials`, `mermaid`, `wikipedia`) come from Carapace's `main` branch, without a tag: every push to `main` is a release. The lock pins the commit they were last updated to; `nix flake update <name> --flake ./skills` brings one to the latest.
- `skillsFlake` exposes each skill's package as `packages.<system>.<name>` and its [manifest](#the-manifest) as `manifests.<system>.<name>`. The builder evaluates and builds every attribute on its own, from `skills/flake.nix`, its lock, `config.json` and the skill's own directory at `HEAD`, so one broken skill leaves the others built and usable.
- The server reads the list from `skills/flake.lock` (the root's inputs), never by evaluating Nix. Without `skills/flake.nix` or its lock the repo has no skills, and the Knowledge view says so.
- `carapace` is the helpers' attribute, so the bundled skill in `skills/carapace` is listed as `carapace-cli`.

To add a skill, add its input and lock: `nix flake lock ./skills`. A new skill directory must be tracked by Git first (`git add`), because `./skills` is a Git flake. After changing a local skill's inputs or its own `flake.lock`, run `nix flake update <name> --flake ./skills`: the top-level lock copies a local skill's inputs once and does not notice later changes. Editing a local skill's code or `SKILL.md` needs no new lock. Commit `skills/flake.lock` together with the change.

To turn a skill off, set `"enable": false` for it in `skills/config.json`, or remove its input and lock again. When you remove an input, remove the skill's entry from `config.json` too: an entry for a skill the flake does not list fails every skill.

### `skills/config.json`

The values of the skills' [settings](#settings), per skill attribute, as JSON with sorted keys. A new knowledge repo gets `{}`; without the file every skill takes its defaults.

```json
{
  "weather": { "settings": { "CITY": "Berlin" } },
  "web": { "enable": false }
}
```

`skillsFlake` reads it into the Nix module system: each skill has the options `enable` (default `true`) and `settings.<NAME>` with the declared type. A setting the skill does not declare or a skill the flake does not list fails the evaluation of every skill, with the module system's message naming the option. A value of the wrong type fails only that skill's manifest, and so does a required setting without a value: `skill weather: no value for its setting CITY; set it in skills/config.json`. A skill that is off needs no values.

A change to `config.json` re-evaluates every skill's manifest but builds nothing: the packages do not depend on it, so every instance of a skill runs the same build.

The Knowledge view of `skills/` edits it too: each skill's "Settings" opens a form with its declared settings (the default as the placeholder), its current values and an on/off switch, and marks a skill that lacks a required value with "Needs configuration". Saving commits that skill's entry as the logged-in user, sorted and indented so the diff shows only what changed, and pushes it; the commit skips the sentinel, since the human acts. A save made from a form older than the current `config.json` is refused, not merged. The server checks a value against the declared type (`str`, `int`, `bool`, exactly as the Nix options take them) before committing; anything else Nix rejects shows as the skill's evaluation error in the same form.

## Commands and what they need

`mkSkill { name, src, commands ? { }, needs ? { }, settings ? { } }` builds the package. `src` is the skill directory, normally `./.`: it becomes a store path of its own, referenced by the package, so the sandbox gets `SKILL.md`, scripts and references together with the commands. Each command has:

- `exec`: what the wrapper runs, with the wrapper's arguments appended. It is shell words, not quoted for you: it gets word-split and expanded, which is what lets a store path carry fixed arguments (`"${pkgs.nodejs}/bin/node ${app}/src/main.mjs"`). A path with spaces needs its own quoting.
- `description`: one short line, shown to the agent.
- `needs` (optional): overrides the skill-wide `needs`, per kind. A command that sets `domains = [ ]` asks for no domains, whatever the default says.

`needs` declares what a command will want from outside the sandbox, skill-wide or per command, as an attribute set or as a function of the [settings](#settings) (`settings: { domains = [ "${settings.CITY}.weather.example" ]; }`). Any other key, an invalid variable name or a malformed tunnel fails the evaluation of the manifest:

- `domains`: host names, or `*.` plus a name of at least two labels.
- `credentials`: environment variable to vault path. The wrapper exports each one before the command starts. Variable names must be shell identifiers.
- `oauth`: vault paths of OAuth entries whose access token the command fetches itself with `ccred get --access-token`, as the MCP bridge does. Declared up front, exported nothing.
- `tunnels`: `"host:port"` with an exact host name (not an IP address) and a port from 1 to 65535, for clients that do not speak HTTP. Requested with `cgate request --tunnel` and open when the command starts; see [sandbox.md](sandbox.md#tunnels).

A command with needs or a skill with settings gets a wrapper that first asks Carapace for itself by name, then runs the command:

```sh
gate="$(cgate request --store-path "/nix/store/…-skill-weather" --command weather)"
eval "$gate"
exec /nix/store/…-skill-env/bin/weather "$@"
```

The wrapper names no domain or credential: Carapace looks the command up in the [manifest](#the-manifest) of the installed build whose package is that store path, or else of the installed build that has a command of that name (so a package built in the workspace with `nix shell path:./skills/<name>` runs with the settings and needs of the committed version), has its needs reviewed and answers with the settings and credentials, which `cgate` prints as `export` lines (fetching the credentials with `ccred get`). So the package is the same for every instance, and only the manifest carries this instance's values. The sentinel decides once, with the whole `exec` in view. A denial, a failing `ccred` or a command that no built skill of this knowledge repo has (a new skill before its first push) stops the wrapper before the command runs, with the reason on stderr. Declarations are a batching hint and carry no trust; what a command was not declared to need still works and is reviewed when it is requested (see [Declaring needs up front](sandbox.md#declaring-needs-up-front-cgate)). A command without needs in a skill without settings gets a plain `exec` wrapper.

`cgate` and `ccred` come from the sandbox image, not from the skill. Their contract is documented in [sandbox.md](sandbox.md#cli-contract), and it is what keeps wrappers built against an older Carapace working.

### Settings

A skill declares the settings an instance gives it, each with a type (`str`, `int` or `bool`), a description and optionally a default:

```nix
mkSkill {
  name = "weather";
  src = ./.;
  settings = {
    CITY = { type = "str"; description = "The city to report on"; };
    UNITS = { type = "str"; description = "metric or imperial"; default = "metric"; };
  };
  needs = settings: { domains = [ "${settings.CITY}.weather.example" ]; };
  commands.weather = { exec = "${env}/bin/weather --units $UNITS"; description = "Current weather"; };
}
```

The values come from [`skills/config.json`](#skillsconfigjson). A setting without a default is required. Every command of the skill gets each setting as an environment variable of the same name, so names must be shell identifiers; numbers and booleans arrive in their JSON spelling (`443`, `true`). Settings are no secrets: a password or token belongs in `needs.credentials`.

## The manifest

The builder evaluates each skill's manifest before it builds anything, and the server reads only that, never Nix:

```sh
nix eval --json 'path:skills#manifests.x86_64-linux.weather'
```

```json
{
  "enable": true,
  "name": "weather",
  "skillDir": "/nix/store/…-skill-weather-src",
  "settings": { "CITY": "Berlin", "UNITS": "metric" },
  "commands": {
    "weather": {
      "description": "Current weather for a city",
      "needs": {
        "domains": ["berlin.weather.example"],
        "credentials": { "WEATHER_TOKEN": "personal/weather-token" },
        "oauth": [],
        "tunnels": []
      },
      "mcp": false
    }
  }
}
```

- `settings` are this instance's values, from `skills/config.json` or the declared defaults.
- `needs` is resolved for those values: the skill-wide default with the command's override applied, every kind present.
- `skillDir` is the store path of `src`. The evaluation already copies it into the store, so the builder reads `SKILL.md` from it before the commands are built.
- `commands` has one entry per wrapper in `bin/`, under the same name. `mcp` is `true` for a command made by `mcpCommands`; `read_skill` lists its tools.
- A skill that `config.json` turns off has the manifest `{ "enable": false }`. It is not built, and Carapace treats it like a skill that is not listed.
- `skillsFlake` writes the manifest from what `mkSkill` declares in `passthru.carapace` (the settings, the commands) and `passthru.carapaceNeeds` (the needs for given setting values). Fields are only ever added.

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

Its package has an empty `bin/` and the reference to the skill directory. The bundled `artifacts`, `mermaid`, `create-skill` and `credentials` skills are built this way.

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
