<p align="center">
  <a href="https://github.com/thiesgerken/carapace/actions/workflows/release.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/thiesgerken/carapace/release.yml"></a>
  <a href="https://github.com/thiesgerken/carapace/releases"><img alt="Release" src="https://img.shields.io/github/v/release/thiesgerken/carapace?display_name=tag"></a>
  <a href="https://www.python.org/"><img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-0F766E"></a>
  <a href="charts/carapace/README.md"><img alt="Helm chart" src="https://img.shields.io/badge/helm-chart-0F766E?logo=helm&logoColor=white"></a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
    <img src="docs/assets/logo-light.svg" alt="carapace" width="420">
  </picture>
</p>
<p align="center"><strong>A secure personal AI agent for DevOps engineers.</strong></p>

<p align="center">Zero trust. Git-backed knowledge. Kubernetes Sandboxes.</p>

<p align="center">
  <a href="docs/quickstart.md">🚀 Quickstart</a>
  ·
  <a href="docs/security.md">🛡️ Security Model</a>
  ·
  <a href="docs/kubernetes.md">☸️ Kubernetes</a>
  ·
  <a href="charts/carapace/README.md">⚓ Helm Chart</a>
</p>

carapace is a self-hosted AI agent with a web UI, CLI, and Matrix channel for operators who want an assistant they can actually reason about. Every meaningful action is evaluated by a dedicated sentinel LLM against your natural-language security policy, executed inside a containerized sandbox, and recorded in an audit trail. Its durable context is not hidden inside an app-specific database: personality, policy, skills, and archived sessions live in Git-backed knowledge repos you can inspect, diff, and sync.

## Highlights

- 🛡️ Sentinel-gated execution. Every non-trivial action is reviewed by a dedicated security agent that keeps session context, not a static allowlist spreadsheet.
- ☸️ Kubernetes-ready sandboxes. Docker and Kubernetes runtimes are both supported, with StatefulSet-backed sandbox sessions, per-session PVCs, idle-to-zero scaling, and an optional warm pool of prestarted base sandboxes for faster Kubernetes claims.
- 🗃️ Git-native per-user knowledge repos. `SOUL.md`, `USER.md`, `SECURITY.md`, skills, and archived sessions live in files you can inspect, diff, sync, and push upstream.
- 🚫 No-direct-internet sandboxes. Sandbox workloads do not get ambient internet access; outbound traffic is forced through the proxy path.
- 🔑 Context-scoped credentials. Secrets stay in your vault, with native Bitwarden support, and are only injected or fetched on demand for exec calls that have the matching approved skill context. Neither the agent nor the backend have a giant `.env` with all of your secrets.
- 👥 Multi-user. Bootstrap an admin user, then manage users, roles, passwords, per-user models, Matrix, Git, and credential backends from Settings. Invite your family!
- 📊 Diagrams in chat. ` ```mermaid ` blocks render as diagrams in the web UI (source toggle, copy, SVG download), and a bundled `mermaid` skill teaches the agent when and how to draw them.
- 🧠 Long-term memory you can inspect. Archived sessions are distilled into per-session extractions and weekly and monthly digests of what was on your mind and what was learned about you, each with full provenance (model, prompt version, input, cost). LLM work runs as tasks in a budgeted queue that you control, and the results are mirrored as Markdown into your knowledge repo.
- ⏰ Built-in jobs and scheduling. Saved jobs can run on demand or by cron, either in fresh unattended sessions or in reused attended sessions.
- 🌐 Bring your own LLM — tested with Gemini, LMStudio and llama.cpp. The agent loop is handled by [Pydantic AI](https://github.com/pydantic/pydantic-ai), which supports lots of LLM backends.

## Motivation

Who doesn't want a personal assistant? OpenClaw showed that this is achievable with LLMs right now. I just didn't like the whole setup — Letting my agent chat with other people is not really important for me. I want something that I can trust and that is not overloaded with features I don't need. I'm pretty sure that there will come another project that has all that stuff, but until then, I'm just going to code and use my own "personal agent harness".

## Screenshots

<p align="center">
  <img src="docs/assets/screenshots/sandbox_info.png" width="1000">
</p>

<p align="center"><em>The web UI surfaces sandbox state, knowledge-repo status, and sentinel-reviewed actions in one place.</em></p>

<br>

<p align="center">
  <img src="docs/assets/screenshots/pancake_web.png" width="1000">
</p>

<p align="center"><em>A web search skill is bundled out of the box. Tool calls and any outbound access is monitored by another agent. Credentials are provided on-demand only.</em></p>

<br>

<p align="center">
  <img src="docs/assets/screenshots/pancake_skill.png" width="1000">
</p>

<p align="center"><em>The agent can improve itself and submit changes to its config via git. Git pushes are proxied + guarded as well.</em></p>

<br>

<p align="center">
  <img src="docs/assets/screenshots/pancake_git.png" width="1000">
</p>

<p align="center"><em>The agent has a local copy of the repository in its sandbox. Conversation histories are automatically committed.</em></p>

<br>

<p align="center">
  <img src="docs/assets/screenshots/pancake_tree.png" width="1000">
</p>

<p align="center"><em>State of one user's knowledge repo after some sessions and a new skill were added.</em></p>

<p align="center">
  <img src="docs/assets/screenshots/post_readonly.png" width="1000">
</p>

<p align="center"><em>Example of a tool call that was intercepted and blocked by the sentinel due to security policy.</em></p>

## Remarks

- Mandatory AI-Disclaimer: Of course I use AI for coding. Everything else just doesn't make sense. The frontend is almost purely vibe-coded, and the backend is review-coded. I try to not touch any files in the backend myself, but I do look at changes to critical code. The architectural and security ideas and decisions are my own. I do have over 20 years of experience in coding without AI.
- Batteries are not included. The point is to use the agent to build out your own skills and workflows.
- I made this for me! And because making stuff is fun. And sharing stuff is fun. I don't mind if `{{some cool project}}` is better or solves the same problem.
- carapace is pre-1.0. Expect breaking changes before `1.0.0`.
- The matrix and CLI connectors are functional, but pretty bare-bones. My focus right now is the Web UI, but the architecture is not hard-coded to that being the only client.

## Knowledge Repo, Not Hidden State

carapace treats long-term agent state as a repository, not as an opaque internal store.

- The agent's policy lives in `SECURITY.md`.
- Its personality and user model live in `SOUL.md` and `USER.md`.
- Skills are plain files in AgentSkills format.
- Durable context is markdown and other plain files on disk.
- Session histories can be archived into the owning user's knowledge repo and pushed upstream.
- Long-term memory is mirrored into `memory/` as Markdown, with provenance in every file.

That makes the system inspectable in a way most agent projects are not. You can review what changed, diff it, sync it, and audit how the agent's knowledge evolves over time.

## Security Model

- Sentinel agent evaluates every non-trivial action against a natural-language policy, not a rigid matrix of rules.
- Strict veto semantics apply: if the safe path, sentinel, or user says no, the action does not proceed.
- Sandboxed execution provides a hard boundary for file and process activity.
- Outbound traffic goes through a proxy, with domain plausibility checks and visible approval events.
- Domains, credentials, and tunnels are scoped to individual exec calls, so privileges do not accumulate across a long-running session.
- Credential access is session-aware and auditable, with a fast path only when a matching skill context explicitly covers it.
- Git pushes from the knowledge workflow are security-reviewed like other sensitive actions.

See [docs/security.md](docs/security.md), [docs/credentials.md](docs/credentials.md), and [docs/sandbox.md](docs/sandbox.md) for the full model.

## Getting Started

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY and CARAPACE_TOKEN
# CARAPACE_TOKEN is only the initial password for the bootstrap admin user

docker compose --profile build pull
docker compose up -d
```

This starts the proxy at `http://localhost:3001`, serving the frontend and routing `/api` to the backend internally.

Published images target Linux x64. On Apple Silicon, use the [native ARM Linux build instructions](docs/development.md#native-linux-images-on-apple-silicon) and local Compose overlay instead of x86 emulation. Nix is the single build/check definition for the server, frontend, and Bitwarden images; only the sandbox remains a Dockerfile. The maintained Compose and Helm configurations run the application images non-root with read-only roots.

Optional CLI connection:

```bash
# First login to the web UI as admin with CARAPACE_TOKEN, then create your normal user.

uv run carapace --user alice --password change-me
```

The web UI uses the same username/password login and stores the session in an HttpOnly cookie. Admin users can manage local users and platform model defaults from **Settings**; normal users manage their own account defaults, Matrix channel, Git remote, and credential backends there too.

You can use whichever LLM backend fits your setup: hosted APIs, self-hosted `vllm`, `llama.cpp`, LM Studio, or anything else that exposes a compatible endpoint.

For the full Docker Compose setup, multi-user auth model, UI-managed configuration, credential backends, Matrix integration, and knowledge-repo configuration, see [docs/quickstart.md](docs/quickstart.md) and [docs/auth.md](docs/auth.md). For Kubernetes deployment, see [docs/kubernetes.md](docs/kubernetes.md) and [charts/carapace/README.md](charts/carapace/README.md).

## Architecture

The server runs the agent loop, session lifecycle, and security system. The CLI, web UI, and Matrix channel are thin clients. Owner-scoped knowledge repos are a first-class part of the design: session output can be promoted into Git-backed knowledge, and outbound Git operations are security-reviewed instead of treated as an afterthought.

See [docs/architecture.md](docs/architecture.md) for the diagrams and fuller architecture breakdown.

## Core Docs

| Topic                                                          | What it covers                                                             |
| -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| [docs/quickstart.md](docs/quickstart.md)                       | Docker Compose setup, users, UI settings, credentials, and Matrix          |
| [docs/security.md](docs/security.md)                           | Sentinel policy model, audit trail, approvals, and veto semantics          |
| [docs/skills.md](docs/skills.md)                               | AgentSkills support, context-scoped access, providers, and command aliases |
| [docs/credentials.md](docs/credentials.md)                     | Vault-backed credentials, approval flow, and per-exec injection            |
| [docs/jobs.md](docs/jobs.md)                                   | Saved jobs, cron scheduling, persistent-session jobs, and job API          |
| [docs/notifications.md](docs/notifications.md)                 | Web Push delivery, presence tracking, suppression, and notification APIs   |
| [docs/persistent-context.md](docs/persistent-context.md)       | Persistent context, workspace files, and archived session snapshots        |
| [docs/memory.md](docs/memory.md)                               | Long-term memory: extractions, digests, tasks, budget, mirror, Memory UI   |
| [docs/sandbox.md](docs/sandbox.md)                             | Docker/Kubernetes sandboxes, proxy behavior, and exec-scoped tunnels       |
| [docs/sessions-and-channels.md](docs/sessions-and-channels.md) | Session lifecycle, session controls, Matrix behavior, and approvals        |
| [docs/compaction.md](docs/compaction.md)                       | Session compaction: `/compact`, fold/tool strategies, agent view           |
| [docs/chatgpt-subscription.md](docs/chatgpt-subscription.md)   | Per-user ChatGPT subscription (`openai-codex`) models and login flow       |
| [docs/kubernetes.md](docs/kubernetes.md)                       | Kubernetes runtime, StatefulSet sandboxes, and Helm deployment             |

## Kubernetes Deployment

carapace supports Kubernetes as a sandbox runtime. Sandboxes run as StatefulSets with per-session PVCs. On idle timeout the StatefulSet scales to zero while preserving persistent state, and on resume the sandbox is recreated with its committed knowledge and activated setup restored. If `CARAPACE_SANDBOX_WARM_POOL_SIZE` is greater than `0`, the server also maintains a generic base-image warm pool and can claim one of those sandboxes for a new session instead of paying the full cold-start path.

Use the included Helm chart in [charts/carapace](charts/carapace) and see [charts/carapace/README.md](charts/carapace/README.md) for installation details.

## Development

```bash
nix develop
uv sync --dev
uv run pytest
pnpm --dir frontend install
pnpm --dir frontend lint
```

For local development without Docker Compose:

```bash
docker build -t carapace-sandbox:local sandbox
CARAPACE_SANDBOX_BASE_IMAGE=carapace-sandbox:local uv run carapace-server
pnpm --dir frontend dev
uv run carapace
```

The dev shell supplies Python 3.14, uv, Node.js 24, pinned pnpm, Helm, and Skopeo. See [docs/development.md](docs/development.md) for host services, sandboxed checks, image builds, and dependency refreshes.

### Brand assets

The organic turtle in `docs/assets/icon.svg` is the canonical mark. The wordmark is
Fraunces SemiBold (weight 600, optical size 9, softness 0, wonk 1), with -0.043 em
tracking. Logo and wordmark SVGs contain outlined letters, so the app and README
need no font download. In both light and dark lockups, the turtle's feet align with
the wordmark baseline, leaving the `p` descender below. Personalized agent names
and icons remain independent of the product branding.

To regenerate the SVG assets, download the upright variable
[Fraunces font](https://github.com/google/fonts/tree/main/ofl/fraunces)
(SIL Open Font License), then run:

```bash
uv run frontend/scripts/generate_brand.py '/path/to/Fraunces[SOFT,WONK,opsz,wght].ttf'
pnpm --dir frontend generate:favicon
pnpm --dir frontend generate:pwa-icons
```

The raster commands require ImageMagick. Generated app icons live in
`frontend/public/`; keeping them out of Next.js file-convention metadata lets
per-user agent icons control the browser tab.

## Contributing

Issues and pull requests are welcome. Before opening a PR, run the relevant Nix checks and runtime smoke. The repo uses `prek` hooks; CI verifies Linux x64 images without registry write access, then a trusted workflow publishes the verified archives and chart.

## License

MIT. See [LICENSE](LICENSE).
