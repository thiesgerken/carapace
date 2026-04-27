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

1. Confirm the folder name, frontmatter `name`, and skill identity all match.
2. Make sure the `description` contains the strongest trigger phrases a routing agent will search for.
3. Keep `SKILL.md` focused on runtime workflow, guardrails, expected commands, and domain facts needed for safe use.
4. Keep domain facts in `SKILL.md` when the agent needs them to act correctly, even if they are user-specific.
5. Move schemas, dependency setup, auth internals, wrapper internals, and maintainer troubleshooting into sidecar docs.
6. Link any sidecar docs from `SKILL.md` when the runtime agent may need to know they exist.
7. If the skill exposes commands, add a short `Exposed Commands` list near the top of `SKILL.md` and show the real aliases there.
8. Do not put exposed commands into frontmatter; keep them in the body where the runtime agent will read them naturally.
9. If the skill performs risky actions, add explicit safety rules near the top of `SKILL.md`.
10. If activation handles credentials or setup automatically, say that briefly in `SKILL.md` and stop there.
11. If `carapace.yaml` injects a credential into a local file, add that generated file path to the skill-local `.gitignore`.

## What Good `SKILL.md` Files Usually Contain

Most good skills in this repo converge on the same shape:

- a precise `description` with task keywords
- one short opening paragraph that sets scope
- a `When To Use` or equivalent section
- an `Exposed Commands` section near the top when the skill ships command aliases
- the normal workflow or command entrypoints
- enough CLI usage detail to run the skill without guessing
- user-specific domain maps that prevent mistakes, such as folder names, project IDs, label names, account conventions, or preferred filters
- important safety or behavior constraints
- a short setup note when automatic activation behavior matters

They do not try to be complete technical documentation, but they may be detailed when the detail is needed during ordinary use.

## What To Move Out Of `SKILL.md`

Move content into a sidecar doc when it is mainly about:

- package structure and source layout
- lockfiles and dependency management
- full config schemas or validation edge cases
- secret sourcing, vault paths, or authentication mechanics beyond the activation behavior
- exhaustive command catalogs where the common commands are already represented in `SKILL.md`
- troubleshooting intended for maintainers rather than runtime usage

Keep content in `SKILL.md` when it is mainly about:

- how to invoke the skill's CLI correctly
- which exposed command aliases the agent should prefer during normal use
- common commands the agent should use often
- user-specific categories, folders, projects, labels, accounts, or IDs needed for correct action
- safety rules and syntax traps that prevent accidental side effects

Use `CONFIG.md` when the document is mostly runtime configuration detail. Use `REFERENCE.md` when it is general maintainer guidance. Use `references/*.md` when the detail is large enough to merit topic-specific documents.

Do not use file length as the deciding factor. Use load timing: if the agent should know it immediately after skill activation, it belongs in `SKILL.md`; if the agent can intentionally open it only for uncommon setup, development, or deep reference work, it can live in a sidecar file.

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

Skills live under `skills/` in the data directory. Each skill directory contains at minimum a `SKILL.md` file:

```text
skills/
  my-skill/
    SKILL.md
    carapace.yaml
    pyproject.toml
    uv.lock
    package.json
    package-lock.json
    pnpm-lock.yaml
    setup.sh
    src/my_skill/
      __init__.py
      cli.py
    references/
    assets/
```

Use `REFERENCE.md`, `CONFIG.md`, or `references/*.md` for maintainer docs, large examples, or implementation notes.

## Frontmatter Rules

Required frontmatter:

```yaml
---
name: my-skill
description: What this skill does and when to use it. Be specific.
---
```

`name` rules:

- must match the parent directory name exactly
- lowercase letters, numbers, and hyphens only
- no consecutive hyphens, no leading or trailing hyphen
- max 64 characters

`description` rules:

- include keywords that help the agent decide when to load the skill
- describe both what the skill does and when to use it
- max 1024 characters

Optional frontmatter fields:

| Field           | Purpose                                                       |
| --------------- | ------------------------------------------------------------- |
| `license`       | License name or reference to a bundled `LICENSE` file         |
| `compatibility` | Environment requirements such as tools, network, or OS limits |
| `metadata`      | Arbitrary key-value pairs                                     |

Good description example:

```yaml
description: Summarise email threads and draft replies. Use when the user mentions email, inbox, or wants to compose a message.
```

Bad description example:

```yaml
description: Helps with email.
```

When in doubt, bias toward concrete routing language:

- name the user intent
- name the relevant domain objects
- name the likely verbs the user will use

For example, `Read, search, summarize, and move private Zoho mailbox messages` routes better than `Email helper`.

## Progressive Disclosure

Carapace loads skills in three tiers:

1. Discovery: `name` and `description`
2. Activation: full `SKILL.md`
3. On-demand resources: files under `src/`, `references/`, `assets/`, and sidecar docs

That is why `SKILL.md` should stay short and user-facing. Put the rest here or into dedicated reference files.

As a rule of thumb, if a runtime agent can succeed without reading a section every time the skill is activated, that section belongs here instead of in `SKILL.md`.

## `carapace.yaml`

`carapace.yaml` is optional. Use it when the skill needs outbound domains, tunnels, hints, auto-injected credentials, or command aliases.

Top-level keys:

| Key               | Type            | Purpose                                                 |
| ----------------- | --------------- | ------------------------------------------------------- |
| `network`         | object          | Network configuration for allowed domains or tunnels    |
| `network.domains` | list of strings | Hostnames added to the session allowlist                |
| `credentials`     | list of objects | Vault-backed credentials to inject as env vars or files |
| `commands`        | list of objects | Command aliases registered on skill activation          |
| `hints`           | map             | Extra metadata for tooling                              |

Valid example:

```yaml
network:
  domains:
    - api.example.com
    - "*.cdn.example.com"

credentials:
  - vault_path: my-backend/some-secret-id
    description: API key for Example service
    env_var: EXAMPLE_API_KEY
  - vault_path: my-backend/deploy-key
    description: SSH private key for deploys
    file: ~/.ssh/id_example_deploy

commands:
  - name: example-search
    command: uv run --directory /workspace/skills/example scripts/search.py
```

Common mistake:

```yaml
network:
  - api.example.com
```

`network` must be an object with a `domains` key. If the shape is wrong, validation fails and the file may be ignored.

When credentials are declared here, activation handles approval and injection automatically. Keep those details out of `SKILL.md` unless the runtime behavior itself depends on them.

When command aliases are declared here, activation generates executable wrappers in `/root/.carapace/bin/` and exposes that directory on `PATH`. Runtime agents should call the plain alias token, not the absolute shim path. Authors should think of `command` as the base command line for that wrapper, not as a multi-line shell script.

Each command entry has:

- `name`: the alias token the agent will invoke
- `command`: a single non-empty line that becomes `exec <command> "$@"` inside the generated `#!/bin/sh` wrapper

Guidelines for command aliases:

- Preserve the caller's current working directory. Do not depend on an implicit `cd` into the skill directory.
- Use absolute paths if the command needs files under `/workspace/skills/<name>/`.
- Assume extra arguments are forwarded with `"$@"`.
- Keep aliases unique. If another active skill already owns the same alias, activation fails.
- Do not use multi-line commands; validation rejects them.

The usual sentence in `SKILL.md` is enough: setup or credential injection happens automatically on activation.

If the skill exposes commands, it is customary to list them near the top of `SKILL.md` in a short section such as:

```markdown
## Exposed Commands

- `example-search`: Search the Example service.
- `example-sync`: Run the Example sync flow.
```

Keep this in the body, not in frontmatter.

If a credential is materialized into a local file, treat that path as generated secret state and ignore it in the skill-local `.gitignore`.

Pattern:

```yaml
credentials:
  - vault_path: vault/<uuid>
    description: Password for Example service
    file: config/example-password.txt
```

```gitignore
config/example-password.txt
```

## Python Provider Files

Python-backed skills should use a proper package under `src/<package_name>/` with CLI entrypoints declared in `pyproject.toml`.

Suggested layout:

```text
skills/my-skill/
  SKILL.md
  REFERENCE.md
  carapace.yaml
  pyproject.toml
  uv.lock
  src/my_skill/
    __init__.py
    cli.py
    another.py
```

Minimal `pyproject.toml`:

```toml
[project]
name = "my-skill"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.28,<1",
]

[project.scripts]
my-cli = "my_skill.cli:main"
my-other = "my_skill.another:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/my_skill"]
```

Rules:

- always commit `uv.lock` alongside `pyproject.toml`
- run commands through `uv run --directory /workspace/skills/my-skill <command>`
- do not run Python source files directly
- prefer `httpx`, modern typing, and structured JSON output for CLIs
- expose stable CLI entrypoints with `main()` functions instead of expecting ad hoc module execution

To create or update the lockfile:

```bash
uv lock --directory /workspace/skills/my-skill
uv add --directory /workspace/skills/my-skill beautifulsoup4
uv remove --directory /workspace/skills/my-skill httpx
```

## Node Provider Files

Node-backed skills are supported through either npm or pnpm.

- `package.json` + `package-lock.json` uses `npm ci`
- `package.json` + `pnpm-lock.yaml` uses `pnpm install --frozen-lockfile`

Commit the lockfile. Activation uses the pushed upstream provider files.

If both npm and pnpm files are present, be explicit about which workflow is intended and remove stale lockfiles when possible.

## `setup.sh`

If present, `setup.sh` runs after dependency installation. Use it for deterministic local post-processing such as writing derived config files or materializing approved credentials into tool-specific locations.

Rules:

- keep it idempotent
- do not print secrets
- assume only the pushed upstream copy runs automatically

`setup.sh` is not a place for user guidance. If the runtime agent needs to know that setup materializes local config, mention that in one short line in `SKILL.md` and keep the details here.

## Creating A New Skill

Recommended sequence:

1. Choose the folder name first.
2. Draft the `description` next, because discovery quality matters more than polish in the long body.
3. Write a `SKILL.md` that a runtime agent can follow without guessing or immediately loading sidecar files.
4. Add sidecar docs only where complexity is real.
5. Add provider files and command entrypoints.
6. Re-read the skill from the perspective of a fresh agent with no maintainer context.

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
