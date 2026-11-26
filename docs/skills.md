# Skill System

carapace uses the open [AgentSkills](https://agentskills.io/) format for skills. This makes skills portable to any AgentSkills-compatible agent (Claude Code, Cursor, Gemini CLI, etc.) while carapace adds its own security layer on top.

A skill with commands is a Nix flake that the Carapace builder builds; [skill-flakes.md](skill-flakes.md) describes how to write one. Its commands are on the agent's `PATH` in every session, and they ask for what they need when they start.

## Skill structure

`skills/flake.nix` lists the skills of a knowledge repo: every input except `nixpkgs` and `carapace` is a skill, named by its attribute ([skill-flakes.md](skill-flakes.md#the-skills-flake)). A skill directory that is not listed there is not a skill, and a repo without `skills/flake.nix` has no skills at all. A local skill is a directory with a `SKILL.md` file (Markdown instructions with YAML frontmatter), its own `flake.nix` and `flake.lock`, and whatever else it needs (`scripts/`, `references/`, sources the flake builds from).

```text
skills/
  flake.nix              # lists the skills
  flake.lock             # what the builder builds; commit it with flake.nix
  my-skill/
    SKILL.md             # instructions and optional metadata.carapace
    flake.nix            # builds the skill's commands (skill-flakes.md)
    flake.lock
    references/          # optional detailed documentation
```

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
    hints:
      web-search: Prefer recent results.
---
```

**`hints`** — optional map of strings, extra metadata for tooling.

There is no `disabled` any more: a skill is active when `skills/flake.nix` lists it. To turn one off, remove its input there and lock again. A `SKILL.md` that still sets `disabled` is [broken](#invalid-frontmatter), with a message that says so.

`network`, `credentials`, `commands` and `mcp` moved into the skill's flake: each command declares the domains, credentials and OAuth entries it needs ([skill-flakes.md](skill-flakes.md#commands-and-what-they-need)), and an MCP server is a command made by `mcpCommands` ([skill-flakes.md](skill-flakes.md#mcp-servers)). A `SKILL.md` that still has one of them is [broken](#invalid-frontmatter), with a message that points there.

## Reading a skill (`read_skill`)

The agent calls `read_skill(skill_name)` before it uses a skill. Nothing is activated or granted: the agent could read the file anyway, and its commands ask for what they need when they start, through [`cgate`](sandbox.md#declaring-needs-up-front-cgate) and `ccred`, reviewed per `exec`.

`read_skill` returns:

- the full `SKILL.md`,
- the skill's commands with their descriptions and what each one asks for when it starts (domains, credentials, OAuth tokens), read from the build's `passthru.carapace`,
- whether the commands are on `PATH`; if not, why: the build failed (with the end of its log), the builder is unavailable, two skills expose the same command name, or the profile sync failed,
- for each MCP server among them, its tools: `read_skill` runs `<server> --list-tools` in the sandbox, every time (nothing is cached). That is an `exec` like any other: the command asks for the server's domain and credentials with `cgate`, and the sentinel decides. Like every `exec`, it first ends processes earlier commands left behind, and `read_skill` says so when it did. A denied listing or an unreachable server is reported with the reason, and the rest of the result still comes back (the `skill` span `list tools`).

It waits until the commands are usable. While the skill builds, it waits for the build (a `skill` span `build wait` in the turn's timeline); then it brings the sandbox's [skill profile](sandbox.md#skill-commands-on-path) to the current head and waits for that too (the `skill` span `profile sync`). Both spans nest under the `read_skill` call, and the chat hears them start and end as [`span` messages](websocket-session.md#span).

`read_skill` finds only skills that `skills/flake.nix` lists in the server's copy of the repo; for any other name it says how to list one.

Like every tool, the `read_skill` call itself is not reviewed, but it is in the action log, so the sentinel knows which skill the requests that follow belong to.

## Discovery (progressive disclosure)

At startup, carapace loads only the `description` from the frontmatter of each skill `skills/flake.nix` lists (~100 tokens per skill). These are injected into the agent's system prompt as a skill catalog, each under the skill's attribute name. The agent sees what's available without the full instructions consuming context. The server reads the list from `skills/flake.lock`, not by evaluating Nix. A skill from another flake (not a `path:` input) has no `SKILL.md` in the repo, so it is not in the catalog yet.

The full `SKILL.md` is loaded only when the agent decides a skill is relevant, with `read_skill`.

### Invalid frontmatter

A `SKILL.md` without frontmatter is valid. A skill's name is always its attribute in `skills/flake.nix`, whatever `name` says. Frontmatter that cannot be read (invalid YAML such as an unquoted value containing a colon followed by a space, a missing closing `---`, a non-string `name` or `description`, a non-mapping `metadata`) or an invalid `metadata.carapace` makes the skill broken:

- The catalog still lists it, with a description that says it is broken and why, so the agent can fix it. The server logs the error. A listed local skill without a `SKILL.md` is listed as broken too.
- `read_skill` returns the error together with the file's text.
- The Knowledge UI shows the error on the skill card; for invalid YAML it renders the raw file.

The build does not read `SKILL.md`, so a broken one does not stop the skill's commands.

## Building skills

What is built ends up on the agent's `PATH`; see [sandbox.md](sandbox.md#skill-commands-on-path).

Every skill `skills/flake.nix` lists is built by the [builder](builder.md), each attribute on its own, so a broken skill does not stop the others.

- **When.** Every result belongs to a build key: a hash of the skill's attribute name, the Git ids of `skills/flake.nix` and `skills/flake.lock`, and the Git tree of the skill's own directory (none for a skill from another flake, which the lock pins). A skill is built once per key. After a sandbox push is accepted, the server builds the skills at the new head whose key has no result yet: editing one local skill rebuilds only that skill, a change to `skills/flake.nix` or its lock rebuilds every skill. Content that arrived another way (a pull from upstream, the Knowledge UI, bootstrap seeding) is built when something first asks for it. Nothing waits for a build: a push is never held up or rejected by one.
- **What the server knows.** Per build key: building, built (store paths and the commands from `passthru.carapace`), failed (the end of the build log, or why the builder refused the skill or it could not be archived), or unavailable (no builder configured, or the builder unreachable, answering 5xx or rejecting the server's token; every request asks again). A failed build stays failed until it is retried. A package without valid `mkSkill` metadata counts as failed. Results are shared between users with the same key, and the builder keeps them across server restarts.
- **What it reads.** `skills/` at `HEAD`, from Git objects rather than the working tree, so the keys and the archive the builder gets (the whole `skills/` directory, which relative `path:` inputs need) describe the same content.
- **Where users see it.** The Knowledge view of a listed skill's directory shows its build: state, the short build key, the built commands with the domains they declare, and for a failed or unavailable build the end of the log. Opening the view starts the build of a key that has none yet, and the view follows a running build. A failed build has a Retry button (`POST /api/knowledge/skills/<name>/build/retry`), which builds the same key again; anything but a failed build answers 409. Without a usable `skills/flake.nix` (missing, or its lock missing or unreadable) the Knowledge view says so on the repo root and on `skills/`, with the command that fixes it. Waiting for a build and syncing the session profile show up in the turn timeline as `skill` spans (`build wait`, `profile sync`).
- **The catalog stays out of it.** The skill catalog is read from frontmatter only, never waits for the builder and never contains build state, because it is part of the cached prompt prefix ([persistent-context.md](persistent-context.md)).

## Reading a skill as a security event

A `read_skill` call is not reviewed and lands in the action log like any other tool call, so the sentinel knows which skill the agent has in mind when the next boundary request arrives. Reading grants nothing.

The sentinel can also read skill files directly (via its `list_skill_files` and `read_skill_file` tools) to understand what a skill's command will actually do, and which other skills a skill builds on. A skill that relies on another one for access (e.g. repo access through a gitea skill) should say so in its `SKILL.md`, ideally already in the `description`.

## Self-improvement

The agent can create new skills by writing files to `/workspace/skills/` in the sandbox (`SKILL.md`, and a flake with its sources for commands) and then committing and pushing them via Git.

The workflow for the agent to create a skill via chat:

1. User asks for a new skill (or the agent proposes one)
2. Agent plans the skill (`SKILL.md`, and for commands a flake with its sources)
3. Agent writes the files in the sandbox at `/workspace/skills/<skill-name>/`, adds the skill's input to `skills/flake.nix` and runs `nix flake lock ./skills`
4. Agent tests the skill in the sandbox (`nix shell path:./skills/<name> -c <command>`)
5. Agent commits and pushes via Git (the skill, `skills/flake.nix` and its lock); the sentinel evaluates the push via the pre-receive hook
6. On approval, the skill is persisted in the workspace repository, the builder builds it, and its commands reach `PATH` in every session; new sessions also list it in their catalog

A built-in `create-skill` skill is seeded into every new knowledge repo to guide the agent through this process; like any skill, the agent can use it once `skills/flake.nix` lists it ([Bundled skills](#bundled-skills)).

## Bundled skills

These are seeded into every new knowledge repo and can be edited or deleted like any other skill. The seeded `skills/flake.nix` lists the ones that have a flake and need no setup, `carapace-cli` and `wikipedia`:

| Skill          | Purpose                                                                        |
| -------------- | ------------------------------------------------------------------------------ |
| `artifacts`    | Build self-contained HTML reports, dashboards, and local tools; [workflow](artifacts.md). |
| `carapace-cli` | Drive a carapace server over its JSON CLI (sessions, approvals, jobs). Its directory is `skills/carapace`: the attribute `carapace` names the helpers every skill follows. |
| `create-skill` | Write and refine skills.                                                       |
| `credentials`  | List, fetch, and use secrets from the vault.                                   |
| `ferret`       | Personal indexed-source discovery over MCP. Not listed by default; [setup](../src/carapace/assets/skills/ferret/SETUP.md). |
| `mermaid`      | Write Mermaid diagrams; the web UI renders ` ```mermaid ` fences as pictures.   |
| `web`          | Web search and page fetch. Not listed by default; requires a Brave Search API key at `vault/brave-api-key` before listing it. |
| `wikipedia`    | Wikipedia search and article fetch.                                            |

`carapace-cli`, `ferret`, `web` and `wikipedia` have commands, so they are [skill flakes](skill-flakes.md); in a knowledge repo they follow the Carapace commit that `skills/flake.lock` pins. The others are a `SKILL.md` with references and are not listed yet. Examples of the helpers live in [`nix/skills/examples`](../nix/skills/examples).

To turn on a bundled skill that is not listed, set it up in its copied directory, uncomment its input in `skills/flake.nix`, run `nix flake lock ./skills`, push, and start a new session. Normal bootstrap seeds missing bundled skill directories without overwriting existing copies or user edits. Explicit `reset-assets` overwrites bundled customization, but never `skills/flake.nix`.
