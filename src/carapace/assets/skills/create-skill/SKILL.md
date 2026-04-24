---
name: create-skill
description: Create and refine Carapace AgentSkills. Use when the user wants to add a new skill, reshape an existing one, or asks how a skill should be structured.
---

# Create Skill

Create or update skills under `skills/<name>/` for Carapace.

## Goal

Produce a skill that is easy for another agent to activate and follow.

- `SKILL.md` is the agent-facing workflow document
- Keep it concise, task-oriented, and specific to the skill's runtime behavior
- Move implementation details, provider setup, long examples, and maintenance notes into a sidecar doc such as `REFERENCE.md`, `CONFIG.md`, or files under `references/`

## What Belongs In `SKILL.md`

Keep only the information an activated agent should need during normal use:

- what the skill does and when to use it
- hard constraints and safety rules
- the normal workflow or command entrypoints
- a short note that credentials or setup are handled automatically, if applicable
- links to sidecar docs when deeper implementation detail exists

Do not turn `SKILL.md` into developer documentation for the skill itself.

## What Belongs Elsewhere

Prefer a sidecar markdown file for:

- provider file layouts and lockfile rules
- full `carapace.yaml` schemas and examples
- authentication wiring and credential internals
- packaging details for Python or Node helpers
- long templates, API references, and maintainer troubleshooting notes

Good filenames are `REFERENCE.md`, `CONFIG.md`, or `references/*.md`.

## Workflow

1. Read `REFERENCE.md` before writing or restructuring any skill. Treat it as required context, not optional background.
2. Inspect nearby skills for tone, structure, and command style before inventing a new pattern.
3. Create or edit `skills/<name>/SKILL.md`.
4. Write tight frontmatter:
   - `name` matches the folder name exactly.
   - `description` says what the skill does and when to use it.
5. Write the body for the agent, not the maintainer.
6. If the skill needs network access, credentials, code, or setup hooks, add the supporting files next to it, but keep `SKILL.md` brief.
7. If setup is non-trivial, add a sidecar markdown file and link it from `SKILL.md`.
8. Tell the user the skill will show up in `/skills` and be available in new sessions.

## Setup Guidance

If a skill needs credentials or network access, note that activation handles them automatically after approval. Do not inline credential wiring, secret-handling procedures, or large `carapace.yaml` walkthroughs in `SKILL.md`.

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
