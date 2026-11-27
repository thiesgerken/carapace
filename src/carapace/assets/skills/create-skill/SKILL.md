---
name: create-skill
description: Create and refine carapace AgentSkills. Use when the user wants to add a new skill, reshape an existing one, or asks how a skill should be structured.
---

# Create Skill

Create or update skills under `skills/<name>/` for carapace.

## Goal

Produce a skill that is easy for another agent to activate and follow.

- `SKILL.md` is the agent-facing workflow document
- Keep it complete enough for normal use without extra lookup
- Move only details that are genuinely on-demand, such as provider internals, build setup, exhaustive references, or maintainer notes, into a sidecar doc such as `REFERENCE.md`, `CONFIG.md`, or files under `references/`

## What Belongs In `SKILL.md`

Keep the information an activated agent should know before acting:

- what the skill does and when to use it
- a short list of exposed commands near the top of the body when the skill has commands
- hard constraints and safety rules
- the normal workflow or command entrypoints
- how the skill CLI is supposed to be invoked
- domain facts the agent needs to act correctly, such as project names, folder names, common labels, IDs, account context, or user-specific conventions
- common command examples and syntax traps that prevent mistakes
- a short note that commands ask for their domains and credentials themselves, if applicable
- links to sidecar docs when deeper implementation detail exists

The guiding question is: would the agent make worse decisions, run the wrong command, or need to pause and load another file during normal use without this? If yes, keep it in `SKILL.md`.

Do not turn `SKILL.md` into developer documentation for the skill itself, but do keep the operational knowledge that a runtime agent needs in the moment.

## What Belongs Elsewhere

Prefer a sidecar markdown file only for content that can safely be loaded on demand:

- provider file layouts and lockfile rules
- how `flake.nix` builds the commands and what they declare
- authentication wiring and credential internals, beyond a one-line note
- packaging details for Python or Node
- exhaustive API references and maintainer troubleshooting notes

Do not move runtime-critical facts out of `SKILL.md` just because they are long, tabular, or user-specific.

Good filenames are `REFERENCE.md`, `CONFIG.md`, or `references/*.md`.

## Workflow

1. Read `REFERENCE.md` before writing or restructuring any skill. Treat it as required context, not optional background.
2. Inspect nearby skills for tone, structure, and command style before inventing a new pattern.
3. Create or edit `skills/<name>/SKILL.md`.
4. Write tight frontmatter:
   - `name` matches the folder name and the skill's attribute name in `skills/flake.nix` (step 7), which is the name Carapace uses.
   - `description` says what the skill does and when to use it.
5. Write the body for the agent who will use the skill, including the operational facts needed for safe normal use.
6. Every skill is a flake: write `flake.nix`, lock it, and commit `flake.lock` (see `REFERENCE.md`). A skill with only instructions needs the few lines of `mkSkill { name = "<name>"; src = ./.; }`. A skill with commands declares them and what they need; add an `Exposed Commands` section near the top of `SKILL.md` with the real command names.
7. List the skill in `skills/flake.nix`: an input `<name>` with `url = "path:./<name>"` that follows `nixpkgs` and `carapace` like the others. `git add skills/<name>`, then `nix flake lock ./skills`. After changing the skill's own inputs or its `flake.lock` later, run `nix flake update <name> --flake ./skills`. Commit `skills/flake.lock` with the skill. A directory that is not listed is not a skill.
8. Build and run every command from the workspace before pushing: `nix shell path:./skills/<name> -c <command> …`. A command that has settings or needs gets them from the committed version of the skill, so a new one of those runs only after its first push and build; until then, run what its `exec` names directly, with the settings in the environment.
9. If implementation or reference material is not needed for normal use, add a sidecar markdown file and link it from `SKILL.md`.
10. Commit and push. `read_skill` sees only pushed skills. After the push, `read_skill(<name>)` waits for the build and puts the commands on `PATH`, in this session too. Tell the user the builder builds the skill after the push and the Knowledge view shows its build state.

## Setup Guidance

If a command needs credentials or network access, declare them in `flake.nix` (a credential slot, bound in `skills/config.json`); the command asks for them itself when it runs. Say that in one line in `SKILL.md`. Do not inline credential wiring, vault paths, or build details there.

## Template

```markdown
---
name: <skill-name>
description: <What the skill does and when to use it.>
---

# <Skill Title>

One short paragraph describing the skill.

## When To Use

- <Concrete trigger or task>
- <Concrete trigger or task>

## Exposed Commands

- `<command>`: <What it does>
- `<command>`: <What it does>

## Workflow

1. <Primary step>
2. <Primary step>
3. <Primary step>

## Guardrails

- <Important limit or safety rule>
- <Important limit or safety rule>

## Setup

If a command asks for a credential, say which vault entry the user has to create and point to `REFERENCE.md` or `CONFIG.md` for details.
```

## Reference

IMPORTANT: Read [REFERENCE.md](REFERENCE.md) before authoring a skill. It contains the required maintainer guidance for file layout, frontmatter, sidecar docs, skill flakes, the development loop, and common failure modes.
