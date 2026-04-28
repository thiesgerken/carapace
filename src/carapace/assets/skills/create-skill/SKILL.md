---
name: create-skill
description: Create and refine Carapace AgentSkills. Use when the user wants to add a new skill, reshape an existing one, or asks how a skill should be structured.
---

# Create Skill

Create or update skills under `skills/<name>/` for Carapace.

## Goal

Produce a skill that is easy for another agent to activate and follow.

- `SKILL.md` is the agent-facing workflow document
- Keep it complete enough for normal use without extra lookup
- Move only details that are genuinely on-demand, such as provider internals, build setup, exhaustive references, or maintainer notes, into a sidecar doc such as `REFERENCE.md`, `CONFIG.md`, or files under `references/`

## What Belongs In `SKILL.md`

Keep the information an activated agent should know before acting:

- what the skill does and when to use it
- a short list of exposed commands near the top of the body when the skill ships command aliases
- hard constraints and safety rules
- the normal workflow or command entrypoints
- how the skill CLI is supposed to be invoked
- domain facts the agent needs to act correctly, such as project names, folder names, common labels, IDs, account context, or user-specific conventions
- common command examples and syntax traps that prevent mistakes
- a short note that credentials or setup are handled automatically, if applicable
- links to sidecar docs when deeper implementation detail exists

The guiding question is: would the agent make worse decisions, run the wrong command, or need to pause and load another file during normal use without this? If yes, keep it in `SKILL.md`.

Do not turn `SKILL.md` into developer documentation for the skill itself, but do keep the operational knowledge that a runtime agent needs in the moment.

## What Belongs Elsewhere

Prefer a sidecar markdown file only for content that can safely be loaded on demand:

- provider file layouts and lockfile rules
- full `metadata.carapace` schemas and examples
- authentication wiring and credential internals, beyond a short activation note
- packaging details for Python or Node helpers
- implementation internals of wrappers and setup hooks
- exhaustive API references and maintainer troubleshooting notes

Do not move runtime-critical facts out of `SKILL.md` just because they are long, tabular, or user-specific.

Good filenames are `REFERENCE.md`, `CONFIG.md`, or `references/*.md`.

## Workflow

1. Read `REFERENCE.md` before writing or restructuring any skill. Treat it as required context, not optional background.
2. Inspect nearby skills for tone, structure, and command style before inventing a new pattern.
3. Create or edit `skills/<name>/SKILL.md`.
4. Write tight frontmatter:
   - `name` matches the folder name exactly.
   - `description` says what the skill does and when to use it.
5. Write the body for the agent who will use the skill, including the operational facts needed for safe normal use.
6. If the skill exposes command aliases, add an `Exposed Commands` section near the top of `SKILL.md`. List the real aliases there in the body, not in frontmatter.
7. If the skill needs network access, credentials, code, or setup hooks, add the supporting files next to it and summarize the activation behavior in `SKILL.md`.
8. If setup, implementation, or reference material is not needed for normal use, add a sidecar markdown file and link it from `SKILL.md`.
9. Tell the user the skill will show up in `/skills` and be available in new sessions.

## Setup Guidance

If a skill needs credentials or network access, note that activation handles them automatically after approval. Do not inline credential wiring, secret-handling procedures, or large `metadata.carapace` / legacy `carapace.yaml` walkthroughs in `SKILL.md`.

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

- `<command-alias>`: <What it does>
- `<command-alias>`: <What it does>

## Workflow

1. <Primary step>
2. <Primary step>
3. <Primary step>

## Guardrails

- <Important limit or safety rule>
- <Important limit or safety rule>

## Setup

If this skill needs extra setup, note that activation handles it automatically and point to `REFERENCE.md` or `CONFIG.md`.
```

## Reference

IMPORTANT: Read [REFERENCE.md](REFERENCE.md) before authoring a skill. It contains the required maintainer guidance for file layout, frontmatter, sidecar docs, provider manifests, and common failure modes.
