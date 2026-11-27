# Sharing skills

A skill is a flake in a directory, so any repository can hold one and any knowledge repo can list it: a skill from a family member's knowledge repo, from a public collection, or one you publish yourself. This guide covers consuming a skill from elsewhere, choosing between pinning and following, publishing a skill so others can use it, and letting Renovate keep the locks current. The formats it relies on are in [skill-flakes.md](skill-flakes.md); how Carapace builds, lists and updates skills is in [skills.md](skills.md).

## Consuming a skill

Say Alice keeps a `weather` skill in her knowledge repo `github.com/alice/knowledge`, under `skills/weather`. To use it, list it in your `skills/flake.nix` like the bundled skills:

```nix
inputs = {
  # …nixpkgs, carapace and your other skills…
  weather = {
    url = "github:alice/knowledge?dir=skills/weather";
    inputs.nixpkgs.follows = "nixpkgs";
    inputs.carapace.follows = "carapace";
  };
};
```

- **The attribute is the name.** `weather` is what the catalog, `read_skill` and `skills/config.json` call it, whatever its `mkSkill` name or frontmatter say. Pick another attribute if it collides with one of yours.
- **Always write both `follows`.** The skill then builds with your `nixpkgs` and your Carapace helpers, the ones every other skill uses, and `nix flake update carapace --flake ./skills` moves them for all. Its other inputs (a Python or npm toolchain, say) come from its own `flake.lock`.
- **Any flake reference works:** `github:`, `gitlab:`, `git+https://…`, `sourcehut:`, with `?dir=` for a skill in a subdirectory. A private repository works on the host of your knowledge remote ([private repositories](#private-repositories)).

Then lock and push, and configure the skill if it declares settings or credential slots:

```sh
nix flake lock ./skills
```

```json
{
  "weather": {
    "settings": { "CITY": "Hamburg" },
    "credentials": { "WEATHER_TOKEN": "personal/weather-token" }
  }
}
```

`read_skill weather` shows what the skill declares, unbound slots included (with the line to add), and a required setting without a value fails the build with its name (see [settings](skill-flakes.md#settings) and [credential slots](skill-flakes.md#credential-slots)). Commit `skills/flake.nix`, `skills/flake.lock` and `skills/config.json` together. Pushed from a sandbox, the sentinel reviews the change, with one line per changed `flake.lock` input ([security.md](security.md#git-push-evaluation)); the builder builds the skill after the push, and new sessions list it.

The skill's commands ask for what they need when they run, reviewed like any other request. Reading its `SKILL.md` and its flake before listing it is still worth it: a skill's instructions reach the agent, and its commands run in your sandboxes.

To change a consumed skill, copy its directory into your `skills/`, point its input at `path:./<dir>`, and lock again. It is then a local skill, and no longer updates from upstream.

## Private repositories

The builder fetches your skill inputs with the token of your [knowledge remote](git.md#authentication) (Settings → Account), for that remote's host only. A skill in a private repository on the same forge as your knowledge repo therefore needs no further setup, as long as that token can read it:

- **Write the input for your knowledge remote's host, over HTTPS:** `git+https://git.example.org/alice/knowledge?dir=skills/weather` works on any forge, `github:alice/knowledge?dir=skills/weather` when the host is `github.com`. For `gitlab:` and `sourcehut:` references the builder does not use the token; write those as `git+https://`. Inputs from other hosts are fetched without credentials, so they must be public.
- **Sharing goes through the forge:** Alice gives Bob read access to her repository (as a collaborator, or through a team or organization), and Bob's token can read it from then on. Carapace has no setting for it.
- **A forge in your LAN,** a self-hosted Gitea for example, is blocked by the builder's egress policy on Kubernetes. List its address in `builder.egress.allowedCidrs` ([egress](builder.md#egress-on-kubernetes)).
- **Lock where you can read the repository.** Sandboxes have no token, so `nix flake lock` fails there for a private input. On your machine git's own credentials cover `git+https` inputs, and `github:` inputs need `access-tokens = github.com=<token>` in your `nix.conf`. Carapace's update check and its "Update" button run on the builder, with your token.

How the builder hands the token to Nix, and that it never lands in a result, is in [builder.md](builder.md#fetch-credentials).

**Known limit: one store for all users.** Nix does not fetch what its store already has, and the builder keeps one store for everyone. A private input that one user's build fetched can serve another user's build without a fetch, and so without that user's token, if their lock names the same input with the same `narHash`. Knowing the `narHash` means knowing the content already, so this hands out nothing new to someone who guessed a URL. It is fine for a family instance, but it is no boundary between users who must not see each other's repositories. Build results are shared the same way: a skill's key covers its flake, lock and directory, so the same skill locked the same way has one result for all users.

## Pinning or following

The input URL decides what an update can move to:

| URL | Locks | Updates |
| --- | --- | --- |
| `github:alice/knowledge?dir=skills/weather` | the default branch's head | to its new head |
| `github:alice/knowledge/dev?dir=skills/weather` | the `dev` branch's head | to its new head |
| `github:alice/knowledge/weather-v2?dir=skills/weather` | the tag `weather-v2` | only if the tag is moved |
| `github:alice/knowledge/<40-hex rev>?dir=skills/weather` | that commit | never |

`skills/flake.lock` holds the exact commit either way, so a build never changes on its own. Following a branch only means that an update has somewhere to go: `nix flake update weather --flake ./skills`, Carapace's update check with its "Update" button ([skills.md](skills.md#updates)), or Renovate (below). A pinned input does not move (a tag only if its publisher moves it), so it reports no update; to move it, change the tag or rev in the URL and lock again.

Follow a branch for skills you trust to stay compatible, such as the bundled ones on Carapace's `main`. Pin to a tag when the publisher tags releases and you want to read the changes before taking them.

## Publishing a skill

Put the skill in its own directory, in your knowledge repo or a repository of its own: `SKILL.md`, `flake.nix`, the committed `flake.lock`, and the code and its lock files if it has commands. [skill-flakes.md](skill-flakes.md) has the formats. A skill with only instructions is a flake of a few lines ([skills with only instructions](skill-flakes.md#skills-with-only-instructions)); one with commands uses `mkSkill` with `uvEnv`, `npmApp` or plain nixpkgs.

Keep everything instance-specific out of it, so it works in any knowledge repo:

- **Inputs named `nixpkgs` and `carapace`**, so consumers can make them follow theirs. Name other inputs as you like.
- **Settings for what differs per instance:** a server URL, a city, a default (`settings.<NAME>`). An MCP server whose address differs per instance takes it from a setting (`mcpCommands { urlSetting = "…"; }`).
- **Credential slots for secrets** (`credentials.<NAME> = { type = "secret" | "oauth"; … }`), never vault paths: a flake that names one fails to evaluate. Each consumer binds the slots to their own password-manager entries.
- **Descriptions on every setting and slot**, since that is what consumers read when they configure the skill, and a `SKILL.md` that says what it needs ("needs a weather API token in its `WEATHER_TOKEN` slot").

Before publishing, build and run it the way a consumer will:

```sh
nix flake lock path:./skills/weather          # its own lock, committed with it
nix build path:./skills/weather#packages.x86_64-linux.default   # or aarch64-linux
```

Its own `flake.lock` pins the inputs that consumers do not override. If consumers should be able to pin, tag the commits you release (`weather-v2`, or `v2` in a repository of its own) and say so.

## Renovate on a knowledge repo

[Renovate](https://docs.renovatebot.com/) can propose lock updates as pull requests on the forge that holds your knowledge repo (the [upstream remote](git.md)), instead of Carapace's update check or a manual `nix flake update`. Its Nix manager is opt-in (in beta as of Renovate 45), and needs a Renovate that can run Nix. Whether a hosted Renovate app runs it depends on that app; a self-hosted Renovate with Nix available does. A `renovate.json` at the root of the knowledge repo:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "nix": {
    "enabled": true,
    "managerFilePatterns": ["/^skills/flake\\.nix$/"]
  },
  "lockFileMaintenance": { "enabled": true }
}
```

- **Only `skills/flake.nix`:** the manager's default pattern matches every `flake.nix`, local skills' own included. Renovate would then update their locks too, which leaves the top-level lock [outdated](skills.md#updates); the pattern above keeps it to the skills flake. A local skill's own inputs are updated with `nix flake update --flake ./skills/<dir>` and then `nix flake update <name> --flake ./skills`.
- **What the PRs look like:** updates of single inputs in `skills/flake.lock`, and with `lockFileMaintenance` a scheduled PR that refreshes the whole lock (on Renovate's lock file maintenance schedule, never grouped with other updates). Only `skills/flake.lock` changes, so a PR is a list of moved inputs. Pinned inputs stay where they are, as above.
- **Who reviews what:** the sentinel reviews what a sandbox pushes, through the server. A Renovate PR is merged on the forge, by you, and never passes the sentinel: your review of the PR is the review, so read which inputs moved and to where, as you would read the sentinel's lines for a lock change.
- **Getting the merge into Carapace:** the server takes remote changes when it starts, on `/pull` in a session, or with "Pull" in the Git sync panel. After the pull, the builder builds the skills whose keys changed, and new sessions see them. A running session keeps its catalog until `/compact`.

Renovate and Carapace's own update check can run side by side: both look at the same lock, and whichever lands first leaves the other nothing to do.
