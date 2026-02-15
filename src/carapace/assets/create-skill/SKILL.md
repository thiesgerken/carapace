---
name: create-skill
description: Create and edit AgentSkills for Carapace. Use when the user wants to add a new skill, edit an existing one, or asks about the skill format.
---

# Create Skill

Guide for creating and maintaining Carapace skills that follow the open [AgentSkills](https://agentskills.io/) format.

## Skill location

Skills live under `skills/` in the data directory. Each skill is a directory containing at minimum a `SKILL.md` file:

```
skills/
  my-skill/
    SKILL.md          # required
    scripts/           # optional: executable code
    references/        # optional: additional docs
    assets/            # optional: templates, data files
```

## SKILL.md format

### Frontmatter (required)

```yaml
---
name: my-skill
description: What this skill does and when to use it. Be specific -- this is what the agent reads at startup to decide whether to activate the skill.
---
```

**`name` rules:**

- Must match the parent directory name exactly
- Lowercase letters, numbers, and hyphens only
- No consecutive hyphens (`--`), no leading/trailing hyphens
- Max 64 characters

**`description` rules:**

- Include keywords that help identify relevant tasks
- Describe both _what_ the skill does and _when_ to use it
- Max 1024 characters

Optional frontmatter fields:

| Field           | Purpose                                             |
| --------------- | --------------------------------------------------- |
| `license`       | License name or reference to a bundled LICENSE file |
| `compatibility` | Environment requirements (tools, network, etc.)     |
| `metadata`      | Arbitrary key-value pairs (author, version, etc.)   |

### Body (instructions)

The markdown body after the frontmatter is the actual skill content. There are no format restrictions. Write whatever helps perform the task effectively.

Recommended sections:

- When to use / when not to use
- Step-by-step instructions
- Common edge cases
- Input/output examples

## Progressive disclosure

Carapace loads skills in three tiers:

1. **Discovery** (~100 tokens): `name` + `description` loaded at startup for all skills
2. **Activation** (< 5000 tokens recommended): full `SKILL.md` body loaded via `activate_skill`
3. **Resources** (on demand): files in `scripts/`, `references/`, `assets/` loaded only when referenced

Keep `SKILL.md` under 500 lines. Move detailed reference material to separate files and reference them with relative paths:

```markdown
See [the API reference](references/api.md) for endpoint details.
```

## Carapace-specific conventions

### Security rules that apply

- **`skill-modification`** (always active): creating, editing, or deleting any file under `skills/` requires user approval. The user will be prompted automatically.
- **`no-exfil-after-skill-read`**: after activating a skill (reading its instructions), outbound communication is blocked without approval. Keep this in mind -- skills may contain sensitive workflow details.

### Creating a skill step by step

1. Choose a name: lowercase, hyphenated, descriptive (e.g. `email-summary`, `git-changelog`)
2. Create the directory and `SKILL.md` using the `write` tool:
   - Path: `skills/<name>/SKILL.md`
   - The `skill-modification` rule will trigger approval
3. Write clear frontmatter with a good `description`
4. Write concise instructions in the body
5. Optionally add `scripts/`, `references/`, or `assets/` directories
6. Tell the user the skill will appear in `/skills` and be available in new sessions

### Editing an existing skill

Use the `edit` tool on `skills/<name>/SKILL.md`. The same approval rule applies.

### Good description examples

```yaml
# Good -- specific, mentions triggers
description: Summarise email threads and draft replies. Use when the user mentions email, inbox, or wants to compose a message.

# Bad -- too vague
description: Helps with email.
```

### Template

When creating a new skill, start from this template and adapt it:

```markdown
---
name: <skill-name>
description: <What it does and when to use it.>
---

# <Skill Title>

## When to use

<Describe the situations where this skill applies.>

## Instructions

<Step-by-step guidance for the agent.>

## Edge cases

<Things to watch out for.>
```
