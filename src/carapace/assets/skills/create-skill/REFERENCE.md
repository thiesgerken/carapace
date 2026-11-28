# Create Skill Reference

This file holds the maintainer-facing reference material that should not bloat `SKILL.md`.

Read this file before creating or heavily editing a skill. `SKILL.md` is for the agent that will use the skill later; this file is for the agent that authors the skill.

## Core Rule

Keep the split practical:

- `SKILL.md` explains how to use the skill at runtime
- `REFERENCE.md`, `CONFIG.md`, and `references/*.md` explain how the skill is built, configured, or maintained

If a paragraph helps the future runtime agent act correctly during normal use, it belongs in `SKILL.md`. If it mainly helps a maintainer understand build, packaging, provider setup, or rare troubleshooting details, move it to a sidecar doc.

## Authoring Checklist

Use this checklist when writing or reviewing a skill:

1. Confirm the folder name, the `name` in `mkSkill`, and the attribute in `skills/flake.nix` all match.
2. Make sure the `description` in `mkSkill` contains the strongest trigger phrases a routing agent will search for.
3. Keep `SKILL.md` focused on runtime workflow, guardrails, expected commands, and domain facts needed for safe use.
4. Keep domain facts in `SKILL.md` when the agent needs them to act correctly, even if they are user-specific.
5. Move schemas, dependency setup, auth internals, wrapper internals, and maintainer troubleshooting into sidecar docs.
6. Link any sidecar docs from `SKILL.md` when the runtime agent may need to know they exist.
7. If the skill has commands, add a short `Exposed Commands` list near the top of `SKILL.md` with the real command names from `flake.nix`.
8. Commands, name and description live in `flake.nix`; `SKILL.md` has no frontmatter and its body only lists the commands for the runtime agent.
9. If the skill performs risky actions, add explicit safety rules near the top of `SKILL.md`.
10. If a command needs domains or credentials, declare them in `flake.nix`; one sentence in `SKILL.md` that the command asks for them itself is enough.
11. Build and run every command with `nix shell path:./skills/<name> -c <command>` before pushing (see [Developing before you push](#developing-before-you-push)).

## What Good `SKILL.md` Files Usually Contain

Most good skills in this repo converge on the same shape:

- a precise `description` with task keywords
- one short opening paragraph that sets scope
- a `When To Use` or equivalent section
- an `Exposed Commands` section near the top when the skill has commands
- the normal workflow or command entrypoints
- enough CLI usage detail to run the skill without guessing
- user-specific domain maps that prevent mistakes, such as folder names, project IDs, label names, account conventions, or preferred filters
- important safety or behavior constraints
- a short note when commands ask for domains or credentials themselves

They do not try to be complete technical documentation, but they may be detailed when the detail is needed during ordinary use.

## What To Move Out Of `SKILL.md`

Move content into a sidecar doc when it is mainly about:

- package structure and source layout
- lockfiles and dependency management
- full config schemas or validation edge cases
- secret sourcing, vault paths, or authentication mechanics beyond a one-line note
- exhaustive command catalogs where the common commands are already represented in `SKILL.md`
- troubleshooting intended for maintainers rather than runtime usage

Keep content in `SKILL.md` when it is mainly about:

- how to invoke the skill's CLI correctly
- which commands the agent should prefer during normal use
- common commands the agent should use often
- user-specific categories, folders, projects, labels, accounts, or IDs needed for correct action
- safety rules and syntax traps that prevent accidental side effects

Use `CONFIG.md` when the document is mostly runtime configuration detail. Use `REFERENCE.md` when it is general maintainer guidance. Use `references/*.md` when the detail is large enough to merit topic-specific documents.

Do not use file length as the deciding factor. Use load timing: if the agent should know it as soon as it reads the skill, it belongs in `SKILL.md`; if the agent can intentionally open it only for uncommon setup, development, or deep reference work, it can live in a sidecar file.

## Common Failure Modes

These mistakes make skills harder to discover or use:

- vague descriptions such as `Helps with email`
- putting provider setup docs before the actual workflow
- embedding credential-handling procedures in `SKILL.md`
- moving operational facts out of `SKILL.md` just because they look like data tables
- documenting every implementation detail instead of the actions and domain facts the agent needs
- forgetting to link the sidecar doc after moving detail out of `SKILL.md`
- showing example commands that do not match the actual entrypoints shipped by the skill

## Standard Skill Layout

Skills live under `skills/` in the knowledge repo. Every skill is a Nix flake: `flake.nix` and `flake.lock` next to `SKILL.md`, plus the code and its lock files if it has commands. A skill with only instructions needs just the flake of a few lines from docs/skill-flakes.md ("Skills with only instructions"): `mkSkill { name = "my-skill"; description = "…"; src = ./.; }`.

Every skill is listed in `skills/flake.nix`, one input per skill, and its attribute name there is the skill's name:

```nix
inputs.my-skill = {
  url = "path:./my-skill";
  inputs.nixpkgs.follows = "nixpkgs";
  inputs.carapace.follows = "carapace";
};
```

Always write both `follows`: every skill then shares the one `nixpkgs` and the one Carapace helper version that `skills/flake.nix` pins, and `nix flake update carapace --flake ./skills` updates the helpers of all skills at once. A skill's own `flake.lock` only matters when it is built on its own.

The bundled skills are not in `skills/` but inputs on Carapace's `main` branch (`github:thiesgerken/carapace?dir=src/carapace/assets/skills/<dir>`), configured in `skills/config.json`. To adjust one beyond its settings (its description, extra instructions, an added file), override it in `skills/flake.nix` (docs/sharing-skills.md, "Overriding a shared skill"); only for deeper changes copy its directory into `skills/`, point its input at `path:./<dir>` and lock again, which makes it a local skill.

```text
skills/
  flake.nix          # lists every skill
  flake.lock         # committed; update it with the skill
  my-skill/
    SKILL.md
    flake.nix        # commands, what they need, how they are built
    flake.lock       # committed, complete; the builder never writes it
    pyproject.toml   # Python: with uv.lock
    uv.lock
    src/my_skill/
      __init__.py
      cli.py
    references/
```

Use `REFERENCE.md`, `CONFIG.md`, or `references/*.md` for maintainer docs, large examples, or implementation notes.

## Name and Description

Both are `mkSkill` arguments in the skill's `flake.nix`, next to its commands. `SKILL.md` holds only the instructions; a SKILL.md that starts with YAML frontmatter fails the build.

```nix
default = skill.mkSkill {
  name = "my-skill";
  description = "What this skill does and when to use it. Be specific.";
  src = ./.;
};
```

`name` rules:

- must match the parent directory name and the attribute name in `skills/flake.nix`
- lowercase letters, numbers, and hyphens only
- no consecutive hyphens, no leading or trailing hyphen
- max 64 characters

`description` rules:

- include keywords that help the agent decide when to load the skill
- describe both what the skill does and when to use it
- max 1024 characters

Good description example:

```nix
description = "Summarise email threads and draft replies. Use when the user mentions email, inbox, or wants to compose a message.";
```

Bad description example:

```nix
description = "Helps with email.";
```

When in doubt, bias toward concrete routing language:

- name the user intent
- name the relevant domain objects
- name the likely verbs the user will use

For example, `Read, search, summarize, and move private Zoho mailbox messages` routes better than `Email helper`.

## Progressive Disclosure

carapace loads skills in three tiers:

1. Discovery: `name` and `description`
2. Activation: full `SKILL.md`
3. On-demand resources: files under `src/`, `references/`, `assets/`, and sidecar docs

That is why `SKILL.md` should stay short and user-facing. Put the rest here or into dedicated reference files.

As a rule of thumb, if a runtime agent can succeed without reading a section every time the skill is activated, that section belongs here instead of in `SKILL.md`.

## Commands: the skill flake

The Carapace builder builds the flake whenever the skill changes on the server, and every session gets its commands on `PATH`. The flake's package holds one wrapper per command and nothing else; interpreters and dependencies stay behind the wrappers. The full reference is the Carapace repo's `docs/skill-flakes.md`; the shape is:

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
          skill = carapace.lib.skill nixpkgs.legacyPackages.${system};
          env = skill.uvEnv { root = ./.; };
        in
        {
          default = skill.mkSkill {
            name = "my-skill";
            description = "Search the Example service. Use when the user asks about Example records.";
            src = ./.;
            # Bound to a password-manager entry in skills/config.json, never written here.
            credentials.EXAMPLE_TOKEN = {
              type = "secret";
              description = "A token for the Example service";
            };
            needs.domains = [ "api.example.com" ];
            commands = {
              my-search = {
                exec = "${env}/bin/my-search";
                description = "Search the Example service";
              };
              my-format = {
                exec = "${env}/bin/my-format";
                description = "Reformat a local file, offline";
                needs = {
                  domains = [ ];
                  credentials = [ ];
                };
              };
            };
          };
        }
      );
    };
}
```

- `name` matches the skill directory. Command names are what the agent types; keep them unique across skills.
- `exec` is what the wrapper runs, with the agent's arguments appended. It is shell words: a store path may carry fixed arguments.
- `needs` declares what a command will ask for from outside the sandbox: `domains`, `credentials` (names of the skill's credential slots, by default all of them), `oauth` (names of the skill's OAuth slots, `type = "oauth"`, whose access token the command fetches with `ccred get --access-token "$SLOT"`). It is the skill-wide default; a command's own `needs` overrides it per kind. The wrapper asks for everything declared at once before the command starts, and exports the credentials. Undeclared requests still work and are reviewed when they happen.
- `credentials` declares the secrets the skill needs, never where they are: `credentials.WEATHER_TOKEN = { type = "secret"; description = "…"; };`. `skills/config.json` binds the slot to a vault path (`{"<skill>": {"credentials": {"WEATHER_TOKEN": "<backend>/<id>"}}}`), and the commands get it as `$WEATHER_TOKEN`. A vault path in the flake fails the evaluation. Until the user binds a slot, the commands that need it are refused with a hint; ask the user which entry to bind, and use `ccred list` to find candidates.
- `needs` may also be a function of the skill's settings: `needs = settings: { domains = [ "${settings.CITY}.weather.example" ]; };`.
- `settings` declares what an instance configures: `settings.CITY = { type = "str"; description = "…"; default = "Berlin"; };`, with type `str`, `int` or `bool`, required without a default. The values live in `skills/config.json` (`{"<skill>": {"settings": {"CITY": "Hamburg"}}}`), and every command gets each setting as an environment variable of the same name. Use a setting for a server URL, a city or a default, never for a secret: those are credential slots. Never write an instance's values into the flake, so the skill stays usable anywhere.
- `description` is one short line the agent sees.
- The wrapper keeps the caller's working directory. Commands take paths as arguments rather than assuming a directory.

## Building commands

- **Python with uv:** `skill.uvEnv { root = ./.; }` builds a virtualenv from `pyproject.toml` and `uv.lock`; commands are the `[project.scripts]` entries under `${env}/bin`. A dependency that ships only an sdist, or a Git dependency, needs its build system named in `overrides` (see `docs/skill-flakes.md`): the error says `No module named 'setuptools'` or similar.
- **Node with npm:** `skill.npmApp { root = ./.; }` from `package.json` and `package-lock.json`; a command is `"${pkgs.nodejs}/bin/node ${app}/src/main.mjs"`.
- **Plain nixpkgs:** a command that only glues tools together needs no package manager. `exec` can be a nixpkgs binary (`"${pkgs.jq}/bin/jq"`) or a `pkgs.writeShellApplication { name; runtimeInputs = [ … ]; text; }` script.
- Nothing is installed at run time: no `uv run`, `npm install`, `nix run` or `nix profile install` in a command. A tool the skill needs every time goes into its flake, so everything a command needs is in its closure.

Minimal `pyproject.toml` for a uv skill:

```toml
[project]
name = "my-skill"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["httpx>=0.28,<1"]

[project.scripts]
my-search = "my_skill.cli:search"
my-format = "my_skill.cli:format"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/my_skill"]
```

Prefer `httpx`, modern typing and JSON output for CLIs, with `main()`-style entry points.

## Developing before you push

The builder builds what is committed and pushed. Before that, build and run from the workspace:

```bash
uv lock --directory skills/my-skill                       # after changing Python dependencies
nix flake lock path:./skills/my-skill                     # after changing flake inputs; commit flake.lock
nix flake update my-skill --flake ./skills                # then pick that up in skills/flake.lock; commit it too
nix shell path:./skills/my-skill -c my-search "query"     # build the commands and run one
```

- `path:` matters: a plain `./skills/my-skill` inside the Git repo only sees committed files, so new or changed files would be missing.
- The first build downloads nixpkgs and dependencies and takes a minute or more; later builds are fast.
- A workspace build has a different store path than the builder's build of the committed skill, and the sentinel sees that when the command asks for domains or credentials.
- After the push, the Knowledge view of the skill shows whether the builder built it, and for a failure the end of the build log.

## Creating A New Skill

Recommended sequence:

1. Choose the folder name first.
2. Draft the `description` next, because discovery quality matters more than polish in the long body.
3. Write a `SKILL.md` that a runtime agent can follow without guessing or immediately loading sidecar files.
4. Add sidecar docs only where complexity is real.
5. Write `flake.nix` and lock it: the mini-flake for instructions only, or for commands the code with its lock files, and run every command with `nix shell path:./skills/<name> -c <command>`.
6. List it in `skills/flake.nix` (above), `git add skills/<name>`, and run `nix flake lock ./skills`.
7. Re-read the skill from the perspective of a fresh agent with no maintainer context.

## Editing An Existing Skill

When reshaping an existing skill:

1. Preserve the established command names unless there is a strong reason to change them.
2. Separate maintainer-heavy prose from runtime-critical instructions before adding new sections.
3. Prefer moving text into `REFERENCE.md` over deleting useful operational knowledge.
4. Keep links between `SKILL.md` and sidecar docs accurate.
5. Check neighboring skills for naming and section conventions before introducing a new structure.

## Mini Pattern Example

Good split:

- `SKILL.md`: `Use when the user wants to search the mailbox, read a message, or move mail after explicit instruction.`
- `CONFIG.md`: IMAP host, local config files, credential filenames, and provider-specific troubleshooting

Bad split:

- `SKILL.md`: full account config, vault path details, package layout, and setup internals before any actual workflow guidance

## Authoring Pattern

Use this split when creating skills:

- `SKILL.md`: concise instructions for the activated agent
- `REFERENCE.md` or `CONFIG.md`: maintainer and implementation detail
- `references/*.md`: larger API or domain docs
- `assets/`: templates, sample payloads, static helper data

If an existing skill has grown unwieldy, cut it back to runtime behavior and move the rest into sidecar docs.
