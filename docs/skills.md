# Skill System

carapace skills are modeled on the open [AgentSkills](https://agentskills.io/) format: a `SKILL.md` with the instructions, a name and a description for the catalog, and whatever files the instructions refer to. What AgentSkills keeps in YAML frontmatter, the name and description, is declared in the skill's flake instead, so a repo that takes a skill from elsewhere can adjust it with plain Nix ([sharing-skills.md](sharing-skills.md#overriding-a-shared-skill)).

Every skill is a Nix flake that the Carapace builder builds; [skill-flakes.md](skill-flakes.md) describes how to write one. The server reads its `SKILL.md` from the build, its commands are on the agent's `PATH` in every session, and they ask for what they need when they start.

## Skill structure

`skills/flake.nix` lists the skills of a knowledge repo: every input except `nixpkgs` and `carapace` is a skill, named by its attribute ([skill-flakes.md](skill-flakes.md#the-skills-flake)). A skill directory that is not listed there is not a skill, and a repo without `skills/flake.nix` has no skills at all. A local skill is a directory with a `SKILL.md` file (Markdown instructions, no frontmatter), its own `flake.nix` and `flake.lock`, and whatever else it needs (`scripts/`, `references/`, sources the flake builds from).

```text
skills/
  flake.nix              # lists the skills
  flake.lock             # what the builder builds; commit it with flake.nix
  my-skill/
    SKILL.md             # instructions only
    flake.nix            # name, description, commands (skill-flakes.md)
    flake.lock
    references/          # optional detailed documentation
```

## SKILL.md and the description

`SKILL.md` holds the instructions, plain Markdown. The skill's `name` and `description` are `mkSkill` arguments ([skill-flakes.md](skill-flakes.md#the-flake)); the description is the skill's line in the agent's catalog.

```markdown
# Web Search

Run `web-search "<search terms>"`. It prints JSON with title, URL and
snippet for each result. Summarize the top results for the user.
```

```nix
skill.mkSkill {
  name = "web-search";
  description = "Search the web using SearXNG. Use when the user asks to look something up, find information, or research a topic.";
  src = ./.;
  # commands …
}
```

The skill directory in the store, which `read_skill` and the sandbox see, gets the final `SKILL.md`: `mkSkill`'s `instructions`, by default the contents of `src/SKILL.md`. A `SKILL.md` that still starts with YAML frontmatter fails the evaluation, with a message that points at [the upgrade script](upgrading-to-skill-flakes.md#skillmd-frontmatter). There is no `disabled` switch: a skill is active when `skills/flake.nix` lists it and `skills/config.json` does not set `"enable": false` for it.

## Reading a skill (`read_skill`)

The agent calls `read_skill(skill_name)` before it uses a skill. Nothing is activated or granted: the agent could read the file anyway, and its commands ask for what they need when they start, through [`cgate`](sandbox.md#declaring-needs-up-front-cgate) and `ccred`, reviewed per `exec`.

`read_skill` returns:

- the full `SKILL.md`, from the build,
- the skill's commands with their descriptions and what each one asks for when it starts (domains, credentials, OAuth tokens), read from the build's [manifest](skill-flakes.md#the-manifest), so resolved for this instance's settings,
- whether the commands are on `PATH`; if not, why: the build failed (with the end of its log), the builder is unavailable, two skills expose the same command name, or the profile sync failed,
- where the skill's other files (scripts, references) are in the sandbox: the skill directory's store path, read-only, with the list of files,
- for each MCP server among them, its tools: `read_skill` runs `<server> --list-tools` in the sandbox, every time (nothing is cached). That is an `exec` like any other: the command asks for the server's domain and credentials with `cgate`, and the sentinel decides. Like every `exec`, it first ends processes earlier commands left behind, and `read_skill` says so when it did. A denied listing or an unreachable server is reported with the reason, and the rest of the result still comes back (the `skill` span `list tools`).

It waits until the commands are usable. While the skill builds, it waits for the build (a `skill` span `build wait` in the turn's timeline); then it brings the sandbox's [skill profile](sandbox.md#skill-commands-on-path) to the current head and waits for that too (the `skill` span `profile sync`). Both spans nest under the `read_skill` call, and the chat hears them start and end as [`span` messages](websocket-session.md#span).

`read_skill` finds only skills that `skills/flake.nix` lists at the pushed `HEAD`; for any other name it says how to list one. A skill whose build ended before `SKILL.md` could be read (an evaluation error, a leftover frontmatter among them) returns the reason instead.

Like every tool, the `read_skill` call itself is not reviewed, but it is in the action log, so the sentinel knows which skill the requests that follow belong to.

## Discovery (progressive disclosure)

The agent's system prompt lists every skill `skills/flake.nix` lists, each under its attribute name with the `description` from its [manifest](skill-flakes.md#the-manifest) (~100 tokens per skill). The agent sees what's available without the full instructions consuming context. The server reads the list from `skills/flake.lock`, not by evaluating Nix, and the descriptions from the builds: the builder evaluates the manifest, builds the skill directory alone (it only copies files) and reads `SKILL.md` from it before the commands build. Local skills and skills from other flakes take the same path.

The server gets `SKILL.md` with the build result. While a changed skill builds, or after its rebuild failed before its manifest evaluated, the catalog keeps the description of its last succeeded build; only a skill that was never built says it is being built (or that the builder cannot be reached). Each session takes its catalog once, on its first turn, and keeps it like the memory block until `/compact` ([persistent-context.md](persistent-context.md#known-breaks)); `/skills` shows that same catalog. A skill pushed mid-session is not in the catalog until then, but `read_skill` finds it by name right away. After a server restart, taking a catalog waits briefly for the builder to say which results it already has.

The full `SKILL.md` is loaded only when the agent decides a skill is relevant, with `read_skill`.

### Broken skills

A skill whose manifest does not evaluate (a mistake in its flake, a missing setting, a leftover frontmatter in `SKILL.md`) is still listed, with a description that says it is broken, so the agent can fix it; `read_skill` returns the evaluation error. A build that fails after the manifest evaluated keeps the description and `SKILL.md`.

## Building skills

What is built ends up on the agent's `PATH`; see [sandbox.md](sandbox.md#skill-commands-on-path).

Every skill `skills/flake.nix` lists is built by the [builder](builder.md), each attribute on its own, so a broken skill does not stop the others.

- **When.** Every result belongs to a build key: a hash of the skill's attribute name, the Git ids of `skills/flake.nix`, `skills/flake.lock` and `skills/config.json`, and the Git trees of the directories the skill reads: a local skill's own, and `skills/<attribute>/` when it exists, where an [override](sharing-skills.md#overriding-a-shared-skill) keeps its files (a skill from another flake is pinned by the lock). A skill is built once per key. After a sandbox push is accepted, or a commit from the Knowledge view (an update or a settings save), the server builds the skills at the new head whose key has no result yet: editing one local skill rebuilds only that skill, a change to `skills/flake.nix` or its lock rebuilds every skill, and a change to `skills/config.json` re-evaluates every skill's manifest (the packages stay the same). Content that arrived another way (a pull from upstream, bootstrap seeding) is built when something first asks for it. Nothing waits for a build: a push is never held up or rejected by one.
- **What the server knows.** Per build key: building, built (store paths, the settings and commands from the manifest, and the skill directory's `SKILL.md` and file list), off (`"enable": false` in `skills/config.json`: the skill counts as not listed, `read_skill` says it is off), failed (the end of the build log, or why the builder refused the skill or it could not be archived), or unavailable (no builder configured, or the builder unreachable, answering 5xx or rejecting the server's token; every request asks again). A failed build stays failed until it is retried. A skill without a valid manifest counts as failed, and so does one whose manifest names no skill directory. A failed build keeps the description and `SKILL.md` it read, if it got that far. A manifest without a description comes from helpers older than `mkSkill`'s `description` and counts as failed, with the command that updates them. Results are shared between users with the same key, and the builder keeps them across server restarts.
- **What it reads.** `skills/` at `HEAD`, from Git objects rather than the working tree, so the keys and the archive the builder gets (`skills/flake.nix`, its lock, `config.json`, the skill's own directory and `skills/<attribute>/`) describe the same content. A skill whose flake or override reads any other directory of `skills/` fails to build.
- **Where users see it.** The skill list on `skills/` marks a skill that `skills/flake.nix` overrides, and so does the card of an overridden local skill. The Knowledge view of a listed skill's directory shows its description and build: state, the short build key, the built commands with the domains they declare, and for a failed or unavailable build the end of the log. Opening the view starts the build of a key that has none yet, and the view follows a running build. A failed build has a Retry button (`POST /api/knowledge/skills/<name>/build/retry`), which builds the same key again; anything but a failed build answers 409. Without a usable `skills/flake.nix` (missing, or its lock missing or unreadable) the Knowledge view says so on the repo root and on `skills/`, with the command that fixes it. Waiting for a build and syncing the session profile show up in the turn timeline as `skill` spans (`build wait`, `profile sync`).
- **The catalog.** It never waits for a build, and it shows build state only for a skill that was never built, because it is part of the cached prompt prefix ([persistent-context.md](persistent-context.md#known-breaks)). A re-keyed skill keeps the description of its last succeeded build until the new one is done, and the session profile keeps its commands ([sandbox.md](sandbox.md#skill-commands-on-path)).

## Updates

Skills can come from other repositories too: [sharing-skills.md](sharing-skills.md) covers consuming and publishing them, pinning or following, and Renovate for lock updates.

Every listed skill has an origin (`./<dir>` for a local skill, its flake reference otherwise) and, for a skill from elsewhere, the rev and date `skills/flake.lock` pins. An update check tells whether something newer is there, with one mechanism for both kinds:

- The builder runs `nix flake update <skill> --output-lock-file <tmp>` on a copy of `skills/` at `HEAD`, once per skill, and the server compares that skill's part of the resulting lock with the repo's (its node and the inputs nested under it).
- **Update available:** a skill from elsewhere whose upstream moved, with the rev and date an update would lock. `nix flake update <name> --flake ./skills` takes it.
- **Outdated:** a local skill whose own inputs or `flake.lock` changed without `nix flake update <name> --flake ./skills`. The top-level lock copies a local skill's inputs once, so it goes stale silently otherwise.
- An input pinned to a rev or a tag never moves, so it never reports an update.
- `nixpkgs` and `carapace` are not checked: they are not skills.

The check runs whenever the `skills/` tree at `HEAD` differs from the one the last check covered (a push, a pull or a new lock; session and memory commits leave it alone), once a day, and on demand: the Knowledge view of `skills/` lists every skill with its origin, locked rev and the last check's verdict, and has a "Check for updates" button (`POST /api/knowledge/skills/updates/check`, then `GET /api/knowledge/skills`). Results live in the server's memory; a restart checks again. The agent sees the same in `read_skill` and `list_skills`, never in the skill catalog: the catalog is part of the cached prompt prefix, and a daily check must not change it.

An available update has an "Update" button (`POST /api/knowledge/skills/<name>/update`). The server commits the lock from that check, but only the skill's part of it: `nix flake update` also re-locks outdated local skills on the way, and those stay as they were. The commit is authored by the logged-in user and skips the sentinel, since the human acts. It is then pushed to the remote and built, as after a sandbox push. If `skills/` changed since the check, or `skills/flake.lock` changes while committing, nothing is committed and the button reports why.

## Reading a skill as a security event

A `read_skill` call is not reviewed and lands in the action log like any other tool call, so the sentinel knows which skill the agent has in mind when the next boundary request arrives. Reading grants nothing.

The sentinel can also read skill files directly (via its `list_skill_files` and `read_skill_file` tools, served by the builder from the skill directory of the build at `HEAD`, or of the skill's last succeeded build while the current one runs) to understand what a skill's command will actually do, and which other skills a skill builds on. A skill that relies on another one for access (e.g. repo access through a gitea skill) should say so in its `SKILL.md`, ideally already in the `description`.

## Self-improvement

The agent can create new skills by writing files to `/workspace/skills/` in the sandbox (`SKILL.md`, a flake, and the sources of its commands), listing the skill in `skills/flake.nix`, and then committing and pushing them via Git.

The workflow for the agent to create a skill via chat:

1. User asks for a new skill (or the agent proposes one)
2. Agent plans the skill (`SKILL.md`, a flake, and for commands their sources)
3. Agent writes the files in the sandbox at `/workspace/skills/<skill-name>/`, adds the skill's input to `skills/flake.nix` and runs `nix flake lock ./skills`
4. Agent tests the skill in the sandbox (`nix shell path:./skills/<name> -c <command>`)
5. Agent commits and pushes via Git (the skill, `skills/flake.nix` and its lock); the sentinel evaluates the push via the pre-receive hook
6. On approval, the skill is persisted in the workspace repository, the builder builds it, and its commands reach `PATH` in every session, `read_skill` finds it at once, and new sessions list it in their catalog

A built-in `create-skill` skill is seeded into every new knowledge repo to guide the agent through this process; like any skill, the agent can use it once `skills/flake.nix` lists it ([Bundled skills](#bundled-skills)).

## Bundled skills

Every new knowledge repo lists them in its seeded `skills/flake.nix`, as inputs on Carapace's `main` branch: nothing is copied ([skill-flakes.md](skill-flakes.md#the-skills-flake)). The seeded `skills/config.json` turns off `carapace-cli`, `ferret` and `web`, which need a server, an endpoint or a key first ([settings and credential slots](skill-flakes.md#skillsconfigjson)):

| Skill          | Purpose                                                                        |
| -------------- | ------------------------------------------------------------------------------ |
| `artifacts`    | Build self-contained HTML reports, dashboards, and local tools; [workflow](artifacts.md). |
| `carapace-cli` | Drive a carapace server over its JSON CLI (sessions, approvals, jobs). Off by default; needs `CARAPACE_HOST` and `CARAPACE_API_KEY` ([setup](../src/carapace/assets/skills/carapace/REFERENCE.md)). Its directory is `skills/carapace`: the attribute `carapace` names the helpers every skill follows. |
| `create-skill` | Write and refine skills.                                                       |
| `credentials`  | List, fetch, and use secrets from the vault.                                   |
| `ferret`       | Personal indexed-source discovery over MCP. Off by default; [setup](../src/carapace/assets/skills/ferret/SETUP.md). |
| `mermaid`      | Write Mermaid diagrams; the web UI renders ` ```mermaid ` fences as pictures.   |
| `web`          | Web search and page fetch. Off by default; bind its `BRAVE_API_KEY` slot to a Brave Search API key in `skills/config.json` and remove its `"enable": false`. |
| `wikipedia`    | Wikipedia search and article fetch.                                            |

All of them are [skill flakes](skill-flakes.md); `artifacts`, `create-skill`, `credentials` and `mermaid` carry only instructions. In a knowledge repo they follow the Carapace helpers that `skills/flake.lock` pins. Examples of the helpers live in [`nix/skills/examples`](../nix/skills/examples).

To turn on `carapace-cli`, `ferret` or `web`, give it its settings and credential bindings in `skills/config.json` and remove its `"enable": false`, push, and start a new session. To change a bundled skill beyond that, copy its directory from the Carapace repo into `skills/` and point its input at `path:./<name>`; it is then a local skill like any other. Bootstrap writes `skills/flake.nix`, its lock and `config.json` only into a new repo, and never overwrites them, not even with `reset-assets`.
