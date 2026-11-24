# Skill System

carapace uses the open [AgentSkills](https://agentskills.io/) format for skills. This makes skills portable to any AgentSkills-compatible agent (Claude Code, Cursor, Gemini CLI, etc.) while carapace adds its own security layer on top.

A skill with commands is a Nix flake that the Carapace builder builds; [skill-flakes.md](skill-flakes.md) describes how to write one. Its commands are on the agent's `PATH` in every session, and they ask for what they need when they start.

## Skill structure

A skill is a directory with a `SKILL.md` file (Markdown instructions with YAML frontmatter), optionally a `flake.nix` and `flake.lock` that build its commands, and whatever else it needs (`scripts/`, `references/`, sources the flake builds from).

```text
skills/
  my-skill/
    SKILL.md             # required: instructions and optional metadata.carapace
    flake.nix            # optional: builds the skill's commands (skill-flakes.md)
    flake.lock           # required next to flake.nix
    references/          # optional detailed documentation
```

A skill without a flake has no commands: its instructions are all there is to it.

## SKILL.md (AgentSkills standard)

The skill's instructions follow the AgentSkills format: YAML frontmatter with at minimum `name` and `description`, followed by Markdown instructions.

```markdown
---
name: web-search
description: >
  Search the web using SearXNG. Use when the user asks to look
  something up, find information, or research a topic.
---

# Web Search

Run `web-search "<search terms>"`. It prints JSON with title, URL and
snippet for each result. Summarize the top results for the user.
```

## carapace metadata

`metadata.carapace` in the frontmatter holds what Carapace needs beyond the AgentSkills fields:

```yaml
---
name: web-search
description: Search the web.
metadata:
  carapace:
    disabled: true
---
```

**`disabled`** — optional boolean, default `false`. Set `metadata.carapace.disabled: true` to exclude a skill from automatic discovery, agent catalogs, shared prompts, prompt previews and builds; `read_skill` refuses it. The files remain browsable and editable in the Knowledge UI/API. Set it to `false` (or remove it) to opt in, then start a new session: the catalog of a running session does not change.

**`hints`** — optional map of strings, extra metadata for tooling.

**`mcp`** — still accepted, but nothing reads it any more: MCP servers are flake commands now ([skill-flakes.md](skill-flakes.md#mcp-servers)). The field goes away with [#578](https://github.com/thiesgerken/carapace/issues/578).

`network`, `credentials` and `commands` moved into the skill's flake, where each command declares the domains, credentials and OAuth entries it needs ([skill-flakes.md](skill-flakes.md#commands-and-what-they-need)). A `SKILL.md` that still has one of them is [broken](#invalid-frontmatter), with a message that points there.

## Reading a skill (`read_skill`)

The agent calls `read_skill(skill_name)` before it uses a skill. Nothing is activated or granted: the agent could read the file anyway, and its commands ask for what they need when they start, through [`cgate`](sandbox.md#declaring-needs-up-front-cgate) and `ccred`, reviewed per `exec`.

`read_skill` returns:

- the full `SKILL.md`,
- the skill's commands with their descriptions and what each one asks for when it starts (domains, credentials, OAuth tokens), read from the build's `passthru.carapace`,
- whether the commands are on `PATH`; if not, why: the build failed (with the end of its log), the builder is unavailable, two skills expose the same command name, or the profile sync failed.

It waits until the commands are usable. While the skill builds, it waits for the build (a `skill` span `build wait` in the turn's timeline); then it brings the sandbox's [skill profile](sandbox.md#skill-commands-on-path) to the current head and waits for that too (the `skill` span `profile sync`). Both spans nest under the `read_skill` call, and the chat hears them start and end as [`span` messages](websocket-session.md#span). A skill without a flake returns at once.

`read_skill` is not reviewed, like every tool, but the call is in the action log, so the sentinel knows which skill the requests that follow belong to.

## Discovery (progressive disclosure)

At startup, carapace loads only `name` and `description` from each enabled skill's frontmatter (~100 tokens per skill). These are injected into the agent's system prompt as a skill catalog. The agent sees what's available without the full instructions consuming context. Skills with `metadata.carapace.disabled: true` are omitted.

The full `SKILL.md` is loaded only when the agent decides a skill is relevant, with `read_skill`.

### Invalid frontmatter

A `SKILL.md` without frontmatter is valid: its directory name becomes the skill name. Frontmatter that cannot be read (invalid YAML such as an unquoted value containing a colon followed by a space, a missing closing `---`, a non-string `name` or `description`, a non-mapping `metadata`) or an invalid `metadata.carapace` makes the skill broken:

- The catalog still lists it under its directory name, with a description that says it is broken and why, so the agent can fix it. The server logs the error.
- `read_skill` returns the error together with the file's text.
- The builder does not build it; its build state is failed with the error.
- The Knowledge UI shows the error on the skill card; for invalid YAML it renders the raw file.

The opt-out survives an invalid `metadata.carapace`, because `disabled: true` is read from the raw mapping. Invalid YAML cannot carry an opt-out, so such a skill is listed as broken (directory name and error position only, no file content) until it is fixed.

## Building skills

What is built ends up on the agent's `PATH`; see [sandbox.md](sandbox.md#skill-commands-on-path).

A skill with a `flake.nix` next to its `SKILL.md` is built by the [builder](builder.md); a skill without one has no commands and is never built. A disabled skill is not built either.

- **When.** Every result belongs to the Git tree hash of the skill directory, so a skill is built once per content. After a sandbox push is accepted, the server builds the skill trees at the new head that have no result yet: only the skills the push changed. Content that arrived another way (a pull from upstream, the Knowledge UI, bootstrap seeding) is built when something first asks for it. Nothing waits for a build: a push is never held up or rejected by one.
- **What the server knows.** Per skill tree: building, built (store paths and the commands from `passthru.carapace`), failed (the end of the build log, or why the builder refused the skill or it could not be archived), or unavailable (no builder configured, or the builder unreachable, answering 5xx or rejecting the server's token; every request asks again). A failed build stays failed until it is retried. A package without valid `mkSkill` metadata counts as failed. Results are shared between users with the same skill tree, and the builder keeps them across server restarts.
- **What it reads.** The skill directory at `HEAD`, from Git objects rather than the working tree, so the tree hash, the archive the builder gets and the checks (`flake.nix` present, not disabled) all describe the same content.
- **Where users see it.** The Knowledge view of a skill directory under `skills/` shows its build: state, the short tree hash, the built commands with the domains they declare, and for a failed or unavailable build the end of the log. Opening the view starts the build of a tree that has none yet, and the view follows a running build. A failed build has a Retry button (`POST /api/knowledge/skills/<name>/build/retry`), which builds the same tree again; anything but a failed build answers 409. Waiting for a build and syncing the session profile show up in the turn timeline as `skill` spans (`build wait`, `profile sync`).
- **The catalog stays out of it.** The skill catalog is read from frontmatter only, never waits for the builder and never contains build state, because it is part of the cached prompt prefix ([persistent-context.md](persistent-context.md)).

## Reading a skill as a security event

A `read_skill` call is not reviewed and lands in the action log like any other tool call, so the sentinel knows which skill the agent has in mind when the next boundary request arrives. Reading grants nothing.

The sentinel can also read skill files directly (via its `list_skill_files` and `read_skill_file` tools) to understand what a skill's command will actually do, and which other skills a skill builds on. A skill that relies on another one for access (e.g. repo access through a gitea skill) should say so in its `SKILL.md`, ideally already in the `description`.

## Self-improvement

The agent can create new skills by writing files to `/workspace/skills/` in the sandbox (`SKILL.md`, and a flake with its sources for commands) and then committing and pushing them via Git.

The workflow for the agent to create a skill via chat:

1. User asks for a new skill (or the agent proposes one)
2. Agent plans the skill (`SKILL.md`, and for commands a flake with its sources)
3. Agent writes the files in the sandbox at `/workspace/skills/<skill-name>/`
4. Agent tests the skill in the sandbox (`nix shell path:./skills/<name> -c <command>`)
5. Agent commits and pushes via Git — the sentinel evaluates the push via the pre-receive hook
6. On approval, the skill is persisted in the workspace repository, the builder builds it, and its commands reach `PATH` in every session; new sessions also list it in their catalog

A built-in `create-skill` skill is seeded on first run to guide the agent through this process.

## Bundled skills

These are seeded into every knowledge repo on first run and can be edited or deleted like any other skill:

| Skill          | Purpose                                                                        |
| -------------- | ------------------------------------------------------------------------------ |
| `artifacts`    | Build self-contained HTML reports, dashboards, and local tools; [workflow](artifacts.md). |
| `carapace`     | Drive a carapace server over its JSON CLI (sessions, approvals, jobs).         |
| `create-skill` | Write and refine skills.                                                       |
| `credentials`  | List, fetch, and use secrets from the vault.                                   |
| `ferret`       | Personal indexed-source discovery over native HTTP MCP. Disabled by default; [setup](../src/carapace/assets/skills/ferret/SETUP.md). |
| `mermaid`      | Write Mermaid diagrams; the web UI renders ` ```mermaid ` fences as pictures.   |
| `web`          | Web search and page fetch. Disabled by default; requires a Brave Search API key at `vault/brave-api-key` before enabling. |
| `wikipedia`    | Wikipedia search and article fetch.                                            |

`carapace`, `web` and `wikipedia` have commands, so they are [skill flakes](skill-flakes.md) that pin a Carapace commit in their `flake.lock`; the others are a `SKILL.md` with references. Examples of the helpers live in [`nix/skills/examples`](../nix/skills/examples).

Configure disabled bundled skills in their copied `SKILL.md`, set `metadata.carapace.disabled: false`, and start a new session. Normal bootstrap seeds missing bundled skill directories without overwriting existing copies or user edits, including Web copies without a disabled flag. Explicit `reset-assets` overwrites bundled customization and restores shipped opt-out defaults.
