---
name: example
description: A template skill showing the AgentSkills format.
---

# Example Skill

This is a template skill that demonstrates the [AgentSkills](https://agentskills.io/) format.

## Instructions

When this skill is activated, greet the user and explain what skills are.

Skills are reusable instruction sets that teach the agent new capabilities.
Each skill lives in its own directory under `skills/` with a `SKILL.md` file.

## Frontmatter

The YAML frontmatter (between `---` markers) provides metadata:

- `name` -- the skill identifier
- `description` -- a short summary shown in the skill catalog

## Creating Your Own Skills

1. Create a new directory under `skills/` (e.g. `skills/my-skill/`)
2. Add a `SKILL.md` file with YAML frontmatter
3. Write instructions the agent should follow when the skill is activated
