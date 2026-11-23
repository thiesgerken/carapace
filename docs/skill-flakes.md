# Skill flakes

A skill that has commands is a Nix flake: `flake.nix` and `flake.lock` live in the skill directory next to its `SKILL.md`. The flake's package holds one wrapper per command, nothing else. The Carapace builder builds it whenever the skill changes, and every session gets the commands on its `PATH`. A skill without commands needs no flake.

The functions below come from the skills subflake of the Carapace repo, `github:thiesgerken/carapace?dir=nix/skills` ([`nix/skills/flake.nix`](../nix/skills/flake.nix)). It has only `nixpkgs` and the uv2nix stack as inputs, so a skill's `flake.lock` stays small. Three working examples live in [`nix/skills/examples`](../nix/skills/examples): uv, npm and pnpm. CI builds them against the helpers of the current checkout.

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
- `carapace` pins a released Carapace commit in `flake.lock`. The helpers keep working when Carapace moves on, because their arguments only grow; a skill updates its pin when it wants something new.
- `flake.lock` must be committed and complete: the builder never writes locks. Run `nix flake lock` after changing inputs.
- The build sees nothing but the skill directory (`nix build path:<dir>`). Evaluation runs with import-from-derivation off, which all helpers support.
- `forSkillSystems` covers `x86_64-linux` and `aarch64-linux`, the architectures sandboxes run on.

## Commands and what they need

`mkSkill { name, commands, needs ? { } }` builds the package. Each command has:

- `exec`: what the wrapper runs, with the wrapper's arguments appended. A store path, possibly with fixed arguments in front (`"${pkgs.nodejs}/bin/node ${app}/src/main.mjs"`).
- `description`: one short line, shown to the agent.
- `needs` (optional): overrides the skill-wide `needs`, per kind. A command that sets `domains = [ ]` asks for no domains, whatever the default says.

`needs` declares what a command will want from outside the sandbox:

- `domains`: host names, or `*.` plus a name of at least two labels.
- `credentials`: environment variable to vault path. The wrapper exports each one before the command starts.
- `tunnels`: `"host:port"`. Not supported yet: a non-empty list fails the evaluation.

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
  "commands": {
    "weather": {
      "description": "Current weather for a city",
      "needs": {
        "domains": ["api.example.com"],
        "credentials": { "WEATHER_TOKEN": "personal/weather-token" },
        "tunnels": []
      }
    },
    "weather-units": {
      "description": "List the supported units, offline",
      "needs": { "domains": [], "credentials": {}, "tunnels": [] }
    }
  }
}
```

- `commands` has one entry per wrapper in `bin/`, under the same name.
- `needs` is already resolved: the skill-wide default with the command's override applied, every kind present.
- The builder passes this on as opaque JSON; the server reads it. Fields are only ever added.

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

## Node with npm or pnpm

`npmApp { root = ./.; }` installs the dependencies from `package.json` and `package-lock.json`. `pnpmApp { root = ./.; hash = "sha256-…"; }` does the same from `pnpm-lock.yaml`. Both return the skill directory with `node_modules` linked in, so a command is `"${pkgs.nodejs}/bin/node ${app}/src/main.mjs"`.

`node_modules` is its own derivation, built from the lock files only. Editing the skill's code does not install the dependencies again.

pnpm needs one thing npm does not: `pnpm-lock.yaml` lacks the hashes Nix needs, so the dependencies are fetched as a fixed-output derivation whose `hash` sits in `flake.nix`. It changes whenever the lock file does. Set it to `pkgs.lib.fakeHash`, build once, and copy the hash from the error:

```text
error: hash mismatch in fixed-output derivation '…-skill-node-modules-pnpm-deps.drv':
         specified: sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
            got:    sha256-nWi4zyIaLKHD6wrM+k7SiWreZEkS8TGfToIvH8HJ628=
```

npm needs no such hash: `package-lock.json` carries the integrity of every package.

## Developing a skill

`nix shell ./skills/<name> -c <command>` builds a skill from the workspace and runs one of its commands, without pushing it. The `cgate` request then reports the workspace build's store path, which does not match what the builder built for the committed skill, and the sentinel sees that.
