# CHANGELOG


## v0.155.1 (2026-08-27)


### Other


- Merge pull request #276 from thiesgerken/renovate/pnpm
  ([`f1dd98e`](https://github.com/thiesgerken/carapace/commit/f1dd98e009afbe50de97081c98374ba7ef9fe35a))

- Merge pull request #274 from thiesgerken/renovate/all-routine-dependencies
  ([`0f527dc`](https://github.com/thiesgerken/carapace/commit/0f527dc3fb26d74a6b1510ea0969865a60ce11c7))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.24.0
  ([`f1dd98e`](https://github.com/thiesgerken/carapace/commit/f1dd98e009afbe50de97081c98374ba7ef9fe35a))

- ⬆️ chore: upgrade pnpm to 11.24.0
  ([`b577c0c`](https://github.com/thiesgerken/carapace/commit/b577c0cca32cec95bf63bea5a0371c4ce008f7ad))

- ⬆️ chore: upgrade traefik:v3.7 Docker digest to ef751c6
  ([`0f527dc`](https://github.com/thiesgerken/carapace/commit/0f527dc3fb26d74a6b1510ea0969865a60ce11c7))

- ⬆️ chore: upgrade traefik:v3.7 Docker digest to ef751c6
  ([`d9a28cf`](https://github.com/thiesgerken/carapace/commit/d9a28cf847135ba0255bf35d4538539ee40dad7c))

## v0.155.0 (2026-08-26)


### ✨ Features


- ✨Merge pull request #269 from thiesgerken/feature/mermaid
  ([`0b762e5`](https://github.com/thiesgerken/carapace/commit/0b762e54c03d1d02e021eef1a51b43bb3cbdaabc))

- ✨ feat: Mermaid diagram rendering + bundled mermaid skill
  ([`0b762e5`](https://github.com/thiesgerken/carapace/commit/0b762e54c03d1d02e021eef1a51b43bb3cbdaabc))

### Other


- fix(ui): correct mermaid render lifecycle, download and security docs
  ([`6449b37`](https://github.com/thiesgerken/carapace/commit/6449b37dad8d68281422c120a094d701964ab672))

  Review findings from #269:

  - mermaid.render() removes any element carrying the id it is handed, so a
    fixed per-component id let concurrent renders (the undefined -> resolved
    theme transition on mount, and every token while streaming) delete each
    other's containers, and let a repeat render rip out the already-injected
    SVG. Every invocation now gets a fresh id and renders are serialized.
  - suppressErrorRendering keeps a failed draw from pinning its error graphic
    to document.body.
  - The whole async body is inside the queue's catch, so a failed chunk load
    surfaces as an error instead of an unhandled rejection.
  - The download anchor is attached to the document and the object URL is
    revoked in a later tick; revoking in the same tick aborts the download in
    Safari and Firefox.
  - securityLevel "strict" sanitizes the SVG with DOMPurify and blocks click
    callbacks, but does not disable HTML labels — corrected in the code
    comment, SKILL.md, flowchart.md and styling.md.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- feat(ui): render mermaid diagrams, add bundled mermaid skill
  ([`aba592c`](https://github.com/thiesgerken/carapace/commit/aba592c89751b76435bef1409228927229c9a126))

  Fenced ```mermaid blocks now render as diagrams in the web UI (chat, tool output, knowledge browser). A rehype plugin rewrites the fence into a `data-mermaid` div before rehype-pretty-code can turn it into Shiki spans; the diagram component lazy-loads mermaid, so nothing is added to the initial bundle.

  While a reply streams, the fence is still incomplete and `mermaid.parse` fails — the component keeps showing the source instead of an error, and flips to the diagram once it parses. Rendering uses securityLevel "strict" since the source is LLM output. Each diagram gets a toolbar: source toggle, copy (source or SVG, depending on the view), and SVG download.

  The bundled `mermaid` skill teaches the agent when a diagram is worth drawing and how to write one that renders here, with per-type syntax references next to SKILL.md.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

## v0.154.3 (2026-08-26)


### Other


- Merge pull request #272 from thiesgerken/renovate/pnpm
  ([`107b3ad`](https://github.com/thiesgerken/carapace/commit/107b3adfc04fb3a20fc39f3425ae1c2db4c1775e))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.23.0
  ([`107b3ad`](https://github.com/thiesgerken/carapace/commit/107b3adfc04fb3a20fc39f3425ae1c2db4c1775e))

- ⬆️ chore: upgrade pnpm to 11.23.0
  ([`fea1f65`](https://github.com/thiesgerken/carapace/commit/fea1f6594bf84e3fc83bf6cbebcde65d8543e747))

## v0.154.2 (2026-08-26)


### Other


- Merge pull request #268 from thiesgerken/renovate/all-routine-dependencies
  ([`9da980f`](https://github.com/thiesgerken/carapace/commit/9da980f42c9d3af7ab8552d343d6fa3f8400cb41))

- Merge pull request #271 from thiesgerken/pnpm-automerge
  ([`5e8f83e`](https://github.com/thiesgerken/carapace/commit/5e8f83e8c5acabdd716a459b0135ec93571294d8))

  Automerge pnpm minor and patch updates

- Automerge pnpm minor and patch updates
  ([`f87fe41`](https://github.com/thiesgerken/carapace/commit/f87fe41f5c0f753f6988f330b97637167cb28b9d))

  pnpm ships a minor every couple of weeks and the bumps are routine, so they were arriving as review-and-click PRs for no gain. The groupName also splits them out of the grouped update PR, which otherwise blocks automerge on every other dep in the group being automergeable too.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`9da980f`](https://github.com/thiesgerken/carapace/commit/9da980f42c9d3af7ab8552d343d6fa3f8400cb41))

- ⬆️ chore: upgrade all routine dependency updates
  ([`08eb5fa`](https://github.com/thiesgerken/carapace/commit/08eb5fa37bc40027cb6c07f32c05834b87002cdb))

## v0.154.1 (2026-08-25)


### Other


- Merge pull request #264 from jkuball/fix/persist-chat-drafts
  ([`8af70b2`](https://github.com/thiesgerken/carapace/commit/8af70b24f38e33d2fe6b1d4b8ed67a0f2a7c80ce))

- Merge branch 'main' into fix/persist-chat-drafts
  ([`e89a682`](https://github.com/thiesgerken/carapace/commit/e89a6820fa8c87cc51f21592d8fe940c3d40ac32))

### 🐛 Bug Fixes


- 🐛 fix: persist chat drafts per session
  ([`8af70b2`](https://github.com/thiesgerken/carapace/commit/8af70b24f38e33d2fe6b1d4b8ed67a0f2a7c80ce))

## v0.154.0 (2026-08-25)


### Other


- Merge pull request #267 from thiesgerken/fix/pin-gitpython
  ([`4e3ddc5`](https://github.com/thiesgerken/carapace/commit/4e3ddc559518b61e2e8cbae1861a6794836818b3))

- Merge branch 'main' into fix/persist-chat-drafts
  ([`528a605`](https://github.com/thiesgerken/carapace/commit/528a605123467bedb113ded3035034398e093729))

- Merge pull request #254 from thiesgerken/renovate/lock-file-maintenance
  ([`4deef5e`](https://github.com/thiesgerken/carapace/commit/4deef5ecd46a47b392bed522792a57fbaefbd67b))

- Merge pull request #263 from thiesgerken/worktree-agent-icon
  ([`5bbf992`](https://github.com/thiesgerken/carapace/commit/5bbf9923bd0c0fb8435b95a13aafa2d476f4e790))

- Merge branch 'main' into fix/persist-chat-drafts
  ([`ea406b8`](https://github.com/thiesgerken/carapace/commit/ea406b83c4fd19fc1835e5530b964bdeedfc6f42))

- Merge pull request #265 from thiesgerken/renovate/all-routine-dependencies
  ([`dfd2cef`](https://github.com/thiesgerken/carapace/commit/dfd2ceff72ea77b6aabe65930c2f70ef7ee6c6b0))

### 🐛 Bug Fixes


- 🐛 fix: pin gitpython below 3.1.60 for semantic release
  ([`4e3ddc5`](https://github.com/thiesgerken/carapace/commit/4e3ddc559518b61e2e8cbae1861a6794836818b3))

- 🐛 fix: pin gitpython below 3.1.60 for semantic release
  ([`63b879d`](https://github.com/thiesgerken/carapace/commit/63b879db19a44bf211eb86e5af1d41ba885fd3a4))

  GitPython 3.1.60 removed Actor.name_email_regex, which python-semantic-release 10.6.1 still uses to validate commit_author, so every release run has failed at config load since that release.

  The psr action builds its image with an unpinned `gitpython ~= 3.0` and offers no way to constrain it, so run the CLI through uv instead, where the constraint fits. psr writes the job outputs itself, so `released` and `version` keep working.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 🐛 fix: accept flag emoji as agent icons and bound the value
  ([`8aa8b30`](https://github.com/thiesgerken/carapace/commit/8aa8b30715d4a8ecd9d7bdf496de16f3968937f3))

  A flag is two regional indicators, which the emoji counter read as two separate emoji, so bundled flags were rejected by the API even though the input field offered them. Treat the second indicator as continuing the first.

  Also bound the length: joiners only re-armed the continuation flag, so a single emoji padded with them counted as one and was stored verbatim. The error message now states what is actually enforced — whether an emoji has a bundled asset is still not checked here.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 🐛 fix: apply the agent name and icon without a reload
  ([`d987ec8`](https://github.com/thiesgerken/carapace/commit/d987ec8549ba916d0745d6c0bde553292c9ad19d))

  Three review findings:

  - The shell only fetched /auth/me on connect, so the sidebar and favicon kept
    the pre-save values until F5. Expose a refresh and call it after saving.
  - agent_icon was clamped only by the input field, so the API stored arbitrary
    text verbatim. Reject anything that is not exactly one emoji, counting a ZWJ
    sequence, keycap or skin tone modifier as part of its base.
  - icon.svg was still an app/ file convention, so its rel="icon" link only
    stayed away because metadata.icons was non-empty. Move it to public/ next to
    favicon.ico, which makes the single-declaration comment structural.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 🐛 fix: make the agent icon the only favicon declaration
  ([`503e4a3`](https://github.com/thiesgerken/carapace/commit/503e4a3663dd6bf131c931268465d11d69058fff))

  The sidebar rendered the custom emoji while the tab kept the default, because the auto-emitted favicon.ico link competed with the one carrying the agent icon and browsers pick between them by their own rules. Move favicon.ico to public/ so no link is emitted for it — it still serves as the implicit /favicon.ico — and own the remaining link outside React.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 🐛 fix: use the agent name in every document title
  ([`9781467`](https://github.com/thiesgerken/carapace/commit/9781467a9b330fbce1ba18347d9158c0fc9f5568))

  Four routes set document.title independently, all hardcoding the product name, so the chat, settings and knowledge views overwrote whatever the app shell had put there. Route them through a shared useBrand() hook instead of re-asserting the title from the layout, which could never win the race.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 🐛 fix: render the favicon link through React
  ([`1a44df8`](https://github.com/thiesgerken/carapace/commit/1a44df8c35465d5cbce3b5c2aca3fa757df6fb01))

  Removing the metadata icon links imperatively deleted DOM nodes React owns, crashing its commit phase with "finishedRoot.parentNode is null". Render the link from the app shell instead and let React hoist it, and drop the static icon declarations so the per-user one is the only rel="icon" candidate besides the .ico fallback.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 🐛 fix: keep the default favicon links when no agent icon is set
  ([`1c0bfe7`](https://github.com/thiesgerken/carapace/commit/1c0bfe792b3f55727339b56248734f3d55d98dac))

  Stripping every icon link unconditionally also dropped the .ico and PNG fallbacks for users on the default, so only take over once a custom icon resolves — and keep the override afterwards so clearing it does not leave the stale emoji in place.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

### ⬆️ Dependencies


- ⬆️ chore: Lock file maintenance
  ([`4deef5e`](https://github.com/thiesgerken/carapace/commit/4deef5ecd46a47b392bed522792a57fbaefbd67b))

- ⬆️ chore: Lock file maintenance
  ([`0aad6b6`](https://github.com/thiesgerken/carapace/commit/0aad6b6418c5b9dc14cb43cd2d310f0151d07685))

- ⬆️ chore: relock backend dependencies
  ([`1d6659c`](https://github.com/thiesgerken/carapace/commit/1d6659c0f591ee2d43d1f743d817d8a7942dda3b))

  anthropic 1.0.0 dropped httpx support and now rejects any http_client that is not an httpx2.AsyncClient, so retry_http_client() moves to httpx2 plus AsyncHTTPX2TenacityTransport (also clears the pydantic-ai v3 deprecation warnings on the OpenAI/OpenRouter providers).

  pydantic-ai 2.34 adds SpeechPart to the response-part union; token counting handles it via its transcript.

  Notable bumps: anthropic 0.117->1.0, openai 2.46->3.3, pydantic-ai 2.13->2.34, starlette 1.3->1.6, cryptography 49->50, fastapi 0.139->0.141, ruff 0.15->0.16 (new RUF036 fix in model_selection.py).

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- ⬆️ chore: upgrade all routine dependency updates
  ([`dfd2cef`](https://github.com/thiesgerken/carapace/commit/dfd2ceff72ea77b6aabe65930c2f70ef7ee6c6b0))

- ⬆️ chore: upgrade all routine dependency updates
  ([`a81d9e4`](https://github.com/thiesgerken/carapace/commit/a81d9e41eb0509fd66c029aff50b9b9d03c087d5))

### ✨ Features


- ✨ feat: custom agent icon; keep tab title on navigation
  ([`5bbf992`](https://github.com/thiesgerken/carapace/commit/5bbf9923bd0c0fb8435b95a13aafa2d476f4e790))

- ✨ feat: custom agent icon; keep tab title on navigation
  ([`fcc7da3`](https://github.com/thiesgerken/carapace/commit/fcc7da3f288a4c7014d1f18cfc71844be0642e5d))

  Adds a per-user `agent_icon` setting (a single emoji) that drives the favicon and the sidebar logo, resolved against the already-bundled twemoji assets.

  Also fixes the tab title falling back to "carapace": Next re-applies the static route metadata on every client-side navigation, so the effect has to depend on the pathname too.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- ✨⬆️Merge pull request #266 from thiesgerken/chore/relock-backend-deps
  ([`5a18f8a`](https://github.com/thiesgerken/carapace/commit/5a18f8ab882ed42d5f3ee91125acb31b62a30579))

- ✨⬆️ chore: relock backend dependencies
  ([`5a18f8a`](https://github.com/thiesgerken/carapace/commit/5a18f8ab882ed42d5f3ee91125acb31b62a30579))

### 💄 UI/UX


- 💄 feat: keep the product identity in platform administration
  ([`741614a`](https://github.com/thiesgerken/carapace/commit/741614a8cf06c5c6ff1b3a111c6d9b921880293a))

  The platform model and user views administer the deployment rather than the user's own agent, so the tab there shows the carapace name and turtle. The sidebar resolves its own icon so it keeps showing the agent on every route.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 💄 feat: preview and clamp the agent icon input
  ([`fedfab4`](https://github.com/thiesgerken/carapace/commit/fedfab4df68a25cc0d03a6acc7ed35ec5aa44501))

  The icon only renders if it resolves to a bundled emoji SVG, so show the resolved asset next to the field (dimmed default when it does not resolve) and drop non-emoji input instead of storing a value that silently falls back.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

## v0.153.3 (2026-08-25)


### Other


- Merge pull request #260 from thiesgerken/renovate/all-routine-dependencies
  ([`40737e1`](https://github.com/thiesgerken/carapace/commit/40737e167c90573016620b275b83fa71f20d750b))

### ⬆️ Dependencies


- ⬆️ chore: upgrade docker.io/library/nginx:1.31.4 Docker digest to 0d4374c
  ([`40737e1`](https://github.com/thiesgerken/carapace/commit/40737e167c90573016620b275b83fa71f20d750b))

- ⬆️ chore: upgrade docker.io/library/nginx:1.31.4 Docker digest to 0d4374c
  ([`08c6f6d`](https://github.com/thiesgerken/carapace/commit/08c6f6d17a19d72dbdb6129b434d181d836040ba))

### 🐛 Bug Fixes


- 🐛 fix: address review findings on chat draft persistence
  ([`3171b23`](https://github.com/thiesgerken/carapace/commit/3171b23352b874ac6cdf4c05baf75470046a91b7))

  - resize the textarea on mount so a restored multi-line draft is not
    rendered one line tall until the next keystroke
  - guard the draft helpers against a throwing sessionStorage, since they
    now run on every keystroke rather than once
  - assert on the store directly in the test, getChatDraft cannot tell a
    stored empty string from a missing key
  - note why ChatView is keyed by session id

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 🐛 fix: persist chat drafts per session
  ([`db1ac97`](https://github.com/thiesgerken/carapace/commit/db1ac97c121aba4a3a4b61701e3818450ebc0f30))

## v0.153.2 (2026-08-24)


### 🐛 Bug Fixes


- 🐛Merge pull request #262 from thiesgerken/fix/261-lazy-model-construction
  ([`89be0f9`](https://github.com/thiesgerken/carapace/commit/89be0f9c24a820c5093d0dc68208860200af7fa5))

- 🐛 fix: start server without provider credentials
  ([`89be0f9`](https://github.com/thiesgerken/carapace/commit/89be0f9c24a820c5093d0dc68208860200af7fa5))

- 🐛 fix: cache the lazily built default agent model
  ([`0a905e6`](https://github.com/thiesgerken/carapace/commit/0a905e65ff1a413bb6b639ba4802c73a0abe144d))

  _build_deps runs once per turn and the default branch cached nowhere, so every message built a fresh provider client (each with its own httpx.AsyncClient) that was never closed. Store the first resolve on the engine; apply_platform_model_config still replaces it when an admin edits the catalog.

  Also mark the ANTHROPIC_API_KEY line in the Kubernetes quick start as the optional part, instead of contradicting the command below it.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- 🐛 fix: start server without provider credentials
  ([`6970a72`](https://github.com/thiesgerken/carapace/commit/6970a724646dd9503c2a19a6fe196a946ae27fdc))

  A fresh install crash-looped when no ANTHROPIC_API_KEY was set: the lifespan eagerly built the default agent model before an admin could configure another provider. Drop the eager construction (SessionEngine already resolves lazily), and fall back to a placeholder key when a provider refuses to construct without one, so keyless Anthropic-compatible endpoints work and a genuinely missing key fails as a provider auth error on the first request instead of at startup.

  Closes #261

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

### Other


- ✅ test: cover server startup without provider credentials
  ([`a836689`](https://github.com/thiesgerken/carapace/commit/a8366899cdbfa861032f1c4e51e9232cdf16681b))

  Extract the lifespan stub harness into a helper and add a second case that runs the real model factory with ANTHROPIC_API_KEY unset, asserting the lifespan completes and hands SessionEngine no eagerly-built model.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

## v0.153.1 (2026-08-22)


### Other


- Merge pull request #252 from thiesgerken/renovate/all-routine-dependencies
  ([`6aba338`](https://github.com/thiesgerken/carapace/commit/6aba33869c6d62c3aa6cc46d7464131a34695cac))

- Merge pull request #256 from thiesgerken/renovate/jsdom-30.x
  ([`a679def`](https://github.com/thiesgerken/carapace/commit/a679def7c31e04d4f3ccd6bfbab59d83a3993be5))

- Merge pull request #253 from thiesgerken/renovate/pnpm-11.x
  ([`740b413`](https://github.com/thiesgerken/carapace/commit/740b413a0b9581e5391c46ce5a1eb351ef328abd))

- Merge pull request #257 from thiesgerken/renovate/j178-prek-action-3.x
  ([`4131056`](https://github.com/thiesgerken/carapace/commit/4131056fb90984bd42c5a2101583adf916c87906))

- Merge pull request #259 from thiesgerken/renovate/astral-sh-setup-uv-10.x
  ([`544a192`](https://github.com/thiesgerken/carapace/commit/544a19222c53badac6425baf5bed690ed9087ceb))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`6aba338`](https://github.com/thiesgerken/carapace/commit/6aba33869c6d62c3aa6cc46d7464131a34695cac))

- ⬆️ chore: upgrade all routine dependency updates
  ([`9b047df`](https://github.com/thiesgerken/carapace/commit/9b047df3392e6fca282d0ee9b4e6fd41b0149858))

- ⬆️ chore: upgrade jsdom to 30.0.1
  ([`a679def`](https://github.com/thiesgerken/carapace/commit/a679def7c31e04d4f3ccd6bfbab59d83a3993be5))

- ⬆️ chore: upgrade jsdom to 30.0.1
  ([`7f93207`](https://github.com/thiesgerken/carapace/commit/7f93207e8cc5010333ff736952fc246e70b621ab))

- ⬆️ chore: upgrade pnpm to 11.22.0
  ([`740b413`](https://github.com/thiesgerken/carapace/commit/740b413a0b9581e5391c46ce5a1eb351ef328abd))

- ⬆️ chore: upgrade pnpm to 11.22.0
  ([`5dedf73`](https://github.com/thiesgerken/carapace/commit/5dedf73cad0cfa27a9cef162b4a091cf2197aaff))

- ⬆️ chore: upgrade j178/prek-action action to v3.0.0
  ([`4131056`](https://github.com/thiesgerken/carapace/commit/4131056fb90984bd42c5a2101583adf916c87906))

- ⬆️ chore: upgrade j178/prek-action action to v3.0.0
  ([`ee25c05`](https://github.com/thiesgerken/carapace/commit/ee25c056c5a293c2b680e2a5990b0a3da2db3c9d))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v10.0.1
  ([`544a192`](https://github.com/thiesgerken/carapace/commit/544a19222c53badac6425baf5bed690ed9087ceb))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v10.0.1
  ([`63a452c`](https://github.com/thiesgerken/carapace/commit/63a452c447c87a259fe6740c3018c8360a05e84e))

## v0.153.0 (2026-08-01)


### ✨ Features


- ✨Merge pull request #258 from thiesgerken/feat/disable-models
  ([`8b2e62c`](https://github.com/thiesgerken/carapace/commit/8b2e62c47ebdf5ef6b53708cb6753f41a397a8b3))

- ✨ feat: disable individual models
  ([`8b2e62c`](https://github.com/thiesgerken/carapace/commit/8b2e62c47ebdf5ef6b53708cb6753f41a397a8b3))

- ✨ feat: disable individual models
  ([`ea7e432`](https://github.com/thiesgerken/carapace/commit/ea7e4329f0ca249db2a6022b040ea84692b3754b))

  Adds an `enabled` flag to the model catalog (default true, so new and existing rows stay enabled). Disabled models are hidden from every picker — /api/models, user settings, the /models command, and the admin default-model pickers — and rejected at inference time.

  No silent fallback: a session whose agent/sentinel/title/compaction override points at a disabled model fails the turn with "agent model 'x' is disabled — select another model" instead of quietly switching to the platform default. Enforced both at turn start (assert_models_enabled, since only the agent model is re-resolved per turn) and in resolve_available_model_entry, which every model creation goes through.

  Platform defaults cannot be disabled: AgentConfig rejects the save, so the admin sees the error instead of every session breaking.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

### Other


- 🌐 i18n(frontend): clarify model enabled hint
  ([`1658ee2`](https://github.com/thiesgerken/carapace/commit/1658ee2334cd756cf76de26192b16d42d9b81981))

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

## v0.152.0 (2026-07-24)


### ✨ Features


- ✨ feat: customizable per-user agent name
  ([`69a1af5`](https://github.com/thiesgerken/carapace/commit/69a1af556331e4b57ab0d05f3c7d71b539056e83))

  Adds an optional agent name in user preferences (stored on UserConfig). When set, it replaces "carapace" in the browser tab title, sidebar brand, mobile header, chat empty state, and message-box placeholder. Flows to the frontend via /auth/me config, so no extra request app-wide. Empty falls back to the default brand.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.151.0 (2026-07-21)


### ✨ Features


- ✨ feat(frontend): open duplicated model rows and suffix their name
  ([`c1893f3`](https://github.com/thiesgerken/carapace/commit/c1893f355db05ae40c68d3c1a451230a2432ef1a))

  Copies now land as "<name> (copy)" (and "<id> (copy)" when the id is explicit) and start expanded so they are ready to edit.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(frontend): copy name and id when duplicating a model
  ([`58c37ba`](https://github.com/thiesgerken/carapace/commit/58c37bad0f9c38c7f0b0da0ceaebb91246631b34))

  Keeps the duplicate collapsed like any other row instead of forcing an expanded incomplete draft; only the stored secret is dropped.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(frontend): duplicate button for platform models
  ([`11e262c`](https://github.com/thiesgerken/carapace/commit/11e262ca85e1c7f041f8aee24c3fd690072292e2))

  Clones a model row into a new unsaved draft at the top of the catalog, clearing name/id/secret so it opens expanded and cannot collide with the source id.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### Other


- remove worktrees
  ([`8720780`](https://github.com/thiesgerken/carapace/commit/87207807308c8b05a6300fc67eda1d87db24053b))

## v0.150.2 (2026-07-21)


### Other


- Merge remote-tracking branch 'origin/main'
  ([`8896a62`](https://github.com/thiesgerken/carapace/commit/8896a62ab60c21259288f31e5125a5b03dcdf3a2))

## v0.150.1 (2026-07-21)


### 💄 UI/UX


- 💄 fix(frontend): clean rendering for skill MCP tool-call rows
  ([`cf2a491`](https://github.com/thiesgerken/carapace/commit/cf2a49181fdf6126ef5d2e8296c5b74526e4007f))

  MCP calls arrive as `mcp:<server>:<tool>` with the gate's internal args (url/skill/server/tool) mirrored in. The row dumped all of that raw. Now it shows a Plug icon, a `<server> · <tool>` label, and summarizes only the actual tool arguments (args.args).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛 fix(knowledge): distinguish unconfigured vault backend from missing secret
  ([`6868942`](https://github.com/thiesgerken/carapace/commit/6868942477c209b981a1f10175e7cc48a203fbcb))

  The skill viewer showed a red "absent" X for every vault_path when the file credential backend was disabled (CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND unset), falsely implying the secret was missing. _resolve now raises UnknownBackendError (KeyError subclass) for an unregistered/disabled backend; resolve_vault_status maps it to a new muted "unconfigured" status instead of "absent".

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.150.0 (2026-07-21)


### ✨ Features


- ✨Merge pull request #250 from thiesgerken/feature/skill-mcp-vault-status
  ([`5d2c18f`](https://github.com/thiesgerken/carapace/commit/5d2c18fca61a5ca8e8c5cbbb096cddee3d4b7839))

- ✨ feat(knowledge): vault-presence status + OAuth provisioning hint in the viewer
  ([`5d2c18f`](https://github.com/thiesgerken/carapace/commit/5d2c18fca61a5ca8e8c5cbbb096cddee3d4b7839))

- ✨ feat(knowledge): vault-presence status for skill secret refs
  ([`01b7dd9`](https://github.com/thiesgerken/carapace/commit/01b7dd922c797e95063ffaaf45ec31bdad831d7e))

  The knowledge viewer now shows, per secret a skill references (credential vault_paths + MCP auth vault_paths), whether it exists in the user's vault: a green check (present), red cross (absent), or muted alert (vault unreachable). Lookup is metadata-only (never values), one fetch_metadata per ref, and best-effort — a down vault never blocks browsing.

  For OAuth MCP servers whose token isn't present, the card shows a short provisioning hint pointing at scripts/mcp_oauth_blob.py (the deferred interactive "populate" button's stand-in).

  - browse endpoint enriches skill listings with vault_status via the
    per-user credential registry
  - knowledge-view renders a VaultBadge next to each ref + oauth hint
  - en/de strings; TS gains SkillMcpOAuthAuth

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨Merge pull request #249 from thiesgerken/feature/skill-mcp-oauth
  ([`754fac0`](https://github.com/thiesgerken/carapace/commit/754fac040f4b59cf943f76bccb127fea984f508e))

- ✨ feat(skills): OAuth auth for MCP servers + vault write-back
  ([`754fac0`](https://github.com/thiesgerken/carapace/commit/754fac040f4b59cf943f76bccb127fea984f508e))

- ✨ feat(skills): OAuth auth for MCP servers + vault write-back
  ([`e170878`](https://github.com/thiesgerken/carapace/commit/e17087805311dfe39699b2281d36e17ba5d59970))

  Add `type: oauth` to skill MCP auth. The vault entry holds a JSON OAuth state blob; carapace injects the access token, refreshes it via the refresh-token grant when missing / near expiry / rejected (401), and writes the rotated blob back to the vault.

  - VaultBackend gains write(); implemented for Bitwarden (read-modify-write
    the item's login password via bw serve PUT) and the file backend
    (.env line-edit / YAML round-trip). Registry + session view route it.
  - _VaultOAuth (httpx.Auth): proactive refresh + 401 retry + write-back,
    guarded by a lock; prewarm() surfaces auth errors at activation.
  - Graceful degradation: use_skill now eagerly connects/enumerates each
    declared MCP server and reports per-server status; a failing server no
    longer aborts activation — the skill loads and the agent is told which
    <server>_* tools are unavailable and why. Shared _build_one_mcp_toolset
    backs both activation prewarm and the dynamic-toolset factory.
  - scripts/mcp_oauth_blob.py assembles the blob; docs/skills.md documents
    the oauth variant, out-of-band bootstrap, and write-back requirement.

  Initial authorization (DCR+PKCE browser login) stays out-of-band; carapace only refreshes. Bitwarden write path needs validation against a live bw serve.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### Other


- Merge branch 'feature/skill-mcp-oauth' into feature/skill-mcp-vault-status
  ([`b025f3c`](https://github.com/thiesgerken/carapace/commit/b025f3c16e35bfaf775b55dac9f11e830735afb9))

- Merge branch 'feature/skill-mcp-stdio-bridge' into feature/skill-mcp-oauth
  ([`2932efa`](https://github.com/thiesgerken/carapace/commit/2932efae15d32a9147eec38501d73495eb420b7c))

  # Conflicts: #	src/carapace/agent/tools.py

## v0.149.0 (2026-07-21)


### ✨ Features


- ✨Merge pull request #247 from thiesgerken/feature/skill-mcp-stdio-bridge
  ([`c6c0f0a`](https://github.com/thiesgerken/carapace/commit/c6c0f0a1c1ac5852d3e9ece8e00706adb39d96c4))

- ✨ feat(skills): stdio MCP servers via an in-sandbox bridge
  ([`c6c0f0a`](https://github.com/thiesgerken/carapace/commit/c6c0f0a1c1ac5852d3e9ece8e00706adb39d96c4))

- ✨ feat(skills): stdio MCP servers via an in-sandbox bridge
  ([`104def2`](https://github.com/thiesgerken/carapace/commit/104def21c930b6275fa9e573c7857d1c7a7c9447))

  Skills can now declare stdio MCP servers (metadata.carapace.mcp with `command` instead of `url`). The server process runs inside the sandbox, spawned once per operation (enumerate at activation, one spawn per call) by a baked-in `carapace-mcp-bridge` — stateless, matching mcp2cli's process model, so nothing about the sandbox's concurrency/lifecycle model changes.

  Unlike driving mcp2cli through a shell alias, tools are registered as real typed pydantic-ai tools built from the server's own JSON Schemas (Tool.from_schema), which fixes the agent's discovery/understanding struggles. Skills that need OAuth, stateful sessions, or custom output shaping can still wrap a server with mcp2cli + a command alias.

  - SkillMcpDecl: url (HTTP) xor command (stdio); stdio servers inherit
    the skill's context-injected credentials, so `auth` is HTTP-only
  - bridge speaks MCP over stdio (mcp SDK), emits a marked JSON envelope
    recoverable from merged stderr; args/server passed base64
  - each call gated by the sentinel as mcp:<server>:<tool>; oversized
    results spill to file — shared with the HTTP path
  - exec credential/domain/tunnel injection factored into
    _collect_context_injection, reused by the bridge
  - knowledge viewer + use_skill badge render stdio decls
  - sandbox image: dedicated /opt/carapace-mcp venv + bridge script

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨Merge pull request #244 from thiesgerken/feature/skill-mcp-connections
  ([`719037d`](https://github.com/thiesgerken/carapace/commit/719037d9f999905f2e1c95f36617cd54f2519112))

- ✨ feat(skills): declare MCP server connections in skill metadata
  ([`719037d`](https://github.com/thiesgerken/carapace/commit/719037d9f999905f2e1c95f36617cd54f2519112))

- ✨ feat(knowledge): render skill MCP servers in the knowledge viewer
  ([`bf68450`](https://github.com/thiesgerken/carapace/commit/bf68450709081a5bdea3ad1e2a4482d72bf75258))

  The viewer already serves the full SkillCarapaceConfig, so mcp entries flow through automatically — add the TS type, a Plug-icon section (name, url, auth type + vault path), and en/de labels.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(skills): declare MCP server connections in skill metadata
  ([`1ea0f43`](https://github.com/thiesgerken/carapace/commit/1ea0f430a8772a9e18db7c299d6203ead33a19e9))

  Skills can now declare MCP servers under metadata.carapace.mcp. While a skill is active, each server's tools are exposed to the agent as regular tools named <server>_<tool>, backed by pydantic-ai's MCPToolset over streamable HTTP.

  - declared servers are part of the use_skill approval (gate payload,
    context grant, sentinel action log, frontend badge)
  - every MCP tool call routes through the sentinel gate with the usual
    escalate-to-user path, shown as mcp:<server>:<tool>
  - oversized text results spill to a sandbox file like exec output
  - bearer-token auth reads from the vault (auth is a tagged union so
    oauth can be added later); tokens cache in the session credential
    cache and re-fetch on miss

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Other


- Merge branch 'feature/skill-mcp-connections' into feature/skill-mcp-stdio-bridge
  ([`8dda728`](https://github.com/thiesgerken/carapace/commit/8dda728be04857b6ec7db4887209c0a422ffa3aa))

  # Conflicts: #	src/carapace/agent/tools.py

- 🔀 Merge main into feature/skill-mcp-connections
  ([`832b334`](https://github.com/thiesgerken/carapace/commit/832b3340457ac14871b5e5f8cb9e0dca4f395ee1))

### 🐛 Bug Fixes


- 🐛 fix(agent): narrow MCP decl url for pyrefly
  ([`5aabf9f`](https://github.com/thiesgerken/carapace/commit/5aabf9fc9321f158339834ef6a6b12d381264a9f))

  Making url optional (str | None) for the stdio transport tripped pyrefly at the HTTP MCPToolset(decl.url, ...) call. Branch on command/url directly so the type checker narrows url to str in the HTTP arm.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix(skills): honest MCP activation status + reject duplicate MCP names
  ([`cc60bee`](https://github.com/thiesgerken/carapace/commit/cc60bee0bd95a5f54ede1477f3089d2d6d0bbabc))

  Addresses two review findings:

  - use_skill no longer unconditionally claims MCP tools are available. It
    now eagerly connects each declared server at activation and reports
    per-server status; a server whose bearer token can't be resolved (or
    that can't be built) is reported UNAVAILABLE instead of falsely
    promised, and activation still succeeds (graceful degradation).
  - Reject activating a skill whose MCP server name is already registered
    by another active skill — tool names are prefixed by name only, so a
    collision would shadow a different server. Mirrors the existing command
    alias conflict check.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.148.4 (2026-07-21)


### Other


- Merge pull request #248 from thiesgerken/renovate/pnpm-11.x
  ([`8bdf9ae`](https://github.com/thiesgerken/carapace/commit/8bdf9aeec73386587037e769a2fb4be0ffbf698a))

- Merge pull request #251 from thiesgerken/renovate/astral-sh-setup-uv-9.x
  ([`fb9b4d5`](https://github.com/thiesgerken/carapace/commit/fb9b4d5aff2b0239e4a668434f29af9139e4beef))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.15.0
  ([`8bdf9ae`](https://github.com/thiesgerken/carapace/commit/8bdf9aeec73386587037e769a2fb4be0ffbf698a))

- ⬆️ chore: upgrade pnpm to 11.15.0
  ([`dcfed24`](https://github.com/thiesgerken/carapace/commit/dcfed244f07e56c2dde3ae8d786351b52a0fbce1))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v9.0.0
  ([`fb9b4d5`](https://github.com/thiesgerken/carapace/commit/fb9b4d5aff2b0239e4a668434f29af9139e4beef))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v9.0.0
  ([`b81ae05`](https://github.com/thiesgerken/carapace/commit/b81ae0549bffe9be570cf02ee2aa2407073a43d0))

## v0.148.3 (2026-07-20)


### Other


- Merge pull request #230 from thiesgerken/renovate/all-routine-dependencies
  ([`7367ae5`](https://github.com/thiesgerken/carapace/commit/7367ae503f3d6e0f09ad8d731d53be0cc00a40db))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`7367ae5`](https://github.com/thiesgerken/carapace/commit/7367ae503f3d6e0f09ad8d731d53be0cc00a40db))

- ⬆️ chore: upgrade all routine dependency updates
  ([`0b1810c`](https://github.com/thiesgerken/carapace/commit/0b1810c26b6246bb70884bddd441f9339e103c1e))

## v0.148.2 (2026-07-20)


### Other


- Merge pull request #245 from thiesgerken/renovate/actions-setup-python-7.x
  ([`944cb51`](https://github.com/thiesgerken/carapace/commit/944cb5123b3640ae64298d8c70e824f6f4d90f52))

### ⬆️ Dependencies


- ⬆️ chore: upgrade actions/setup-python action to v7.0.0
  ([`944cb51`](https://github.com/thiesgerken/carapace/commit/944cb5123b3640ae64298d8c70e824f6f4d90f52))

- ⬆️ chore: upgrade actions/setup-python action to v7.0.0
  ([`ced59dd`](https://github.com/thiesgerken/carapace/commit/ced59ddb1a5d543225766f711ebeae1d679e2121))

## v0.148.1 (2026-07-20)


### Other


- Merge pull request #239 from thiesgerken/renovate/pnpm-11.x
  ([`e647367`](https://github.com/thiesgerken/carapace/commit/e647367dcb62e0f60ab6f1c3ab6d2f207d9bc058))

- Merge pull request #240 from thiesgerken/renovate/astral-sh-setup-uv-8.x
  ([`df3b573`](https://github.com/thiesgerken/carapace/commit/df3b57355e2645d91c145fd7ab3497e69669c98d))

- Merge pull request #242 from thiesgerken/renovate/actions-setup-node-7.x
  ([`de0da4b`](https://github.com/thiesgerken/carapace/commit/de0da4b8c3e41779e04dada43af7d187d902b5d3))

- Merge pull request #246 from thiesgerken/renovate/katex-0.x
  ([`128c0bd`](https://github.com/thiesgerken/carapace/commit/128c0bdcdb370da7665b0409d29f16edf9b3777d))

- Merge pull request #229 from thiesgerken/renovate/lock-file-maintenance
  ([`4547d77`](https://github.com/thiesgerken/carapace/commit/4547d777691f8b08d60e2debe32341d0a457f1c0))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.13.1
  ([`e647367`](https://github.com/thiesgerken/carapace/commit/e647367dcb62e0f60ab6f1c3ab6d2f207d9bc058))

- ⬆️ chore: upgrade pnpm to 11.13.1
  ([`25fd0b2`](https://github.com/thiesgerken/carapace/commit/25fd0b28139fc9f93319edf8ecf4fb00a18ea02d))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v8.3.2
  ([`df3b573`](https://github.com/thiesgerken/carapace/commit/df3b57355e2645d91c145fd7ab3497e69669c98d))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v8.3.2
  ([`ef3cf5c`](https://github.com/thiesgerken/carapace/commit/ef3cf5cce25eec37b89a88129e628a307a541f29))

- ⬆️ chore: upgrade actions/setup-node action to v7.0.0
  ([`de0da4b`](https://github.com/thiesgerken/carapace/commit/de0da4b8c3e41779e04dada43af7d187d902b5d3))

- ⬆️ chore: upgrade actions/setup-node action to v7.0.0
  ([`c5ea0d6`](https://github.com/thiesgerken/carapace/commit/c5ea0d6ff574ea5b0a3708eef30e58d3957f5a92))

- ⬆️ chore: upgrade katex to 0.18.0
  ([`128c0bd`](https://github.com/thiesgerken/carapace/commit/128c0bdcdb370da7665b0409d29f16edf9b3777d))

- ⬆️ chore: upgrade katex to 0.18.0
  ([`9f6c0e6`](https://github.com/thiesgerken/carapace/commit/9f6c0e6900832677207ceeff5be80567ef74c7a1))

- ⬆️ chore: Lock file maintenance
  ([`4547d77`](https://github.com/thiesgerken/carapace/commit/4547d777691f8b08d60e2debe32341d0a457f1c0))

- ⬆️ chore: Lock file maintenance
  ([`1064a47`](https://github.com/thiesgerken/carapace/commit/1064a47acc8037139e66e4ff4da7f68380a87353))

## v0.148.0 (2026-07-20)


### ✨ Features


- ✨Merge pull request #243 from thiesgerken/worktree-knowledge-viewer
  ([`e376e81`](https://github.com/thiesgerken/carapace/commit/e376e817e6c83d6b4246839eb30251c9c8994a86))

- ✨ feat(knowledge): read-only knowledge repo browser in web UI
  ([`e376e81`](https://github.com/thiesgerken/carapace/commit/e376e817e6c83d6b4246839eb30251c9c8994a86))

- ✨ feat(knowledge): copy the full commit hash by clicking it
  ([`b20e456`](https://github.com/thiesgerken/carapace/commit/b20e456335fa4d30ee114f959b6a4ea3c6adb688))

  Listing rows keep showing git's abbreviated hash but now copy the full 40-character one, which is what you actually paste into a git command. The short form is taken from git rather than truncated client-side, since git picks the abbreviation length per repo.

  A copy icon fades in on row hover and briefly becomes a checkmark on success. A rejected clipboard (insecure origin, denied permission) leaves the label untouched instead of falsely reporting success.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): link the session archive path to the knowledge browser
  ([`8a390ad`](https://github.com/thiesgerken/carapace/commit/8a390ad44f83c19d196419bf3dc2030608f88280))

  The archive path shown in the session inspector now opens that file in the browser instead of being inert text. Route building moves to lib/knowledge-links.ts so both views agree on the query-param form the static export requires.

  Also guards the code viewer: Shiki tokenizes a whole document up front, and this link leads straight to a conversation.json that runs to hundreds of KB. Past 128 KB the file renders as plain text with a note, rather than locking the tab.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): show the last commit per entry in listings
  ([`995094f`](https://github.com/thiesgerken/carapace/commit/995094fbadf7fa5dcb729b3725cabc4c7e8ec888))

  Each row now carries the newest commit touching it — short hash and subject line — the way a git host shows a tree. Resolved by a single 'git log --name-only' walk per listing that folds nested paths back to the child row, so a directory of 20 files costs one subprocess, not 20 (~70-160ms on a 900-commit repo).

  Row layout degrades by width: the commit column appears at lg, the relative time at sm, and the filename and size stay at every size. The timestamp now prefers the commit date over the working-tree mtime, which a checkout rewrites; mtime remains the fallback for uncommitted files.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): show last-modified time for files in listings
  ([`14c2bab`](https://github.com/thiesgerken/carapace/commit/14c2bab34a2fb4dbbb04376a8a42782bac156b00))

  File rows now carry a relative mtime ("3 days ago", absolute date past a week) with the exact timestamp as a tooltip, alongside the size. Hidden below the sm breakpoint so narrow rows keep the filename readable.

  Adds lib/format-time.ts with the relative/absolute formatters. sidebar and message still hold their own near-identical copies; noted there for whoever touches them next rather than refactored blind.

  The timestamp is the working-tree mtime, so a checkout or pull rewrites it — it is when the file last changed on disk, not the authoring commit date.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): distinct icons for the top-level skills and sessions dirs
  ([`9104162`](https://github.com/thiesgerken/carapace/commit/9104162ba6debfe67f1b528207f1ee06d0163de3))

  FolderTree for skills/ and FolderArchive for sessions/, distinguishing the collections from the individual skill (FolderCog) and session (FolderClock) dirs inside them. Matched by name and only at the repo root, so a nested dir with either name stays a plain folder.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): icon lookup by name/extension, fix skill label alignment
  ([`28c040b`](https://github.com/thiesgerken/carapace/commit/28c040b0fa72aa6afccb50f2f39706e8cc2d32f5))

  Adds lib/file-icons.tsx: an exact-name table (SOUL.md, SECURITY.md, Dockerfile, lockfiles, .gitignore, …) checked before an extension table (~70 extensions across markup, code, config, images, archives, media). Directories resolve by kind and keep a folder silhouette — FolderClock for session archives, FolderCog for skills — so they still read as directories. Skill dirs are now tagged server-side, which the listing needs to pick that icon.

  Fixes the skill card's section labels drifting to the vertical middle of multi-line value lists: the label row became a flex container when it gained an icon, so items-center measured against the stretched full height. self-start stops the stretch.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): render READMEs for plain dirs, icon the skill sections
  ([`de82b59`](https://github.com/thiesgerken/carapace/commit/de82b595906a63669319219125beaa40938c63e6))

  Any directory without a SKILL.md now renders its README below the listing, the same way skill dirs render their instructions. The name is matched case-insensitively against the entries already listed, so it costs no extra syscalls, and a skill dir that also carries a README still shows SKILL.md. README frontmatter is left intact — only SKILL.md has frontmatter worth stripping.

  Skill card sections gained leading icons (terminal, globe, cable, key, lightbulb) so commands, domains, tunnels, credentials and hints are distinguishable at a glance.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): render parsed skill frontmatter as a card
  ([`ad27abb`](https://github.com/thiesgerken/carapace/commit/ad27abb4b8fe9d13e754a6815badc87bd4893c98))

  Skill dirs now show their declared capabilities above the prose: commands, network domains and tunnels, credentials, and hints. The frontmatter is stripped from the rendered markdown so it no longer appears as raw YAML at the top.

  Parsing reuses the server-side SkillRegistry logic, extracted into parse_skill_document() so both the registry and the browse endpoint share one implementation, and validates through SkillCarapaceConfig. Skills with absent or malformed carapace metadata still render their prose.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): render SKILL.md below skill directory listings
  ([`6162f5d`](https://github.com/thiesgerken/carapace/commit/6162f5d154b6017a08599914cf45e8cafd83fa4c))

  Opening a directory that contains SKILL.md now inlines it in the browse response and renders it under the file listing, so a skill's instructions are visible without opening the file. Detection uses the same marker SkillRegistry scans for.

  kind/doc on the listing are the extension point for parsed skill metadata (commands, network domains, credentials) later.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): label session archive dirs with their title
  ([`443b002`](https://github.com/thiesgerken/carapace/commit/443b00224813e360595e462fcd885ec1e3bd103a))

  Directory listings now tag entries that are session archives (detected by the conversation.json marker, so a reconfigured path_prefix still works) with kind, the session title, and its id. The browser renders the title where a file shows its size, linking to the session in chat, and uses a distinct icon for those dirs.

  kind/label are the extension point for the same treatment on skill dirs later.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): sniff text server-side instead of guessing by extension
  ([`4e47576`](https://github.com/thiesgerken/carapace/commit/4e47576d4e4b86e9b9d4baad546fe540d0b423fc))

  The browse endpoint now inlines file contents for anything that decodes as UTF-8 without NUL bytes, so extensionless files (.gitignore, Dockerfile) and unknown extensions render in the text viewer instead of falling back to download-only. Binaries and files over 1 MiB still report content: null.

  Drops the client-side extension/MIME allowlist and the second round trip that fetched file text after the metadata request.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): show repo HEAD and git sync controls in browser header
  ([`71bed31`](https://github.com/thiesgerken/carapace/commit/71bed3156a2ef3798d4a6d7751fe68cb3a2b47da))

  Rename the page heading to 'Knowledge Repository' so it no longer duplicates the breadcrumb root, and add a meta row between heading and path: current HEAD (short hash + subject) plus the existing global git panel (ahead/behind, pull, push, refresh) reused from the account menu.

  /api/git/status now reports head and head_subject, filled even when no external remote is configured; GlobalGitPanel gained an alwaysShow prop so the browser can offer refresh in that case.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(knowledge): read-only knowledge repo browser in web UI
  ([`1b962ce`](https://github.com/thiesgerken/carapace/commit/1b962cee0bbfe887152b00fbe0c691e02e5728ff))

  Add GET /api/knowledge/browse[/{path}] serving the per-user knowledge repo working tree: directories return a JSON listing, files return metadata or raw content (?raw=1 / ?download=1). Path traversal and .git access are rejected; access is gated by a new 'knowledge' API key scope (cookie sessions unaffected).

  Frontend: /knowledge page with breadcrumb navigation, directory listing, markdown/code rendering (existing MarkdownContent + Shiki), image preview and download fallback. Entry point via sidebar icon.

  Foundation for later augmented displays (skill metadata cards, session archive links).

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### 🔒 Security


- 🔒 fix(knowledge): close .git read-through, inline HTML, and log-parse holes
  ([`15ea56a`](https://github.com/thiesgerken/carapace/commit/15ea56aacd1b6b60f6b4278b95302db7e034877e))

  Self-review of the browse endpoint turned up three more holes of the same family as the symlink escape fixed in 64119ceb:

  - contained_target() checked containment in the repo root but not the .git
    exclusion resolve_target applies, so a committed
    `notes/README.md -> ../.git/config` returned the remote URL — access token
    included — in the listing JSON.
  - ?raw=1 served user-pushed content inline on the app origin with a guessed
    mime, so a pushed .html or .svg ran script under the user's cookie session.
    Only the image types the client renders as an <img> stay inline now.
  - The session-archive probe read and JSON-parsed conversation.json with no
    size cap, once per subdirectory of a listing.

  Also: git accepts \x01 in a commit subject, so splitting the `git log` walk on it blindly dropped every path in that commit and showed a stale commit for those entries. Split only where a commit header follows.

  Frontend, same review: the 128 KB highlighting guard sat below the markdown branch and so never covered a large .md; session rows dropped the commit and date columns they were meant to line up with; a file past the server's inline cap read as "no preview for this file type"; pull/push fetched status twice from the acting panel; formatSize duplicated formatBytes.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🔒 fix(knowledge): do not read through symlinks that escape the repo
  ([`64119ce`](https://github.com/thiesgerken/carapace/commit/64119ceb4f62906ce6ec63441b7aa7ee42ac05a2))

  resolve_target guarded the browsed path, but listing a directory reads through its entries on its own — a SKILL.md, a README, a session's conversation.json — with no containment check. A symlink committed into the repo pointing at any host path had its contents inlined into the browse response, up to the 1 MiB cap.

  Every such read now resolves through contained_target(), which also fixes a listing crashing on a dangling symlink: stat() raised FileNotFoundError and took down the whole directory. Those entries are still listed by name, just without size or metadata read through them.

  Also refreshes browse listings and every git status indicator after a pull or push, and hides the download button while a new path loads so it cannot point at the file just navigated away from.

  Reported by Cursor Bugbot on #243.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### Other


- 🎨 fix(knowledge): reveal the copy icon on the commit column, not the whole row
  ([`1cf87a8`](https://github.com/thiesgerken/carapace/commit/1cf87a8c6244ffdc94ab76dd75ad101db2cabfe8))

  The hover group moves from the row to the commit column, so pointing anywhere in a row no longer suggests the hash is the clickable part.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🎨 fix(knowledge): keep listing columns aligned for directories
  ([`d6dcb7f`](https://github.com/thiesgerken/carapace/commit/d6dcb7faecfbc50254bd018fc82b0da107ec5cab))

  Directories have no size, so the size slot collapsed and pushed their commit and date columns right, out of line with the file rows below. Both trailing slots now hold their width when empty, and the date slot is fixed-width so dates form a column instead of ragged-right text.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🎨 revert(knowledge): plain folder icon for the top-level skills and sessions dirs
  ([`b33fffb`](https://github.com/thiesgerken/carapace/commit/b33fffba16a7a9db9fd87afa4033fcbcf756ee63))

  Reverts the FolderTree/FolderArchive icons; both are plain folders again. Drops the atRoot plumbing they needed, since nothing else uses it. Individual skill and session dirs keep FolderCog and FolderClock.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛 fix(knowledge): wrap long skill values instead of truncating them
  ([`6ddc2e8`](https://github.com/thiesgerken/carapace/commit/6ddc2e8f160ab910126aa8d98c632a14432c525f))

  Commands, vault paths, domains and tunnel endpoints in the skill card now wrap (break-all for mono values, break-words for prose) rather than ending in an ellipsis. Real commands reach 138 characters, so the tail — the part identifying which script actually runs — was the part being hidden. Drops the now-redundant title tooltips.

  Row contexts (breadcrumb, listing entries, HEAD subject) keep truncating; they are single-line by design.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.147.1 (2026-06-28)


### 🐛 Bug Fixes


- 🐛 fix(frontend): wrap long unbroken strings in chat messages
  ([`94737b4`](https://github.com/thiesgerken/carapace/commit/94737b4bc3c521f689072ca4a0d2a22728f6b689))

  Add overflow-wrap: anywhere to .chat-copy-serif so long URIs without whitespace wrap instead of causing horizontal scrolling. Covers both user and assistant messages.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.147.0 (2026-06-26)


### ✨ Features


- ✨Merge pull request #238 from thiesgerken/feature/job-archive-previous-sessions
  ([`921aae6`](https://github.com/thiesgerken/carapace/commit/921aae6d071a0adca1a1f19b686586ec2e6b2dfc))

- ✨ feat(jobs): archive previous sessions on new run
  ([`921aae6`](https://github.com/thiesgerken/carapace/commit/921aae6d071a0adca1a1f19b686586ec2e6b2dfc))

- ✨ feat(jobs): archive previous sessions on new run
  ([`ce37512`](https://github.com/thiesgerken/carapace/commit/ce375127b35b5a7816d42af75b7159a5527c1b79))

  Add an `archive_previous_sessions` option to job definitions. When a fresh-session job runs, earlier sessions it created (channel_ref `job:<id>`) that are still open get committed to knowledge, marked archived, and have their sandboxes torn down. Sessions with a running agent turn are skipped. Rejected together with `persistent_session_id`.

  Keeps recurring jobs (e.g. a daily digest) from piling up idle sessions and sandboxes.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.146.0 (2026-06-24)


### ⬆️ Dependencies


- ⬆️Merge pull request #237 from thiesgerken/feature/pydantic-ai-v2
  ([`8e988e0`](https://github.com/thiesgerken/carapace/commit/8e988e06b0b0a77a2b08bdfb95b6647330601c15))

- ⬆️ Upgrade pydantic-ai to v2
  ([`8e988e0`](https://github.com/thiesgerken/carapace/commit/8e988e06b0b0a77a2b08bdfb95b6647330601c15))

- ⬆️ build(deps): upgrade pydantic-ai to v2
  ([`a3eb87e`](https://github.com/thiesgerken/carapace/commit/a3eb87e1c8a6fae678700e33c4b437ee2d201fb4))

  Bump pydantic-ai pin from >=1.59,<2 to >=2,<3.

  The codebase already tracked v1's latest naming (RunUsage, OpenAIChatModel, input/output_tokens, capabilities, DeferredToolRequests), so the only code change is the Google provider split: v2 replaces the single GoogleProvider + vertexai flag with GoogleProvider (Gemini API) and GoogleCloudProvider (Vertex), both resolved via infer_provider_class and both accepting http_client. Drop the special-case branch and let the generic factory path handle them.

  BREAKING (user config): the google-gla / google-vertex provider prefixes are gone in v2 — use google: / google-cloud: instead. Default install is also slimmer; bedrock/groq/mistral/cohere/xai/huggingface/temporal extras are no longer bundled.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### ✨ Features


- ✨ feat(llm): alias legacy google prefixes and add openai-responses provider
  ([`3502b12`](https://github.com/thiesgerken/carapace/commit/3502b124eb69747c3ccdf7098ca6c83dc6924042))

  - normalize_provider_prefix rewrites pre-v2 google-gla → google and
    google-vertex → google-cloud at the resolution boundary, so existing
    configs and persisted model ids keep working without a DB migration.
  - New openai-responses provider forces the Responses API even on a custom
    base_url (openai / openai-chat stay on Chat Completions for OpenAI-compatible
    servers). Added to OPENAI_COMPATIBLE_PROVIDERS so base_url/api_key/
    thinking_budget_tokens validation accepts it.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.145.1 (2026-06-24)


### Other


- Merge pull request #234 from thiesgerken/renovate/pnpm-11.x
  ([`2521f14`](https://github.com/thiesgerken/carapace/commit/2521f14a5dd04db4ec8d6d71ef2db716eef6b76a))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`4e91c00`](https://github.com/thiesgerken/carapace/commit/4e91c0048ef0a27627decb972f57b9ae2485bb9b))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.8.0
  ([`2521f14`](https://github.com/thiesgerken/carapace/commit/2521f14a5dd04db4ec8d6d71ef2db716eef6b76a))

- ⬆️ chore: upgrade pnpm to 11.8.0
  ([`e40b58a`](https://github.com/thiesgerken/carapace/commit/e40b58a2979025b96f7066f1efc79c67ebb520f8))

## v0.145.0 (2026-06-22)


### ✨ Features


- ✨Merge pull request #235 from thiesgerken/feature/interleave-assistant-text
  ([`f187e1f`](https://github.com/thiesgerken/carapace/commit/f187e1f531de2cbb29cbb81d96bd441b3901d939))

- ✨ Interleave intermediate assistant text with tool calls
  ([`f187e1f`](https://github.com/thiesgerken/carapace/commit/f187e1f531de2cbb29cbb81d96bd441b3901d939))

- ✨ fix(chat): re-project transcript on turn done so metadata shows live
  ([`7b26361`](https://github.com/thiesgerken/carapace/commit/7b26361be03b7eb6d84ebe14f570026bc7aca689))

  The live WS path can't carry persisted-only metadata (timestamps, event indices, per-turn message numbering, usage/TTFT/tok-s), so the new stats only appeared after a manual reload. Re-fetch and re-project the event log when a turn completes — same pattern as the compact handler — preserving any tail that arrived during the async fetch.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(chat): per-turn tok/s, TTFT and provider token totals
  ([`51ec671`](https://github.com/thiesgerken/carapace/commit/51ec6719e6a70ff0f87aa3d99a7554958b9ffd87))

  Show generation speed (tok/s) next to the timestamp on the turn's final answer; TTFT and provider token totals (in/out) go in the tooltip.

  aggregate_turn_generation sums the turn's completed agent requests using the model's reported token counts (never tiktoken surrogates). Generation time is the sum of per-request decode windows (first token → completion), so the gaps between requests — tool execution — are excluded; tok/s reflects decode speed, not tool latency. ttft_ms is the turn's first request's prompt→first-token wait. Persisted onto the assistant event so it survives reload.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(chat): event-level fork & reset (phase 3)
  ([`5601e10`](https://github.com/thiesgerken/carapace/commit/5601e10e4c311716e884ca4106f552b44f2efd49))

  Fork/reset now cut at any message, not just turn boundaries. Each user prompt and assistant bubble (intermediate or final) is a valid branch point.

  Backend: _sliced_transcript_for_event_cut handles three cases — a final-assistant cut reuses the fold-aware turn slice; a mid-turn (partial) or user-prompt cut keeps the older turns compacted and rebuilds only the cut turn verbatim from its events (safe: the newest turn is never folded/tool-compacted). reset_to_turn and fork_session route through it; retry stays turn-level.

  Resetting/forking at a user prompt keeps the conversation through that prompt and drops its response, so you can amend and re-run with a follow-up message.

  Frontend: messages carry their own event index; fork/reset use it directly (no turn snapping); reset slices optimistically at the clicked message.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(chat): persist & interleave intermediate assistant text
  ([`b412f20`](https://github.com/thiesgerken/carapace/commit/b412f20ee3f674e418e64998842d374441593946))

  Previously only a turn's final assistant text was saved (one event at turn end), so narration the model emitted between tool calls was swallowed — on reload all tools collapsed into one group with the text dumped after them.

  Now text emitted before a tool call is flushed as its own `partial` assistant event at its real position (agent/loop.py stream handler → on_assistant_text → turns.py). Turn-boundary detection (completed_event_turns) ignores partial events so reset/fork/retry/compaction stay anchored to the final answer. The live `done` handler finalizes every streaming segment, matching reload.

  Also (phase 2): metadata tooltip gains "message i of n", and copy/fork/reset actions are exposed on all conversational messages (fork/reset snap to the enclosing turn boundary; retry re-runs the latest turn).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛 fix(chat): guard overlapping on-done history refetches
  ([`233e96d`](https://github.com/thiesgerken/carapace/commit/233e96dca155d51f6883cd1640ff260eecff3b39))

  Sequence-guard the on-done re-projection so only the newest turn's refetch applies; a slower earlier response no longer merges against a newer messages state (which could duplicate or drop bubbles when turns finish close together).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix(chat): always append final assistant bubble on done
  ([`4d61ff3`](https://github.com/thiesgerken/carapace/commit/4d61ff3c3b56727da8b0a4dbf09532d1e00e3480))

  The backend persists a final assistant event even when its content is empty, so the live done handler must append it unconditionally (when not streamed) — the earlier truthiness guard dropped it, diverging from the reloaded event log.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix(chat): don't lose pre-tool narration on done / in approval loop
  ([`6f8c047`](https://github.com/thiesgerken/carapace/commit/6f8c0476364f9c0d53865157a89577e8c2fb9328))

  Two Bugbot findings:

  - Live `done` handler overwrote a pre-tool narration bubble with the final
    answer when the answer never streamed (structured/unattended output). Now the
    final answer replaces a streamed bubble only if it is the tail (no tool call
    after it); otherwise narration stays partial and the answer is appended —
    matching the persisted events on reload.
  - The deferred-tool approval loop cleared buffered assistant text without
    flushing, dropping narration emitted after a sub-run's last tool call. Flush
    before clearing for the next sub-run.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 💄 UI/UX


- 💄 fix(chat): drop comma between date and time in turn tooltip
  ([`4081f70`](https://github.com/thiesgerken/carapace/commit/4081f70085106c076ccc4bddb4ebf49b50855193))

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(chat): always show user message timestamp
  ([`78fa35f`](https://github.com/thiesgerken/carapace/commit/78fa35f2cf5608e73cf369decb98013744911020))

  Drop the <10min hide rule; user timestamps now show like assistant ones.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(chat): user controls before timestamp (match assistant order)
  ([`b70ae58`](https://github.com/thiesgerken/carapace/commit/b70ae580f66fefb1a3739adbfdc62cc563336d95))

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(chat): align user message controls like the assistant row
  ([`0d9aaa3`](https://github.com/thiesgerken/carapace/commit/0d9aaa3347dd8ab9f54ec2913aac0e1efa5f2eab))

  The user actions row shrink-wrapped inside the right-aligned column, so the buttons and timestamp clustered side by side instead of spanning the message. Wrap the bubble + actions in a bubble-width container and mirror the layout (timestamp left, controls right under the bubble), matching the assistant row.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### Other


- Merge remote-tracking branch 'origin' into feature/interleave-assistant-text
  ([`e3abdcf`](https://github.com/thiesgerken/carapace/commit/e3abdcf82390112de75abe347a217289490ce0e8))

- remove worktree gitlink
  ([`43b8695`](https://github.com/thiesgerken/carapace/commit/43b869551aafbfff88ec844930ad392ac767bed8))

- ignore worktrees
  ([`3f6e805`](https://github.com/thiesgerken/carapace/commit/3f6e805541ce77c539693d749f2d8a4ab87eabec))

## v0.144.0 (2026-06-21)


### ✨ Features


- ✨Merge pull request #231 from thiesgerken/feature/session-compaction
  ([`fb573e8`](https://github.com/thiesgerken/carapace/commit/fb573e8c0c54c51853e2287c5e0450e6900ac1b0))

- ✨ Session compaction (manual /compact)
  ([`fb573e8`](https://github.com/thiesgerken/carapace/commit/fb573e8c0c54c51853e2287c5e0450e6900ac1b0))

- ✨ feat(chat): enrich turn tooltip with duration, tools, model, tokens
  ([`ae79ff6`](https://github.com/thiesgerken/carapace/commit/ae79ff69af72adea242f98a6eb98b9efeae15a69))

  Turn duration (user→assistant elapsed) and tool-call count are derived during projection; model + input/output tokens are now persisted onto the assistant event (TurnUsage was broadcast-only) and surfaced in the tooltip.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(chat): hover-reveal turn metadata (time + turn number)
  ([`a29ec42`](https://github.com/thiesgerken/carapace/commit/a29ec42584f39778c0f2b79e01dc3d12c9059c2f))

  Each user bubble and assistant turn shows a muted relative timestamp on row hover; its tooltip carries the turn number and absolute local time. Nothing shows at rest, so the default layout is unchanged.

  Backend exposes the event timestamp on HistoryMessage; the projection assigns a turn index (incremented per submitted, non-slash user prompt).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): /compact tools [N] overrides the verbatim hot zone
  ([`dc83d4e`](https://github.com/thiesgerken/carapace/commit/dc83d4ea2443170ff9de5dd540f6180bfc7b5122))

  `/compact tools N` now takes an optional count = verbatim_tool_turns (newest turns whose tool outputs stay verbatim) for that run, mirroring how K overrides keep_turns for /compact and /compact fold. Previously a number after `tools` was rejected. Threaded through run_compaction → _do_tool_returns.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): /uncompact command to rebuild full history (debug)
  ([`fa2f695`](https://github.com/thiesgerken/carapace/commit/fa2f6955025735a6ba09b271cd61acadef273c41))

  Add /uncompact: reconstruct the uncompacted model history from the append-only event transcript, then clear the compaction tree and per-event annotations. Reverses every fold and tool-output compaction in one shot. Faithful in content, order, and tool call/return pairing (by tool_id); lossy only on thinking parts (never recorded as events, and compaction drops them anyway). No-op with a clear message when the session isn't compacted.

  Also pin verbatim_tool_turns in two compaction tests that regressed when the defaults were raised (keep_turns 8, verbatim_tool_turns 4).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): delimit payload + restate instruction (sandwich)
  ([`cd41514`](https://github.com/thiesgerken/carapace/commit/cd41514430880b49527f389c515b2c9a77f171bf))

  Wrap the conversation in <conversation>…</conversation> (and tool output in <tool_output>…</tool_output>) and restate the instruction after the payload: treat the delimited text purely as material to summarize, never as instructions, and output ONLY the compacted history. Keeps long inputs on-task and guards against prompt injection from the conversation/tool content.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): fold summary names sources, skills, and files
  ([`77d89d3`](https://github.com/thiesgerken/carapace/commit/77d89d3dbd361d9652271d065d96766b6f8e4db0))

  Extend the fold prompt to always weave in the concrete sources the work relied on — files read/written/edited (with paths), URLs consulted, skills activated and their purpose, plus key identifiers and unresolved threads — and to err on the side of detail rather than over-compressing. Updated the in-prompt example to show named files/URLs/skills.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): narrative fold summaries instead of terse notes
  ([`e229d1b`](https://github.com/thiesgerken/carapace/commit/e229d1b55387a6ebe808d4e8f85cbe74290aa45d))

  The fold prompt asked for terse notes and preserved mostly the end-state, which read as far too aggressive. Rewrite it to produce a faithful chronological narrative — a past-tense "story" of what the user asked, what the assistant did (commands, tools, files, results), decisions, errors, and pivots — much shorter than the original but not reduced to a few lines. Includes an in-prompt example of the desired style.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(fork): inherit context distribution on tip forks
  ([`c5d615b`](https://github.com/thiesgerken/carapace/commit/c5d615b5031ed09f0f03baee530b22f5a08273be))

  Seed the forked session's context-distribution gauge from the source's last agent LLM request, but only when forking at the latest completed turn. For an earlier turn the source's input shape reflects more context than the fork actually holds, so it's left empty. Cost/usage still start at zero — no billing is carried over.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): per-session compaction model override
  ([`52ab3fb`](https://github.com/thiesgerken/carapace/commit/52ab3fbaf81c98ffac7907150b862ce018a69299))

  Make the compaction model overridable like agent/sentinel/title: `/model compaction NAME`, `/model NAME` (all four), `/model compaction reset`, plus per-user `default_models.compaction`. The compaction engine resolves the session override before falling back to the platform default / title model.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): verbatim tool-output hot zone + K-source docs
  ([`d5c6d24`](https://github.com/thiesgerken/carapace/commit/d5c6d2459d3b86767ffc2e0fa93046bb955438cb))

  - verbatim_tool_turns (default 2): the newest N completed turns keep their
    tool outputs fully verbatim; tool-return compaction only touches kept turns
    older than that zone. 0 disables it. Wired through config + platform
    settings DB round-trip + admin UI (en/de).
  - docs: state that omitted K falls back to the configured keep_turns, and
    document the verbatim hot zone.

  Addresses the two remaining PR review questions.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): configure compaction via admin platform settings
  ([`0f37014`](https://github.com/thiesgerken/carapace/commit/0f37014c1606f389576f003ff71572872f957e8e))

  agent.compaction was unreachable — not in the DB scalar round-trip, the platform-settings PATCH, or any UI, so it was pinned to code defaults.

  - persist compaction in the platform_settings 'agent' row (_AGENT_SCALAR_FIELDS)
  - expose + carry it through PlatformSettings payload/patch + _agent_config_from_patch
    (also fixes the reset-on-save footgun for the field)
  - convert AgentConfig validation errors in the PATCH to 422 instead of 500
  - admin UI: Compaction section (model picker + keep-turns / tool-floor /
    max-parallel inputs), wired through draft/build/dirty-check + en/de i18n
  - docs: configuration is via Settings → Platform → Compaction (DB-backed)

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): phase 4 — e2e ladder test + docs
  ([`3cd82f7`](https://github.com/thiesgerken/carapace/commit/3cd82f7ece443b8c813461f65abf6c0d04f73311))

  - end-to-end test: /compact all drops thinking, folds 7 turns, summarizes
    kept-region tool outputs, attributes usage to the compaction category,
    and is idempotent on a second run
  - docs/compaction.md + README index entry + ROADMAP tick

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): phase 3b — compaction UI (badges, folds, agent view)
  ([`82ff4b4`](https://github.com/thiesgerken/carapace/commit/82ff4b4bcc5b4bf6fbee4dd72957146b9e77c465))

  - HistoryMessage/ChatMessage carry compaction annotations; tool-result merge
    threads the badge through
  - tool rows show a method-aware "compacted" badge (orig→summary tokens)
  - consecutive folded messages collapse into an expandable summary block
  - /compact CommandResultView shows tokens saved + per-strategy counts;
    client refetches history on the compact result so folds/badges render
  - Agent-view overlay: read-only render of the model history exactly as the
    agent sees it (fold summaries + short-form tool returns), toggled from the
    session inspector; backed by GET /agent-history
  - en/de i18n keys at parity

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): phase 3a — agent-view endpoint + history passthrough
  ([`afc4135`](https://github.com/thiesgerken/carapace/commit/afc413566527b672af88925ee24612d122900c57))

  - HistoryMessage.compaction passthrough so the transcript carries fold/tool badges
  - GET /sessions/{id}/agent-history: serialize the model history verbatim
    (fold summaries + compacted tool returns) for the agent-view toggle
  - tool_return_compaction_info accessor

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): phase 2 — /compact command + orchestration
  ([`545dd01`](https://github.com/thiesgerken/carapace/commit/545dd01bf5cc9e4d98aaaa7d135b1d46ba4f1f5a))

  - compaction_summarizer: aux LLM calls (fold + tool-output) logged under the
    "compaction" source, structured DevOps-aware prompts
  - SessionCompactionMixin.run_compaction: ladder (thinking-drop → fold(K) →
    tool-return compact within kept region), parallel tool summaries under the
    shared LLM semaphore + budget guard
  - persists rewritten history, summary tree, and transcript annotations
    (fold node id on folded events; method/tokens on tool_result events)
  - /compact [K], /compact fold [K], /compact tools parsing + help entry
  - CompactionReport returned to the client; on_compaction broadcast

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): phase 1 — pure strategy core
  ([`54df986`](https://github.com/thiesgerken/carapace/commit/54df98672fc9590b772d31e1e47fc3196213b650))

  Provider-agnostic, LLM-free strategy functions over pydantic-ai history:
  - apply_thinking_drop: shed stale ThinkingParts, keep the newest turn's
  - find/apply tool-return compaction: shrink large outputs in place, stamp
    metadata as a re-compaction guard, mark with re-run hint; truncate helper
  - plan/apply fold: collapse turns older than keep-window K into a synthetic
    FOLD_MARKER message; append-only blocks (no drift), pairing preserved
  - plan/apply consolidate: merge adjacent fold blocks

  Planning vs apply split so the engine injects the model later; fully unit-tested.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat(compaction): phase 0 — config, token helpers, persistence
  ([`f8764ca`](https://github.com/thiesgerken/carapace/commit/f8764cabdb3353c7bfb22d10afea62a86b41865b))

  - agent.compaction config (model, keep_turns, tool_output_floor_tokens, max_parallel_summaries)
  - count_text_tokens / count_message_tokens helpers (reuse tiktoken bucket accumulation)
  - "compaction" LlmSource for request logging
  - SessionCompaction tree model + SessionCompactionRow + migration 0004
  - manager load_compaction / save_compaction

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🗑️ Deprecations


- 🗑️ chore(roadmap): remove completed compaction tasks from roadmap
  ([`4dc962c`](https://github.com/thiesgerken/carapace/commit/4dc962c6a3b9d9680aff2609fb85c8e07f3a9179))

### 🐛 Bug Fixes


- 🐛 fix(compaction): satisfy pyrefly in uncompact attachment restore
  ([`eb5eef7`](https://github.com/thiesgerken/carapace/commit/eb5eef7b8f95c772d34e08a0f708ba1d04de4084))

  Reconstruct Attachment via model_validate instead of SimpleNamespace, which doesn't statically satisfy the AttachmentLike protocol (dynamic attrs).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix(compaction): address PR review findings on /compact + /uncompact
  ([`c6594bd`](https://github.com/thiesgerken/carapace/commit/c6594bdcab4460a2884f947520b4745c4fe4c1e7))

  - transcript: restore provider tool_call_id (model_tool_call_id) on rebuilt
    call+return so tool pairing survives /uncompact (fall back to carapace UUID)
  - transcript: re-augment user prompts from persisted attachments on uncompact
  - compaction: include NativeToolCallPart in fold-summary text (isinstance,
    not exact class-name match)
  - align platform/UI/docs compaction defaults to config (keep_turns 8,
    verbatim_tool_turns 4)
  - chat-view: preserve live messages arriving during the post-compact refetch
    instead of clobbering them with an older snapshot
  - command-result: render /uncompact's human-readable message instead of a
    raw JSON blob
  - message: pass compaction annotation to nested child tool calls so they show
    the compacted badge
  - tests: provider-id restore + attachment-preamble restore on rebuild

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix(compaction): tool annotations matched the wrong id namespace
  ([`d31bd6b`](https://github.com/thiesgerken/carapace/commit/d31bd6b6342df07ee33ebaae590f7ac45e3a843a))

  Tool-compaction indicators never showed in the UI: events key tools by a carapace-generated UUID (tool_id), but compaction keys by the model's provider tool_call_id. The two never match, so _annotate_tool_result_events (and the /history model_text enrichment) annotated nothing for real sessions — it only worked in tests that reused one id.

  Record the provider id (ctx.tool_call_id) on the tool_result event as model_tool_call_id and match on it, falling back to tool_id for legacy/test events. Fixes future compactions; existing sessions can't be backfilled (no id link was stored).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix(compaction): keep reset/fork in sync with folded history
  ([`3a3c1a1`](https://github.com/thiesgerken/carapace/commit/3a3c1a14a4fab3737412d7df571f6e760f929fa0))

  Reset and fork sliced model history by completed event-turn count, but folds collapse old turns so the model-turn count diverges — truncation could leave turns the events no longer contain (or under-trim), and the persisted compaction tree was never trimmed (fork inherited fold messages with no tree).

  Slice fold-aware via the surviving `folded_into` event annotations (keep the leading fold prefix + the matching verbatim tail) and trim/carry the compaction tree to match. Addresses two Bugbot findings on the per-session-model commit.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix(compaction): address PR review threads
  ([`23bb2c6`](https://github.com/thiesgerken/carapace/commit/23bb2c6e1bee5c6ba91def51cf438f7024cacab4))

  - honor agent.compaction.max_parallel_summaries: bound tool-output
    summarization with a semaphore instead of an unbounded asyncio.gather
  - surface compact refetch failures: append an error row + reload hint
    instead of swallowing the catch, so the transcript isn't silently stale
  - agent view: distinct error copy (agentError) vs the empty-history copy
    so a fetch/permission failure is no longer shown as "No history yet"

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix(compaction): pyrefly errors + fold/tool annotation ordering
  ([`8bfde64`](https://github.com/thiesgerken/carapace/commit/8bfde6492d8c25f5ca3a40595e605ebd67f4efdc))

  backend-lint (pyrefly):
  - stub run_compaction on SessionCommandMixin; type llm_request_recording
    stub as AbstractContextManager (fixes inconsistent-inheritance + with-None)
  - rebuild compacted tool returns as a base ToolReturnPart (str content),
    restricted to exact type so capability-return subclasses are never touched
  - guard non-str tool_id before dict.get in _annotate_tool_result_events

  Bugbot: _annotate_folded_events skipped turns that only carried a tool-output annotation, so `/compact tools` then `/compact fold` left folded turns unbadged. Skip only already-folded turns and merge annotations.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 💄 UI/UX


- 💄 fix(chat): clearer token tooltip wording ("12k in, 1.8k out")
  ([`053710a`](https://github.com/thiesgerken/carapace/commit/053710a1cb1a7ee4e1187e19b6032e974d0e2eab))

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(chat): move user timestamp to bottom-right, always show on assistant
  ([`29cf1de`](https://github.com/thiesgerken/carapace/commit/29cf1de995571778f889af8431d41aa64a33bd84))

  User turn meta now sits bottom-right under the bubble like the assistant row; the <10min hide rule applies to user turns only (assistant turns always show).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(chat): hide turn timestamp for turns under 10min old
  ([`d8f445e`](https://github.com/thiesgerken/carapace/commit/d8f445e526807cad9eaf940f8482e5505ae9350c))

  Show it by event age, not by reload — a fresh turn stays bare whether it arrived live or via a page refresh.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(chat): always show turn timestamp instead of hover-reveal
  ([`8beeb1c`](https://github.com/thiesgerken/carapace/commit/8beeb1c1a22aa52ac6b25d93fe259fc4b46aa143))

  Relative time is unintrusive enough to stay visible; keep turn number and absolute time in the tooltip.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(compaction): group tool rows inside the fold rail
  ([`5444d16`](https://github.com/thiesgerken/carapace/commit/5444d1648b37f366658b50bb606433c8cf0740fa))

  Folded turns rendered their children individually, losing the tool-row grouping the live transcript uses. Extract groupRenderItems into tool-call-group.tsx (shared, no import cycle) and apply it inside the fold rail so runs of tool calls collapse into a ToolCallGroup there too.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(compaction): localize the compaction method word
  ([`30b2cd9`](https://github.com/thiesgerken/carapace/commit/30b2cd9674b2690e11dec80bc4f4ce73992b34d6))

  The tool tooltip and agent-view badge interpolated the raw backend method ("summarize"), so German read "Tool-Ausgabe summarize …". Add localized method labels (summarized/truncated/dropped → zusammengefasst/gekürzt/entfernt) and use them in the tooltip and agent-history badge.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(compaction): icon-only tool chip, details in tooltip
  ([`c9e3df4`](https://github.com/thiesgerken/carapace/commit/c9e3df4d055b91a811203683b3f80c3749f31996))

  The compacted tool chip showed a redundant "summarize" label while sibling chips are icon-only. Drop the label — the tooltip already states the method and token savings (orig→summary). Removed the now-unused toolBadge string.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 fix(compaction): fold rail sits in the gutter, no content shift
  ([`1c29dc4`](https://github.com/thiesgerken/carapace/commit/1c29dc47465a3d0bb29d8036899f0b54342f621c))

  The fold rail used border-l + pl-2.5, nudging the originals ~10px right. Move it to an absolutely-positioned bar in the left gutter (negative offset, within the list padding) so folded turns align exactly with every other message.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 feat(compaction): show originals by default with subtle compaction markers
  ([`9bac6b2`](https://github.com/thiesgerken/carapace/commit/9bac6b2b10484f73b280874e7c8086811dce8040))

  Reworked the compaction UI so the user mainly sees the uncompacted history:

  - Folded turns no longer collapse behind a summary. They render inline and
    expanded inside a left margin rail with a header chip ("N turns condensed for
    the model"); the chip expands to the model-facing summary text.
  - Compacted tool rows keep the original output as the main content; the row's
    details gain a "Model sees" disclosure with the shortened return + token delta.
  - /history enriches each annotation with the model-facing text (fold node
    summary, compacted tool content) so the main view needs no second fetch.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 💄 refactor(compaction): first-level compaction_model, drop max-parallel knob, UX polish
  ([`4099f51`](https://github.com/thiesgerken/carapace/commit/4099f517a50ac25bb4c961a779621c66d1634c37))

  - compaction model is now a top-level agent.compaction_model (like model/
    sentinel_model/title_model) and lives in the "Default models" UI section
    alongside the other three, not buried in the Compaction section
  - drop agent.compaction.max_parallel_summaries: tool-output summaries are
    already bounded by the shared LLM semaphore (agent.max_parallel_llm)
  - UI: label "Keep recent turns" (drop the cryptic "(K)")
  - de: "Komprimierung" → "Compaction" (the natural term in German too)
  - docs updated

  No migration needed (platform settings are schemaless JSON; PR unmerged).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### Other


- increase default values for keep_turns and verbatim_tool_turns
  ([`8ee5f94`](https://github.com/thiesgerken/carapace/commit/8ee5f941c2e1b9821007774b6e591276311d7edd))

- 🛡️ fix(session): warn when fork/reset truncates a desynced history
  ([`ab704a6`](https://github.com/thiesgerken/carapace/commit/ab704a6351c81285ecefb4becddf649071a3f86a))

  fork/reset slice the model history by the event-turn count and silently cap to whatever the history holds (min(turn_count, available)). If a session's model history ever lags its events, the copy/reset is quietly truncated to fewer turns with no signal — exactly the failure that produced a 1-turn copy of a 23-turn session. Log a loud warning when the model history has fewer completed turns than the event transcript so the anomaly is visible instead of silent.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✅ test(compaction): model precedence + reset into folded region
  ([`10c156d`](https://github.com/thiesgerken/carapace/commit/10c156d220ae3b608904da911e172bd0349e6abf))

  Two gaps with no direct coverage: the compaction model resolution order (session override → platform compaction_model → title) and rewinding to a turn the fold already swallowed (tail_turns=0 → history collapses to the lead fold, tree node retained). Brings the suite to 1000.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🎨 refactor(compaction): hoist agent-history imports to module top
  ([`3258e82`](https://github.com/thiesgerken/carapace/commit/3258e824abb95aa20decd8730d8511ba40a377eb))

  Move the in-function imports in get_agent_history (ToolReturnPart, FOLD_MARKER, is_fold_message, tool_return_compaction_info) to the top of history.py — no circular import.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- Merge remote-tracking branch 'origin/main' into feature/session-compaction
  ([`310561b`](https://github.com/thiesgerken/carapace/commit/310561b9b0d47a0693a0eb084684ba2faeeae910))

## v0.143.1 (2026-06-20)


### Other


- Merge pull request #228 from thiesgerken/renovate/pnpm-11.x
  ([`67d25e5`](https://github.com/thiesgerken/carapace/commit/67d25e51d4a2c8742661e0b706a3b7f1e534f4d8))

- Merge pull request #232 from thiesgerken/renovate/actions-checkout-7.x
  ([`87f0194`](https://github.com/thiesgerken/carapace/commit/87f019493bfcab575711e80ab5bd8973631e0bcf))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.7.0
  ([`67d25e5`](https://github.com/thiesgerken/carapace/commit/67d25e51d4a2c8742661e0b706a3b7f1e534f4d8))

- ⬆️ chore: upgrade pnpm to 11.7.0
  ([`3e358a7`](https://github.com/thiesgerken/carapace/commit/3e358a759f94a259de99fd32e606201abf6a5d71))

- ⬆️ chore: upgrade actions/checkout action to v7.0.0
  ([`87f0194`](https://github.com/thiesgerken/carapace/commit/87f019493bfcab575711e80ab5bd8973631e0bcf))

- ⬆️ chore: upgrade actions/checkout action to v7.0.0
  ([`c31da8e`](https://github.com/thiesgerken/carapace/commit/c31da8e3312e9f84ede8b9d154a5b67b9f5c8542))

## v0.143.0 (2026-06-19)


### ✨ Features


- ✨Merge pull request #233 from thiesgerken/feat/group-tool-rows
  ([`80b4f1b`](https://github.com/thiesgerken/carapace/commit/80b4f1b20c5aa151b1df4f937498be9f27763f88))

- ✨ feat: group tool-call runs + restyle rows and usage panel
  ([`80b4f1b`](https://github.com/thiesgerken/carapace/commit/80b4f1b20c5aa151b1df4f937498be9f27763f88))

- ✨ feat: collapse tool-call runs into a summary group
  ([`72693d6`](https://github.com/thiesgerken/carapace/commit/72693d6ee0a9c9e4e27e858f67772c558dd3c2a5))

  Consecutive tool_call/thinking messages now collapse into a single ToolCallGroup row showing a summary ("Ran 4 commands, read 7 files, edited 3 files"). Finished runs collapse by default; in-progress runs stay expanded with present-tense wording and a spinner, then auto-collapse when the turn ends (unless the user toggled). Grouping is render-only, no backend or type changes.

  Also drop a redundant trailing "geschrieben" in the German write summary.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛 fix: collapse history usage panels, expand only live ones
  ([`7fa4197`](https://github.com/thiesgerken/carapace/commit/7fa4197301c855b84772b5aa40480a6b99255356))

  The setTimeout hydration heuristic failed because history loads async, so panels mounted after the tick and started expanded. Mark live-appended command messages with `live: true` and thread it down as defaultExpanded: replayed history panels start collapsed, a freshly run /usage starts open.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix: derive group open state instead of setState in effect
  ([`6f96b55`](https://github.com/thiesgerken/carapace/commit/6f96b55f291b194240a9f7478240c287cbe78f1f))

  Replace the useEffect+setOpen pattern with derived state (override ?? inProgress) to satisfy react-hooks/set-state-in-effect.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix: count nested child tool calls in group summary
  ([`2ad6453`](https://github.com/thiesgerken/carapace/commit/2ad64533e04a1b50f901a46158ea2a3c47ba0c0c))

  Flatten message.children into the summary counts so commands/reads spawned as child rows (e.g. under a skill) are no longer under-reported.

  Addresses Cursor Bugbot review.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 💄 UI/UX


- 💄 style: lighten tool rows, add timeline rail, collapsible usage
  ([`e71ec38`](https://github.com/thiesgerken/carapace/commit/e71ec38dac7d4644cef4d0bc4c06e669d2f5651e))

  - Drop per-row background fill; rows are quiet text lines with hover +
    active (open) fill (bg-accent).
  - Labels use the UI font; payloads stay mono but a touch smaller (11px)
    so the right side no longer outweighs the label.
  - Expanded tool-call groups get a left rail tying their steps together.
  - Completed thinking blocks show whole seconds; the live timer keeps
    decimals/ms for a responsive feel.
  - /usage breakdown is now collapsible (budget gauges + tables fold under
    the total summary). Existing panels start collapsed on load; a freshly
    run /usage starts expanded.
  - Zero-cost cells ("-") use normal text color instead of green.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.142.4 (2026-06-16)


### 🐛 Bug Fixes


- 🐛 fix: deny orphaned proxy requests without invoking sentinel
  ([`e73d2b8`](https://github.com/thiesgerken/carapace/commit/e73d2b8bbe2a57794205d42dce924bd8cb18d618))

  When a skill activation (or any exec) is cancelled, the in-container process keeps running and its network requests reach the session-scoped domain approval callback, escalating each one to the sentinel and burning tokens. Guard request_domain_approval: if no exec is live (no entry in session_current_command), deny immediately instead of consulting the sentinel.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.142.3 (2026-06-14)


### Other


- 📋 docs: remove done items from roadmap
  ([`d2588fc`](https://github.com/thiesgerken/carapace/commit/d2588fc759a96504f725fee61c2da89d33bc07a4))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`ad6d455`](https://github.com/thiesgerken/carapace/commit/ad6d45566f5d99447f6f2553a4e12aac4f91da72))

## v0.142.2 (2026-06-14)


### 🐛 Bug Fixes


- 🐛 fix: exclude None values in session history response model
  ([`4f3f706`](https://github.com/thiesgerken/carapace/commit/4f3f706592fd303e1dfd0889652faad6943b4575))

- 🐛 fix: set max_tokens above thinking budget for Anthropic models
  ([`3974949`](https://github.com/thiesgerken/carapace/commit/3974949163141a9979202bf2b2d6763d7e82360b))

  Anthropic counts thinking tokens toward max_tokens and rejects requests where max_tokens <= thinking.budget_tokens. pydantic_ai defaults max_tokens to 4096, but a unified thinking level maps to a larger budget for budget-based models (e.g. haiku-4-5: True -> 10000), causing a 400. Raise max_tokens above the budget when enabling thinking on an Anthropic entry.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.142.1 (2026-06-14)


### ♻️ Refactoring


- ♻️Merge pull request #225 from thiesgerken/worktree-settings-routes
  ([`b899b1e`](https://github.com/thiesgerken/carapace/commit/b899b1e81f113a0c265939c7067e9f5faf2d8f64))

- ♻️ Settings as real routes + extract jobs panel
  ([`b899b1e`](https://github.com/thiesgerken/carapace/commit/b899b1e81f113a0c265939c7067e9f5faf2d8f64))

- ♻️ refactor: settings as real routes; extract jobs panel
  ([`e1e17bd`](https://github.com/thiesgerken/carapace/commit/e1e17bd29394efd2c8ae595c689c40d726a17dba))

  Follow-up to the API-keys PR. Replaces the query-param settings tabs and the mis-named 1355-line jobs-view container with real Next.js routes.

  - /settings/<tab> are real routes (App Router route group (app)/), prerendered
    per tab under output:export. Existing nginx try_files serves them — no infra
    change. Chat stays at / with ?session=.
  - App shell (sidebar + connection/session state + auth gate) hoisted into
    AppShellProvider/useAppShell; page.tsx split into (app)/layout + (app)/page +
    (app)/settings/{layout,[tab]/page}.
  - jobs-view.tsx is now just the JobsView jobs panel (tab nav + 5 panel dispatches
    moved to the settings route). The settings container no longer masquerades as
    "JobsView".
  - jobs deep-link is now /settings/jobs?job=<id>.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛 better logging for login problems
  ([`d3d8e2b`](https://github.com/thiesgerken/carapace/commit/d3d8e2baf630830c6f9f80887da894ddd2db1610))

- 🐛 fix: don't bounce admins off platform tabs before roles load
  ([`bf0eb9c`](https://github.com/thiesgerken/carapace/commit/bf0eb9cebae8798cb372223d4f3cbadd4f7838c0))

  Cursor (PR #225): on a stored connection currentUser loads asynchronously, so isAdmin is false until it resolves. The platform-tab guard redirected to /settings/preferences before roles were known, bouncing admins who deep-link or refresh /settings/platform-*. Only redirect once currentUser is known.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### Other


- Merge remote-tracking branch 'origin/main' into worktree-settings-routes
  ([`af674ec`](https://github.com/thiesgerken/carapace/commit/af674ec86f0f2afe00f93f8d619e4173b35435b8))

## v0.142.0 (2026-06-14)


### Other


- Merge pull request #224 from thiesgerken/renovate/all-routine-dependencies
  ([`4ef22b3`](https://github.com/thiesgerken/carapace/commit/4ef22b37e78901ba3e10a52ba129cced0b1dcb77))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates to 11.5.3
  ([`4ef22b3`](https://github.com/thiesgerken/carapace/commit/4ef22b37e78901ba3e10a52ba129cced0b1dcb77))

- ⬆️ chore: upgrade all routine dependency updates to 11.5.3
  ([`8c568c8`](https://github.com/thiesgerken/carapace/commit/8c568c8b1e545ddc49f13ba3e60305eb9d73104d))

### ✨ Features


- ✨Merge pull request #227 from thiesgerken/worktree-api-keys
  ([`72971be`](https://github.com/thiesgerken/carapace/commit/72971be8bcb8537c0bafc0cf4b2a1e5a9669669a))

- ✨ feat: agent-drivable CLI (non-interactive session + job control)
  ([`72971be`](https://github.com/thiesgerken/carapace/commit/72971be8bcb8537c0bafc0cf4b2a1e5a9669669a))

- ✨Merge pull request #223 from thiesgerken/cli-enhancements
  ([`6980b72`](https://github.com/thiesgerken/carapace/commit/6980b7267dd33ade673487400d9906ad2c9b32b5))

- ✨ feat: agent-drivable CLI (non-interactive session + job control)
  ([`6980b72`](https://github.com/thiesgerken/carapace/commit/6980b7267dd33ade673487400d9906ad2c9b32b5))

- ✨ feat: carapace CLI skill + CLI-only base package
  ([`5ce598e`](https://github.com/thiesgerken/carapace/commit/5ce598e41a59cb5c7f4afaaffeef8b91663e7732))

  Bundle a `carapace` skill so a sandboxed agent can drive a carapace server over the non-interactive JSON CLI (sessions, approvals, jobs). Auth via a vault-injected API key; server domain is a per-deploy placeholder documented in REFERENCE.md.

  Split the package so the client is light: base `dependencies` now cover only the CLI (typer/rich/httpx/websockets/python-dotenv — ~16 deps, no compiled wheels), and the server/agent/db stack moves to the `server` optional extra. `pip install carapace` is now a client; the server installs `carapace[server]`. Dockerfile syncs `--extra server`; the dev group includes it so CI/tests are unchanged. The skill's git install thus pulls the light client only.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat: agent-drivable CLI (non-interactive session + job control)
  ([`4a93863`](https://github.com/thiesgerken/carapace/commit/4a93863780ee1f9f899158e9b045b79f98b07c44))

  Add JSON-output, non-interactive CLI commands so an agent can drive the server: session list/get/create/update/history/pending/send/cancel, approval allow/deny by unique request id, job list/get/create/update/ delete/run. The human `chat` REPL now refuses on a non-TTY (--force to override).

  - `session send --wait` drives a turn over the WS and returns when it
    ends; on an approval/escalation request it ABORTS (without cancelling),
    returning the request's unique id plus ready-to-run allow/deny commands.
    A --wait timeout returns status=timeout and leaves the turn running.
  - `approval allow|deny <session> <id>` resolves one specific pending
    request by id (rejects unknown ids); --wait reads the resumed turn.
  - Agent text (markdown/LaTeX) passes through verbatim — no rendering, no
    stripping. Exit codes: 0 ok, 1 error, 2 needs_approval, 3 timeout.
  - New server endpoint GET /api/sessions/{id}/pending-approvals
    (sessions:read) backs `history`/`pending` and approval lookups.

  Auth via --api-key / CARAPACE_API_KEY (env is the ergonomic default for the grouped sub-apps).

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛 fix: observer turn-wait must not report missed failures as success
  ([`14b8935`](https://github.com/thiesgerken/carapace/commit/14b8935535991c8518008b921f78c65cf0d3aa9f))

  The previous observe-mode fix reported any on-connect `status` with `agent_running=false` as `done`/exit 0. But the server replays no terminal frame to a late subscriber, so a turn that *failed* or was *cancelled* before connect was also surfaced as an empty success.

  `_read_turn` now returns a neutral `finished` instead of fabricating `done`, and `_drive_turn` backfills `content` from the last assistant message in history — which, for a failed/cancelled turn, is the persisted terminal message rather than nothing.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix: job run --wait misses turns that finish before WS connect
  ([`10b76dd`](https://github.com/thiesgerken/carapace/commit/10b76dd167ce07f42f75c8f14ce73f2bb8767acd))

  `job run --wait` starts the turn via REST, then connects the WebSocket as a pure observer. If the turn finished before that connect, the server replays no `done` frame — only the on-connect `status` with `agent_running=false`, which `_read_turn` ignored, so the CLI hit `--timeout` (exit 3) on an already-done job.

  Add an `observe` mode to `_read_turn`: a `status` frame with `agent_running` false now resolves to `done`. `_drive_turn` enables it only when no frame is sent on the socket (`message is None and approval is None`), so the send/approval paths — which connect, then send, then run — still ignore their pre-send `status:false`.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.141.1 (2026-06-14)


### Other


- Merge pull request #226 from thiesgerken/fix/sandbox-git-identity
  ([`5a1b2cc`](https://github.com/thiesgerken/carapace/commit/5a1b2cc1f2a90dabbe360d4c1118f1fe6605b0a3))

### 🐛 Bug Fixes


- 🐛 fix: persist sandbox git identity across pod restarts
  ([`5a1b2cc`](https://github.com/thiesgerken/carapace/commit/5a1b2cc1f2a90dabbe360d4c1118f1fe6605b0a3))

- 🐛 fix: persist sandbox git identity across pod restarts
  ([`d8f669e`](https://github.com/thiesgerken/carapace/commit/d8f669eea4d90b1bb9e0eebfba7c800ace6a67a4))

  Git identity was set via `git config --global`, writing to `~/.gitconfig` on the ephemeral container rootfs. Only `/workspace` and `/tmp` are on the persistent PVC, so suspend/resume (StatefulSet scale 0→1 → fresh pod) wiped the identity while the cloned repo survived. `clone_knowledge_repo` early-returned when the repo was already present, so identity was never re-applied — the agent's first commit failed with an unknown author and it had to set identity by hand.

  Write identity as repo-local config (`/workspace/.git/config`), which lives on the PVC and survives pod recreation. Also re-apply identity + commit-msg hook even when the repo already exists, migrating sessions cloned under the old global scheme.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.141.0 (2026-06-14)


### ✨ Features


- ✨Merge pull request #222 from thiesgerken/worktree-api-keys
  ([`89fa0e6`](https://github.com/thiesgerken/carapace/commit/89fa0e62a60f7c261e6b7ca1720e2fbbb790d681))

- ✨ feat: user-managed scoped API keys
  ([`89fa0e6`](https://github.com/thiesgerken/carapace/commit/89fa0e62a60f7c261e6b7ca1720e2fbbb790d681))

- ✨ feat: API-key auth for the CLI client
  ([`d306d63`](https://github.com/thiesgerken/carapace/commit/d306d632c170e754e802e31cb767c7d2155e79be))

  Add --api-key / CARAPACE_API_KEY to `carapace chat`. When set, the CLI uses Authorization: Bearer for REST and the ?api_key= query param for the chat WebSocket, skipping username/password login. Key needs the sessions scope. Username/password login stays as the fallback.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- ✨ feat: user-managed scoped API keys
  ([`7be7b72`](https://github.com/thiesgerken/carapace/commit/7be7b723a714ae63f441b4a567fcabdf97461d06))

  Add long-lived API keys that users self-manage in the web UI. A key acts as its owning user but its scopes narrow access (read/write per route group: sessions, jobs, preferences, notifications, history, admin).

  - Opaque tokens (ck_<prefix>.<body>), sha256-hashed at rest, prefix-indexed
    lookup, shown once. New api_keys table + alembic 0003.
  - ApiKeyStore + Scope/Access/ApiKeyGrant. Bounded by owner: dies on user
    disable/delete, survives password change, admin grant stripped live on
    demotion.
  - Auth resolves cookie OR Authorization: Bearer; require(scope, access)
    dependency gates every /api route. Bearer also works on the chat WS via
    ?api_key= (sessions:write). Sandbox API untouched.
  - Cookie-only key management endpoints (POST/GET/DELETE /api/keys) — a key
    cannot mint or list keys.
  - Frontend: API Keys settings tab with per-scope read/write toggles, admin
    scope only for admins, secret shown once with copy box. en/de i18n.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛 fix: hide stale admin scope in API key listing
  ([`52824c1`](https://github.com/thiesgerken/carapace/commit/52824c10e6870f8c989e984a4b1c07b5cfc274d5))

  Cursor: GET /api/keys showed stored scopes verbatim, so a demoted owner

  still saw admin:* even though validate_key strips those grants. list_keys now drops admin scopes when the owner lacks the admin role, matching the effective grants used at auth time.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix: WS cookie fall-through, FK-owned API keys, CLI auth guards
  ([`8a632e5`](https://github.com/thiesgerken/carapace/commit/8a632e5969fef79f9f6547dc3267e24eb84488bb))

  PR review follow-ups:
  - WS auth now falls through a stale/invalid session cookie to the api_key
    query param (matched REST's cookie→Bearer fall-through); a valid key in
    the URL was being rejected when the browser still sent an old cookie.
  - api_keys.user is now a FK to users.username with ON DELETE CASCADE, so
    the DB drops a user's keys on delete; removed the manual delete in
    delete_user.
  - CLI: add --key alias and reject --api-key combined with --user/--password.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix: surface expired API keys and history-scope needs in CLI
  ([`ccb4ae4`](https://github.com/thiesgerken/carapace/commit/ccb4ae41bc141921983e8e000cb10be66efc624b))

  Cursor Bugbot follow-ups on 300d011:
  - list view now badges expired keys instead of showing them as active
  - chat --history replay warns when the key lacks history:read, and the
    --api-key help notes the extra scope

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

- 🐛 fix: delete API keys when their owning user is deleted
  ([`300d011`](https://github.com/thiesgerken/carapace/commit/300d0110d1a7e494d986c1ead8e2ec7175f44735))

  Cursor Bugbot: a recreated user with the same username would inherit the deleted account's still-hashed API keys. Hard-delete keys on user removal.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### 🔧 Configuration


- 🔧 chore: enforce 4-space message catalogs via prek
  ([`7ec25f5`](https://github.com/thiesgerken/carapace/commit/7ec25f59bb6e9c5977f835cd57498d7a32824307))

  pretty-format-json with --no-ensure-ascii keeps indentation consistent while preserving literal UTF-8 (umlauts, ellipses), so the catalogs can't silently reflow to 2-space again.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

### Other


- 🎨 style: restore 4-space indent in message catalogs
  ([`5c83041`](https://github.com/thiesgerken/carapace/commit/5c83041712275f8070d82393298d384f5bb29a0e))

  Earlier api-keys work rewrote en/de.json at 2-space, bloating the PR diff. Reindent to the repo's 4-space (umlauts/ellipses kept literal) so the diff shows only the apiKeys additions.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## v0.140.6 (2026-06-12)


### Other


- Merge pull request #220 from thiesgerken/renovate/all-routine-dependencies
  ([`a8331ad`](https://github.com/thiesgerken/carapace/commit/a8331ad06fa08fb3169ff97b8bd27e805732cd67))

- Merge pull request #221 from thiesgerken/renovate/alpine-3.x
  ([`7e1eb13`](https://github.com/thiesgerken/carapace/commit/7e1eb138e206f90bcb0a7975d528dd9abbfce18d))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`a8331ad`](https://github.com/thiesgerken/carapace/commit/a8331ad06fa08fb3169ff97b8bd27e805732cd67))

- ⬆️ chore: upgrade all routine dependency updates
  ([`90ee923`](https://github.com/thiesgerken/carapace/commit/90ee923467d77f5602aaa07a64c8463ba5c28efd))

- ⬆️ chore: upgrade alpine Docker tag to v3.24
  ([`7e1eb13`](https://github.com/thiesgerken/carapace/commit/7e1eb138e206f90bcb0a7975d528dd9abbfce18d))

- ⬆️ chore: upgrade alpine Docker tag to v3.24
  ([`c1618af`](https://github.com/thiesgerken/carapace/commit/c1618af541e84d0f64b551da62f974bae65ead31))

## v0.140.5 (2026-06-10)


### 🐛 Bug Fixes


- 🐛 fix: grant pods/log RBAC so sandbox readiness wait works
  ([`6731cbf`](https://github.com/thiesgerken/carapace/commit/6731cbf8fa544aaca25a314a05a85778cc32f6e4))

  The server ServiceAccount could get pods and pods/exec but not the pods/log subresource, so every logs() call 403'd. wait_for_ready scrapes container logs for the ready marker and thus never matched, burning the full 180s timeout on every sandbox create/resume/claim before silently proceeding — the multi-minute startup users observed.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

## v0.140.4 (2026-06-10)


### 🐛 Bug Fixes


- 🐛 force release
  ([`d7e9341`](https://github.com/thiesgerken/carapace/commit/d7e934122b4f982916dc60493ef6763d5174719a))

### Other


- 🩺 debug: log logs() kr8s failures at debug level
  ([`2475c17`](https://github.com/thiesgerken/carapace/commit/2475c17c8734ace363736f1f1fdc36447e292e76))

  Keep the get-vs-stream split and exact exception repr, but emit at debug so it's quiet by default; enable via CARAPACE_LOG_LEVEL=debug when diagnosing the wait_for_ready stall.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- 🩺 debug: surface exact kr8s error in logs(), split get vs stream
  ([`ad787e5`](https://github.com/thiesgerken/carapace/commit/ad787e591042e86f6fcafcb61e6216bca5e6a578))

  logs() returned the "(pod not found or logs unavailable)" placeholder on a running StatefulSet pod, so wait_for_ready burned 180s. Promote the swallowed exception to a warning and split Pod.get from pod.logs so the next stall reveals which call fails and the exact kr8s error.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

## v0.140.3 (2026-06-10)


### Other


- 🩺 debug: instrument sandbox readiness wait + pin logs container
  ([`fc5d99e`](https://github.com/thiesgerken/carapace/commit/fc5d99e3ea5ea86f96d69760ff27ec535774d3ef))

  wait_for_ready burned the full 180s timeout on resumed StatefulSet pods even though the pod printed the ready marker quickly. logs() swallowed kr8s errors silently, hiding why the marker poll never matched.

  - logs(): pass container="sandbox" explicitly (kr8s container=None can
    resolve the default container oddly on a just-restarted pod) and log
    the kr8s exception at debug instead of swallowing it.
  - wait_for_ready(): include container id and the last log tail in the
    timeout warning to reveal whether logs() returned the error
    placeholder or real marker-less output.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- 📝 chore: update roadmap by removing obsolete workspace items
  ([`b9bfb72`](https://github.com/thiesgerken/carapace/commit/b9bfb7220adf4c0d08033cabdccaeaaf18923c2a))

### 🐛 Bug Fixes


- 🐛 fix: force-overwrite read-only file on credential write
  ([`e49d71c`](https://github.com/thiesgerken/carapace/commit/e49d71c83990ec195ca7d54888bef93f0857642e))

  Credential files are written mode 0400. A stale read-only token.txt surviving in the persisted /workspace (backend crash or pod eviction skips post-exec cleanup) made the next truncating redirect fail with "Permission denied". rm -f before redirect clears the leftover.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

## v0.140.2 (2026-06-07)


### 🐛 Bug Fixes


- 🐛 fix: avoid asyncio loop blockade
  ([`763f233`](https://github.com/thiesgerken/carapace/commit/763f233ba6acaf15a28a8642e1fae958a76e4a38))

- 🐛 fix: increase k8s idle timeout for sandboxes
  ([`aeb6c57`](https://github.com/thiesgerken/carapace/commit/aeb6c57d3766f63c01b4d7ca7975ae4f70124969))

## v0.140.1 (2026-06-07)


### Other


- Merge pull request #217 from thiesgerken/renovate/traefik-3.x
  ([`eab3eb6`](https://github.com/thiesgerken/carapace/commit/eab3eb60ad5ec99f8d9caf6f22c7211bbb90dff7))

### ⬆️ Dependencies


- ⬆️ chore: upgrade traefik Docker tag to v3.7
  ([`eab3eb6`](https://github.com/thiesgerken/carapace/commit/eab3eb60ad5ec99f8d9caf6f22c7211bbb90dff7))

- ⬆️ chore: upgrade traefik Docker tag to v3.7
  ([`92fe7cd`](https://github.com/thiesgerken/carapace/commit/92fe7cd1d886af3d63c2d210e19e539857e6c831))

## v0.140.0 (2026-06-07)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`6849bb1`](https://github.com/thiesgerken/carapace/commit/6849bb13b4182c06df860454ff5f49473f575be5))

## v0.139.0 (2026-06-07)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`ac08883`](https://github.com/thiesgerken/carapace/commit/ac08883a465a1345fb249ac9751b262c578efac5))

- rm comment
  ([`ba461b9`](https://github.com/thiesgerken/carapace/commit/ba461b997651126aff730ed0aa298a3fbc0a3b87))

- fix: load .env in carapace-migrate so it matches the server
  ([`123c0e2`](https://github.com/thiesgerken/carapace/commit/123c0e24967a2fe8aae2985a0f1c003a4d704e8b))

  carapace-migrate upgrade builds config from env only (no config.yaml), but never called load_dotenv() — so a local .env with CARAPACE_DATABASE_URL worked for the server yet migrate fell back to the default SQLite under ./data and could touch the wrong DB. Load dotenv in the Typer callback.

  Caught by Bugbot on #218.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- chore: drop configurable knowledge_dir, always <data_dir>/knowledges
  ([`bc27b73`](https://github.com/thiesgerken/carapace/commit/bc27b7359bb1454e1fecb72b2965b17588fb8fc2))

  The knowledge_dir knob had no users (neither k3s nor docker-compose set it) and a relative CARAPACE_KNOWLEDGE_DIR resolved against CWD, not the data root — a footgun Bugbot flagged on #218. Remove the field/env var and always derive <data_dir>/knowledges via the existing resolve_knowledge_repos_dir.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: read subsection env at build_config() time, not import
  ([`8d33e14`](https://github.com/thiesgerken/carapace/commit/8d33e14da21f50934d5b6b4f4f641c7cc33cfed0))

  Config's BaseSettings sections were single instances created at class-definition (import) time, so any CARAPACE_* env loaded afterward — including via load_dotenv() in the server module — was ignored. Use default_factory so each section re-reads its env prefix when a Config is built (after load_dotenv, at build_config() call).

  Caught by Bugbot on #218.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- postgres secrets
  ([`cc281a1`](https://github.com/thiesgerken/carapace/commit/cc281a1d7553b101d0a59d04e7ccd1a8ccdb2bad))

- chore: remove config.yaml; operator config is env-only
  ([`3cc44ba`](https://github.com/thiesgerken/carapace/commit/3cc44ba7898601d082a9a988d013b25105a48a59))

  config.yaml was nearly vestigial after agent/sessions moved to the DB. The one real coupling was that data_dir/knowledge_dir resolved relative to the config file's *location*. Replace that with explicit env vars and drop the file.

  - CARAPACE_DATA_DIR (abs, default ./data) is the data root; knowledge_dir
    derives as <data_dir>/knowledges (CARAPACE_KNOWLEDGE_DIR overrides)
  - env-back the last file-only sections: AuthConfig + NotificationsConfig become
    BaseSettings (CARAPACE_AUTH_*, CARAPACE_NOTIFICATIONS_*, nested via __), so
    cookie.secure / vapid_subject etc. stay settable
  - replace load_config/get_config_path/get_data_dir with build_config(); no file
    read, no empty-{} file creation
  - swap CARAPACE_CONFIG -> CARAPACE_DATA_DIR in compose + helm; update docs/tests

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- chore: remove YAML→SQL migration cruft
  ([`6662604`](https://github.com/thiesgerken/carapace/commit/6662604dacd643ace9815ee4566c039265ae23da))

  All deployments have migrated to the SQL backend, so the one-time migration scaffolding is now dead weight (and a footgun: an importer that can --purge live tables; a boot-time config.yaml rewrite).

  - delete the carapace-migrate import-yaml importer + its tests; keep upgrade
  - drop boot-time seed_from_config/is_seeded and the config.yaml strip machinery
  - a fresh DB now starts empty and boots on AgentConfig code defaults until an
    admin configures the catalog via the Platform UI
  - config.yaml stays as a thin optional operator file

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### ✨ Features


- ✨ feat: env-only operator config (drop config.yaml)
  ([`06a51df`](https://github.com/thiesgerken/carapace/commit/06a51df251d908a32b11e11d039f86fe09aab815))

  Release marker for the config.yaml removal (PRs #216 + #219). The feature commits used Conventional-Commit text without a gitmoji, so the emoji-based semantic-release parser saw nothing releasable. This ✨ commit cuts the minor.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- ✨ feat: env-only operator config (drop config.yaml)
  ([`54819a8`](https://github.com/thiesgerken/carapace/commit/54819a87480364548da8733523d83ef45ec4b26e))

  Release marker for the config.yaml removal (PRs #216 + #219): those merged with Conventional-Commit text and no gitmoji, so the emoji-based semantic-release parser found nothing releasable and the version/docker/helm jobs were skipped.

  Also set commit_parser_options.ignore_merge_commits = false so future "✨Merge pull request …" commits drive the release on their own.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- ✨Merge pull request #219 from thiesgerken/chore/drop-config-yaml
  ([`26a47b9`](https://github.com/thiesgerken/carapace/commit/26a47b920782ec63a0c6f6c91273496824a7b74a))

- ✨ feat: remove config.yaml (env-only operator config)
  ([`26a47b9`](https://github.com/thiesgerken/carapace/commit/26a47b920782ec63a0c6f6c91273496824a7b74a))

- ✨Merge pull request #216 from thiesgerken/chore/remove-migration-cruft
  ([`1833981`](https://github.com/thiesgerken/carapace/commit/1833981a454afe845174b88bac3ceea0ec2c5924))

### 🐛 Bug Fixes


- 🐛 chore: remove YAML→SQL migration cruft
  ([`1833981`](https://github.com/thiesgerken/carapace/commit/1833981a454afe845174b88bac3ceea0ec2c5924))

## v0.138.3 (2026-06-06)


### 🐛 Bug Fixes


- 🐛 fix: decrease chunk sizes for k8s
  ([`1654bb1`](https://github.com/thiesgerken/carapace/commit/1654bb1ed83d9200ccd9404268711f64e5335d5c))

## v0.138.2 (2026-06-06)


### ⬆️ Dependencies


- ⬆️ fix: force release
  ([`c5c4d43`](https://github.com/thiesgerken/carapace/commit/c5c4d433d0ca4239b734b6ea667ef2b4598797b2))

### ✨ Features


- ✨Merge pull request #208 from thiesgerken/feature/git-sync-transparency
  ([`d226de6`](https://github.com/thiesgerken/carapace/commit/d226de686f01d862845393750b3fa7ca2b869304))

- ✨ feat: surface sandbox/knowledge git state in UI
  ([`d226de6`](https://github.com/thiesgerken/carapace/commit/d226de686f01d862845393750b3fa7ca2b869304))

### Other


- Merge remote-tracking branch 'refs/remotes/origin/feature/git-sync-transparency' into feature/git-sync-transparency
  ([`1a8b18c`](https://github.com/thiesgerken/carapace/commit/1a8b18cce775f677df028e64743c48453b2051fb))

- fix: delete warning no longer trusts stale cached sandbox status
  ([`c213f20`](https://github.com/thiesgerken/carapace/commit/c213f20cd0eeb87273b83ebbcdc5553fa45c85c0))

  The unpushed-commit delete guard only ran when the cached session-row snapshot showed running, but non-active rows can be stale (stopped in the list while actually running), skipping the warning. The backend status check is boot-safe (returns running=false / no counts when stopped), so query it directly for every delete instead of gating on the cached row.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- Merge branch 'main' into feature/git-sync-transparency
  ([`c0e2996`](https://github.com/thiesgerken/carapace/commit/c0e29964e6a97bf90459dafff4570ffc0a8ed36d))

- fix: address bugbot review (snapshot, push result, stale error, hidden panel)
  ([`79c4e9f`](https://github.com/thiesgerken/carapace/commit/79c4e9fa53563c7589c83829ea9fbe72c265fb48))

  - _running_container re-attaches via the lifecycle directly instead of
    self.ensure_session, which wrote a transient "pending" sandbox snapshot
    on a cold cache — a read-only git status no longer flips UI state or
    skips the delete unpushed-commit warning.
  - push_to_remote now returns success; push_for_user reports ok=false when
    the external push fails (it previously only logged), so the UI no longer
    shows a green confirmation for a failed push.
  - Clear a stale error outcome on the next successful status refresh.
  - Render the global git panel unless the remote is known-unconfigured, so a
    failed initial status fetch still shows the error and a refresh control.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: move git command output into status tooltip
  ([`9bf4486`](https://github.com/thiesgerken/carapace/commit/9bf4486890b0d50e5de9d4af50325680fd630c20))

  The raw pull/push/git output was dumped inline in the small panel, unformatted and cramped. Show only a short error label on failure; the full command output is now the tooltip on the status line ("Up to date" / ahead-behind counts), on success and failure alike.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: align ahead/behind counts and pull/push buttons
  ([`8d13ea9`](https://github.com/thiesgerken/carapace/commit/8d13ea969772d5694f023bab2de0a86b0b9b10da))

  The counts read ↑ahead ↓behind while the buttons read pull, push, so pull/push sat under the wrong counts. Reorder the counts to ↓behind ↑ahead (pull↔behind, push↔ahead) and color push amber to match the ahead count (pull already matches behind in sky).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat: show account dot only when knowledge remote has changes to pull
  ([`98513ed`](https://github.com/thiesgerken/carapace/commit/98513edf4f5fded95857d134de1949317afb5442))

  Re-add the global git status dot on the account avatar, but render it only when the server repo is behind the remote (behind > 0), with a tooltip stating how many commits there are to pull.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: detect running sandbox for git status; drop account-menu dot
  ([`c25a786`](https://github.com/thiesgerken/carapace/commit/c25a786269e21a6f3e10ad9e526581b17fb38ffb))

  - sandbox_git_status reported "not running" for a running sandbox whose
    container wasn't in the in-memory _sessions cache (e.g. after a server
    restart). _running_container now also checks the runtime for an existing
    running sandbox and adopts it via ensure_session, which re-attaches
    without booting — matching how the snapshot detects "running".
  - Remove the status dot from the account avatar per request; the global
    git info + controls live solely in the account-menu popup.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- refactor: move global git into account menu + add tooltips
  ([`ff42259`](https://github.com/thiesgerken/carapace/commit/ff42259f2108bb27008e048c9ac8e06069f199b9))

  - Replace the always-visible global git panel in the sidebar footer with a
    small status dot on the account avatar (in sync / out of sync / busy) and
    the full pull/push panel inside the account menu popup. Keeps the sidebar
    uncluttered. Status is fetched once via a shared useGlobalGit hook.
  - Add explanatory tooltips to both the session (B1) and global (B2)
    controls: a hover description on the section label and per-button titles
    spelling out what pull/push do and to/from where.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: address bugbot review (sandbox boot, stale fetch, shift-skip)
  ([`ea8ed0c`](https://github.com/thiesgerken/carapace/commit/ea8ed0c246f8972a2ca62f3ffc5b4009744e7d82))

  - sandbox_git_status/unpushed_count no longer boot a stopped sandbox:
    add _running_container (checks is_running without ensure_session) and
    return running=False instead. Mirrors the delete flow. UI shows a
    "Sandbox not running" label and disables actions.
  - sandbox_git_status now reports fetched=False when git fetch fails, so a
    failed fetch can't masquerade as up-to-date with stale local behind.
  - Shift+click delete now skips the unpushed-commits warning too, matching
    the documented confirm-skip behavior (skipUnpushedWarning threaded from
    the sidebar through onDelete).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: keep pull/push result notice after refresh
  ([`99b0eb2`](https://github.com/thiesgerken/carapace/commit/99b0eb220535927589578e25f072759cb4870961))

  runAction set a success/denial notice then called refresh, which clears the notice on entry, so users never saw confirmation or denial text. Set the notice after refresh completes instead.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- Merge remote-tracking branch 'origin/main' into feature/git-sync-transparency
  ([`4df9603`](https://github.com/thiesgerken/carapace/commit/4df9603588179dcbcf4a9f0796066e18d5b33a03))

- fix: clear global git counts on status fetch error
  ([`e072d7c`](https://github.com/thiesgerken/carapace/commit/e072d7c1cf7e9f624768dec38e69047a932f1c35))

  GlobalGitControls left stale ahead/behind counts visible after a failed status fetch, misstating sync state and keeping pull/push enabled. Clear counts in the catch block so only the error notice shows.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- Merge remote-tracking branch 'origin/main' into feature/git-sync-transparency
  ([`90035d3`](https://github.com/thiesgerken/carapace/commit/90035d3f4c7623f2dc60cbdda6c15d887d7c4302))

  # Conflicts: #	tests/test_session_engine_usage.py

- fix: address bugbot review on git-sync PR
  ([`49330bb`](https://github.com/thiesgerken/carapace/commit/49330bb5403ff289acd9e6efc34c581428d55f7c))

  - Remove obsolete /pull slash-command test (command no longer exists);
    skill-cache invalidation now lives in KnowledgeGitRuntime.pull_for_user.
  - Global pull/push endpoints now report ok=false when no remote is
    configured (pull_for_user/push_for_user return (ok, message)); add
    push_for_user and a regression test.
  - git-sync UI: distinguish a status-fetch error from "no remote" via an
    explicit emptyLabel, so a failed fetch no longer shows the no-remote
    label alongside the error notice.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat: surface sandbox/knowledge git state in UI
  ([`35d90bc`](https://github.com/thiesgerken/carapace/commit/35d90bc009f01c35a64cd39068d4e97f5e157e0d))

  Replace the per-session /pull and /push slash commands with visible UI controls across the two git boundaries:

  - B1 (sandbox /workspace <-> backend repo): ahead/behind indicator plus
    pull/push in the chat inspector, run via _exec_in_container so they
    never appear as agent tool calls. Push stays sentinel-gated.
  - B2 (backend per-user repo <-> external remote): global ahead/behind
    indicator with pull/push in the sidebar footer, hidden when no remote
    is configured. Replaces the removed /pull /push slash commands.
  - Warn before deleting a session whose sandbox has unpushed commits
    (checked only when the sandbox is already running).

  Adds GitStore.remote_status, KnowledgeGitRuntime status/pull helpers, SandboxManager git methods, REST endpoints, and the git-sync frontend component with en/de strings.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

## v0.138.1 (2026-06-06)


### ⬆️ Dependencies


- ⬆️ chore: upgrade to pg18
  ([`f84b836`](https://github.com/thiesgerken/carapace/commit/f84b8365c42eb165eaf6ca6500dffeab89c25e2b))

## v0.138.0 (2026-06-06)


### ✨ Features


- ✨Merge pull request #212 from thiesgerken/feature/config-to-db
  ([`0e8a768`](https://github.com/thiesgerken/carapace/commit/0e8a768924da2bed73a0d3a42d193f2715fb4780))

- ✨ feat: move runtime platform config to the database
  ([`0e8a768`](https://github.com/thiesgerken/carapace/commit/0e8a768924da2bed73a0d3a42d193f2715fb4780))

- ✨ feat: make carapace.log_level / logfire_token env-configurable
  ([`4b2513d`](https://github.com/thiesgerken/carapace/commit/4b2513d06213f71397aa8e60f0629afc80bc2bf7))

  CarapaceConfig is now a BaseSettings (env_prefix CARAPACE_), so CARAPACE_LOG_LEVEL / CARAPACE_LOGFIRE_TOKEN actually take effect — the Helm chart already injected CARAPACE_LOG_LEVEL but the plain-model backend silently ignored it. env wins over any value still in config.yaml's `carapace:` section, so the section (and the whole file) can be dropped.

  - docker-compose: pass CARAPACE_LOG_LEVEL through.
  - docs: note the env path + that the section is optional.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- ✨ feat: strip DB-managed sections from config.yaml after seeding
  ([`6403e13`](https://github.com/thiesgerken/carapace/commit/6403e1348c6400e71f373d14123d469f6e5d611e))

  After the one-time seed, remove the now DB-authoritative agent/sessions sections from config.yaml so an admin editing them on disk can't silently no-op. Keeps a single stable backup (config.yaml.pre-db-migration.bak) — fixed name, no timestamped-.bak pileup — and prepends a note explaining the move. Idempotent: never overwrites an existing backup, runs only when the seed actually seeds.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- ✨ feat: move runtime platform config to the database
  ([`36c4060`](https://github.com/thiesgerken/carapace/commit/36c4060a8bebdfbf927b55c3fe41e43f1fcb7d1e))

  Model catalog and scalar agent/sessions settings now live in `models` + `platform_settings` tables instead of config.yaml. The admin Platform UI persists to the DB in a transaction; the config.yaml read-modify-write (and its .bak pileup) is gone. config_writable is always true.

  - New PlatformSettingsStore: catalog CRUD, section upsert, idempotent
    seed_from_config, agent/sessions assembly + Config overlay.
  - Lifespan seeds once from config.yaml on first boot, then overlays so the
    in-memory Config reflects the DB. agent/sessions YAML sections become
    seed-only; operator/bootstrap config stays env/file.
  - Alembic 0002 (models + platform_settings); JSONB on Postgres.
  - Relocated secret_to_dict/model_entry_to_dict to models/config.py.
  - Docs: chart README + kubernetes.md note the DB-backed seed-once behavior.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### Other


- Merge remote-tracking branch 'origin/main' into feature/config-to-db
  ([`bbf196e`](https://github.com/thiesgerken/carapace/commit/bbf196e6c6ce7f02c00a929f95093440a8b85e32))

### 🐛 Bug Fixes


- 🐛 fix: harden platform seed against races + retry config strip
  ([`1967cfc`](https://github.com/thiesgerken/carapace/commit/1967cfc337d6b2af5302da76f72b3d5db74e69ac))

  Address Bugbot findings on #212:

  - Concurrent seed: seed_from_config now catches IntegrityError from a
    racing winner and returns False (DB is populated either way) instead of
    aborting lifespan startup. Add is_seeded().
  - config.yaml strip: run every boot when the DB is seeded (idempotent
    no-op when the sections are absent) instead of only on the boot that
    seeded, so a strip that failed once is retried. This also closes the
    "empty catalog revives YAML" path — post-seed config.yaml has no agent
    section, so the assemble fallback can only yield defaults.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- 🐛 fix: dedup duplicate model ids before persisting catalog
  ([`46838d0`](https://github.com/thiesgerken/carapace/commit/46838d0aed0a36f6f073aba727d2ef59dc5ae2d4))

  A config (or admin save) listing the same model_id twice was valid before (last wins via agent_available_model_entries) but the per-entry insert into the models table PK-conflicted on seed/save. Collapse by model_id first.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

## v0.137.1 (2026-06-06)


### Other


- Merge pull request #213 from thiesgerken/renovate/pin-dependencies
  ([`431085d`](https://github.com/thiesgerken/carapace/commit/431085d8d7e237b0227517c75c459ccf91ad7a5c))

- Merge pull request #214 from thiesgerken/renovate/docker.io-library-postgres-18.x
  ([`b046341`](https://github.com/thiesgerken/carapace/commit/b046341324ebedb11a918e585ac90d314dd1969e))

### ⬆️ Dependencies


- ⬆️ chore: Pin dependencies
  ([`431085d`](https://github.com/thiesgerken/carapace/commit/431085d8d7e237b0227517c75c459ccf91ad7a5c))

- ⬆️ chore: Pin dependencies
  ([`de8592e`](https://github.com/thiesgerken/carapace/commit/de8592e7495261d798948b06cf3ef97b9c5deb40))

- ⬆️ chore: upgrade docker.io/library/postgres Docker tag to v18
  ([`b046341`](https://github.com/thiesgerken/carapace/commit/b046341324ebedb11a918e585ac90d314dd1969e))

- ⬆️ chore: upgrade docker.io/library/postgres Docker tag to v18
  ([`84c4d15`](https://github.com/thiesgerken/carapace/commit/84c4d1537071ae98af26cd4198106f0e1b4d1490))

## v0.137.0 (2026-06-06)


### ✨ Features


- ✨Merge pull request #209 from thiesgerken/feature/sql-backend
  ([`4d6004f`](https://github.com/thiesgerken/carapace/commit/4d6004fc1670106b5b2bf02c65535d63940ae7d6))

- ✨ feat: SQL backend (SQLAlchemy 2.0 + Alembic)
  ([`4d6004f`](https://github.com/thiesgerken/carapace/commit/4d6004fc1670106b5b2bf02c65535d63940ae7d6))

- ✨ feat(helm): bundled Postgres + DB backend options + migration docs
  ([`3f1221d`](https://github.com/thiesgerken/carapace/commit/3f1221d61703faa18af5ae3f85f9b15e7b207c73))

  The chart had no database resources after the SQL-backend switch. Add:
  - Bundled in-cluster PostgreSQL (Deployment + Service + PVC + Secret),
    enabled by default. Password auto-generates into the <release>-postgres
    Secret and is reused across upgrades via lookup; overridable via
    postgres.auth.password / existingSecret.
  - database.url for an external DB; SQLite-on-data-PVC fallback when
    postgres is disabled and no url is set. Server wires CARAPACE_DATABASE_URL
    via carapace.databaseUrlEnv helper.
  - chart README "Database" section + docs/kubernetes.md pointer covering
    backend selection and the one-shot YAML import
    (kubectl exec deploy/<release>-server -- carapace-migrate import-yaml).
  - docker-compose: comment documenting the same import command.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- ✨ feat: SQL backend (SQLAlchemy 2.0 + Alembic)
  ([`6ee74ee`](https://github.com/thiesgerken/carapace/commit/6ee74ee47691aa91cec4e6bf59f1390ef7528262))

  Move the six file/YAML storage targets into a relational database (PostgreSQL primary, SQLite for dev/test) behind the existing store classes. Sync SQLAlchemy keeps every store method signature unchanged, so call sites are untouched.

  Migrated: per-session data (state, history, events, usage, llm_requests, audit, sandbox snapshot, sandbox token), users.yaml, jobs.yaml, auth sessions, notification subscriptions. Config, secrets, knowledge git repos and session workspace/ dirs stay on disk.

  - New carapace.database package: base (portable JSON + tz-aware
    datetime), models (11 tables), engine (sync factory, SQLite WAL+FK
    PRAGMA, run_migrations), Alembic + 0001 initial migration.
  - Stores swap YAML I/O for ORM; load-modify-write becomes single
    UPDATE/DELETE (kills the jobs lost-update race, drops the auth RLock).
  - Events/audit are append rows; history/usage/llm_log are JSON blobs.
  - One-shot importer + `carapace-migrate import-yaml` (idempotent,
    --dry-run, --purge); migrations auto-run on server startup.
  - docker-compose gains a postgres service.

  BigInteger PKs use an Integer variant on SQLite (autoincrement); BIGSERIAL on Postgres. Verified on both backends; 903 tests pass.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### Other


- add comment regarding locking inter-process
  ([`d88ab72`](https://github.com/thiesgerken/carapace/commit/d88ab722b694874fea6bc83df47f8369c8e72bba))

- Merge remote-tracking branch 'origin/main' into feature/sql-backend
  ([`b3a5988`](https://github.com/thiesgerken/carapace/commit/b3a59885cf6579ac5db8ebe94cb26d4235ba2ed1))

- Merge remote-tracking branch 'origin/main' into feature/sql-backend
  ([`7278db8`](https://github.com/thiesgerken/carapace/commit/7278db82678c7a9d6c6f5393fef5115de8fd41b4))

### 🐛 Bug Fixes


- 🐛 fix(helm): inject Postgres password via PGPASSWORD, not the URL
  ([`d255462`](https://github.com/thiesgerken/carapace/commit/d255462b6143c28757495d17dd35525b0e81a330))

  Address Bugbot: the generated CARAPACE_DATABASE_URL interpolated the password without URL-encoding, so a user-supplied postgres.auth.password (or existingSecret value) containing @ : / % could break parsing/auth.

  Drop the password from the SQLAlchemy URL and inject it as PGPASSWORD from the same Secret; libpq (psycopg) applies it when the URL omits the password — no URL-encoding needed for any password.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- 🐛 fix: handle sandbox-token insert race and delete_session rmtree failure
  ([`4bf8117`](https://github.com/thiesgerken/carapace/commit/4bf8117179bf055aef0fbd32916642bd4adf2edb))

  Address Bugbot review on #209:
  - get_or_create_token: a concurrent writer could insert the same
    sandbox_tokens PK between the existence check and our INSERT, raising
    IntegrityError. Catch it and reuse the persisted token.
  - delete_session: the DB row (source of truth) is deleted first; a failing
    workspace rmtree now only logs a warning instead of propagating, leaving
    harmless orphan files for the sandbox orphan cleanup rather than a
    half-completed delete.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- 🐛 fix: make importer --purge atomic and clear all tables
  ([`c0ce7a2`](https://github.com/thiesgerken/carapace/commit/c0ce7a2e20bb49f2fe351bcfa0f294ddcc87ea79))

  Address Bugbot review on #209:
  - Purge ran in a separate committed transaction before import; a later
    validation/IO error left the DB emptied with no rollback. Move the
    truncate into the same transaction (flush, not commit) so any failure
    — or dry_run — rolls the purge back too.
  - Purge skipped `users` and `auth_sessions`, so a purge-and-reimport
    wiped sessions but kept stale auth rows and re-skipped YAML users as
    "already existing". Add both tables to the truncate set.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### ♻️ Refactoring


- ♻️ refactor: typed Pydantic JSON columns + address review
  ([`79d9239`](https://github.com/thiesgerken/carapace/commit/79d9239a6848193ac101b4211ea1cbb321a4514f))

  Address PR #209 review comments:
  - Typed JSON columns: add PydanticJson / ModelMessagesJson TypeDecorators
    so columns read as Mapped[SessionState], Mapped[UsageTracker],
    Mapped[JobDefinition], Mapped[UserConfig], Mapped[NotificationSubscription],
    Mapped[SessionSandboxSnapshot], Mapped[list[ModelMessage]]. Stores now
    store/read the models directly — the scattered model_dump/model_validate
    calls are gone. Free-form event/audit payloads and roles stay JSON with a
    comment. (state/sandbox_snapshot columns are self-documenting now.)
  - Move SessionSandboxSnapshot to sandbox/snapshot.py (db-free) to break the
    models <-> sandbox.state import cycle; state.py re-exports it.
  - sessions.state is now nullable (the rare owner-before-state placeholder
    stores NULL instead of {}).
  - Default SQLite path is resolved under data_dir (resolve_database_url), so
    it lands beside the data tree instead of the process CWD.
  - Drop the lazy `import yaml` in session/manager.py.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

## v0.136.7 (2026-06-06)


### Other


- Merge pull request #211 from thiesgerken/fix/ws-reconnect-storm
  ([`73ab526`](https://github.com/thiesgerken/carapace/commit/73ab526485f20c5fa0259bcdb8e69fa387e2be5f))

### 🐛 Bug Fixes


- 🐛 fix: back off websocket reconnects when connection flaps
  ([`73ab526`](https://github.com/thiesgerken/carapace/commit/73ab526485f20c5fa0259bcdb8e69fa387e2be5f))

- 🐛 fix: back off websocket reconnects when connection flaps
  ([`78c46b5`](https://github.com/thiesgerken/carapace/commit/78c46b5b6ce6c2b059ca95b752ebec361e7c8420))

  Reset the reconnect backoff only after the socket stays open past STABLE_CONNECTION_MS instead of immediately on open. A backend that comes back half-ready (accepts the socket then drops it) no longer triggers a tight 500ms reconnect loop, which re-rendered chat-view repeatedly and looked like a rapid reload cycle.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

## v0.136.6 (2026-06-06)


### 💄 UI/UX


- 💄 ui: confirm for model deletion
  ([`f0f8d4a`](https://github.com/thiesgerken/carapace/commit/f0f8d4a15cbbe4cf892ecc4c92250e683a8bd467))

### Other


- Merge pull request #210 from thiesgerken/fix/usage-mobile-overflow
  ([`dff547b`](https://github.com/thiesgerken/carapace/commit/dff547b04e6d85ba7d88375685678228f9730c21))

- fix: confine /usage tables to horizontal scroll on mobile
  ([`5659f81`](https://github.com/thiesgerken/carapace/commit/5659f816513891a6615fb17e401a0016f834f6c4))

  Usage tables lacked an overflow wrapper, so wide content scrolled the whole app sideways. Wrap them in overflow-x-auto like the /models command.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: add track_activity to _generate_title protocol stub
  ([`ac9f6a5`](https://github.com/thiesgerken/carapace/commit/ac9f6a566b2478150aa70fd96d63693b3b521a69))

  pyrefly flagged the SessionTurnHost protocol stub missing the new keyword argument used by the auto-title scheduler.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat: run auto-titling off the session busy path
  ([`6c65d81`](https://github.com/thiesgerken/carapace/commit/6c65d8105ff358d3aafddbdc60bfc9bd2a0054e4))

  Auto-title generation ran fire-and-forget but still wrapped its LLM call in llm_request_recording, which set active.llm_request_state and broadcast on_llm_activity -- making the session look busy (and clobbering a concurrent turn's activity state).

  Add track_activity flag to llm_request_recording / _generate_title; the auto-title scheduler passes track_activity=False so the background title keeps usage + audit-log recording but never touches or broadcasts the busy state. /retitle and /model title stay visible/blocking.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛fix: confine /usage tables to horizontal scroll on mobile
  ([`dff547b`](https://github.com/thiesgerken/carapace/commit/dff547b04e6d85ba7d88375685678228f9730c21))

- 🐛Merge pull request #207 from thiesgerken/feature/background-titling
  ([`153c3c1`](https://github.com/thiesgerken/carapace/commit/153c3c12de4ec0c53bc8e1eaf17186489bf906a1))

- 🐛 fix: Run auto-titling off the session busy path
  ([`153c3c1`](https://github.com/thiesgerken/carapace/commit/153c3c12de4ec0c53bc8e1eaf17186489bf906a1))

## v0.136.5 (2026-06-05)


### Other


- Merge pull request #206 from thiesgerken/renovate/all-routine-dependencies
  ([`aca3754`](https://github.com/thiesgerken/carapace/commit/aca3754e061b8e3ac472a0edf8eff025ce199b50))

- fix: upload progress + send_file sandbox-startup UI
  ([`31c68b2`](https://github.com/thiesgerken/carapace/commit/31c68b213e84e99c0fee977de72b0a3e021ead56))

  - AttachmentChip shows the upload percentage as soon as bytes stream
    (progress > 0), instead of staying on "Starting sandbox…" through a
    long cold-start upload
  - Add send_file to SANDBOX_STARTUP_TOOL_NAMES so the optimistic pending
    sandbox snapshot is applied when it runs against a stopped sandbox

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat: start sandbox on demand for file uploads
  ([`bd5b6fb`](https://github.com/thiesgerken/carapace/commit/bd5b6fbf5ecfdc7245d6b4c4ff9bf8a5453d7885))

  Drop the running-sandbox requirement for uploads now that a server-side blob is persisted. The upload endpoint calls ensure_session (warm-claim or cold-create, idempotent when running) instead of returning 409. Frontend enables the attach control regardless of sandbox state and shows a snapshot-driven "Starting sandbox…" label until the sandbox is running.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- refactor: simplify send_file function by removing title parameter
  ([`982d3ad`](https://github.com/thiesgerken/carapace/commit/982d3ad4746e01cb1d8026ae63ffe57d4cd93c03))

- show path as tooltip
  ([`5e6a2e5`](https://github.com/thiesgerken/carapace/commit/5e6a2e5e9f32b9ab62d0ae0a7bffa6f0147d7096))

- assign sandbox id lazily
  ([`9149cbd`](https://github.com/thiesgerken/carapace/commit/9149cbd20aad44c571783b5315ed759cd9ba5d0e))

- fix: gate send_file + dedupe size formatter
  ([`b0b9351`](https://github.com/thiesgerken/carapace/commit/b0b935173bbcc0e09dfb08c4dcbca65f89ab0aa3))

  - send_file now runs through the security gate and skill-activation
    check like the read tool, and is added to SAFE_TOOLS so it's
    auto-allowed by the safe list (returns ToolDenied on denial)
  - Replace the duplicate formatFileSize with the existing formatBytes
    util so file sizes render consistently across the UI

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- Merge remote-tracking branch 'origin/main' into feature/file-downloads
  ([`aaee0c1`](https://github.com/thiesgerken/carapace/commit/aaee0c1287938d8cf94148f254cb3b6a2e9c4ef1))

- Merge remote-tracking branch 'origin/main' into feature/file-downloads
  ([`3b0f45b`](https://github.com/thiesgerken/carapace/commit/3b0f45b424f8c53cffb61a7d8b74cf293314cc5f))

- fix: remove orphan blob when upload fails
  ([`5d28c58`](https://github.com/thiesgerken/carapace/commit/5d28c58be70974435c508da154397930bc014af3))

  Any upload failure (size limit, write error, stopped sandbox, I/O) now unlinks the reserved persistent blob before raising, so no sidecar-less file is left under sessions/{id}/files/.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: address CI failure + Bugbot review
  ([`46f179e`](https://github.com/thiesgerken/carapace/commit/46f179e115e8f2782793f065618f4de082022d93))

  - Update test_upload_sandbox_file_streams_to_tmp for the extended upload
    response (file_id/size/mime)
  - download_tmp_file raises UploadError on a short read instead of
    returning the full stat size (would mislabel truncated blobs)
  - FilePreview keys the blob URL by fileId so a stale preview is never
    shown while the next image loads

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat: persist uploads + inline image/size for both directions
  ([`8304c35`](https://github.com/thiesgerken/carapace/commit/8304c35567be2759c4df2989be7c01e1e2678d12))

  - Uploaded files are now copied into persistent per-session storage at
    upload time (tee while streaming into the sandbox), so they stay
    viewable/downloadable after the sandbox is gone. Upload response and
    Attachment carry file_id/size/mime.
  - Shared FilePreview component (extracted from the send_file row): inline
    image preview for images, name + size + download chip otherwise.
  - User message bubble renders FilePreview for uploaded attachments;
    upload chips and both preview chips show file size after the name.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat: file downloads via send_file tool
  ([`fa216d4`](https://github.com/thiesgerken/carapace/commit/fa216d46840d7527d44617be58a887ee6584e75d))

  Add the reverse of file uploads: a send_file agent tool that exposes a file or image to the user for view/download in the chat.

  - send_file(path, title?) copies the file out of the ephemeral sandbox
    into persistent per-session storage (data_dir/sessions/{id}/files), so
    it survives sandbox scale-down and history replay
  - SandboxManager.download_tmp_file streams bytes out via tail|base64
  - GET /sessions/{id}/files/{file_id} serves persisted files (inline or
    ?download=1), works with the sandbox stopped; file_id validated as hex
  - SentFileInfo threaded through tool_result events, websocket, history
  - Frontend: send_file row expanded by default, inline image preview +
    download chip; new sentFile/sendFile labels (en/de)

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`aca3754`](https://github.com/thiesgerken/carapace/commit/aca3754e061b8e3ac472a0edf8eff025ce199b50))

- ⬆️ chore: upgrade all routine dependency updates
  ([`4228b9a`](https://github.com/thiesgerken/carapace/commit/4228b9a6f0c72bb05dcb8a473f36890536cf8871))

### ✨ Features


- ✨Merge pull request #201 from thiesgerken/feature/file-downloads
  ([`3c15020`](https://github.com/thiesgerken/carapace/commit/3c15020470097eb7bd13f4fd10637ec51ae362e9))

- ✨ feat: file downloads via send_file tool
  ([`3c15020`](https://github.com/thiesgerken/carapace/commit/3c15020470097eb7bd13f4fd10637ec51ae362e9))

## v0.136.4 (2026-06-05)


### Other


- Merge pull request #205 from thiesgerken/renovate/all-routine-dependencies
  ([`f33b412`](https://github.com/thiesgerken/carapace/commit/f33b412d06a22f073f758b263e710de80eae6d17))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`f33b412`](https://github.com/thiesgerken/carapace/commit/f33b412d06a22f073f758b263e710de80eae6d17))

- ⬆️ chore: upgrade all routine dependency updates
  ([`2d9cba1`](https://github.com/thiesgerken/carapace/commit/2d9cba1ce82679e36c816f0f6911597e9e578795))

## v0.136.3 (2026-06-04)


### Other


- Merge pull request #204 from thiesgerken/renovate/all-routine-dependencies
  ([`6d50139`](https://github.com/thiesgerken/carapace/commit/6d50139b77b0f8d4a41cca1c9472d573bc582f07))

- fix: only clean up genuinely partial chunked writes
  ([`d418513`](https://github.com/thiesgerken/carapace/commit/d4185133f29cc014e356eff9edb2abdd09585bca))

  Address review: the previous cleanup ran `rm -f` on any multi-command failure, which could delete a pre-existing file when the first mkdir/truncate fails, or a fully-written file when the trailing chmod fails. Now only remove the file when a write fails after an earlier chunk already wrote (real partial state); make chmod a separate trailing command for multi-chunk writes so its failure never triggers cleanup. Single-chunk/credential writes stay one exec.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- Merge remote-tracking branch 'origin/main' into fix/upload-arg-too-long
  ([`10aa87d`](https://github.com/thiesgerken/carapace/commit/10aa87d5d441236453523c1ff3b356e72c2c2913))

  # Conflicts: #	src/carapace/sandbox/file_ops.py

- ui: pill switch for vision toggle
  ([`f3caacc`](https://github.com/thiesgerken/carapace/commit/f3caacc63355cc772e985c76712d60642dcb039c))

  Replace the raw checkbox with a SwitchRow-style pill toggle to match the rest of the settings UX.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat: vision toggle in platform model settings UI
  ([`f2d7adc`](https://github.com/thiesgerken/carapace/commit/f2d7adc6bfe5f0d63c05fea1b5bfc76cbf229c08))

  Surface the per-model `vision` flag through the admin platform settings: API (PublicPlatformModelEntry, PlatformModelEntryPatch, YAML round-trip) and the model editor UI (checkbox + summary badge, i18n en/de). Default stays false and is omitted from YAML when unset.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- docs: remove implemented image-input plan
  ([`84c845b`](https://github.com/thiesgerken/carapace/commit/84c845b50810997688e5f1f78cff133bc9bd94ac))

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat: inject images into vision-capable models via read tool
  ([`09240a1`](https://github.com/thiesgerken/carapace/commit/09240a12446ca14e5bc86e160d929cd498018911))

  Add per-model `vision` config flag. When the active model supports image input, a plain `read(path)` on a raster image (png/jpg/jpeg/gif/webp) returns the image itself as a multimodal tool result instead of the binary stub. Passing `offset`/`limit` forces a text read (SVG/source escape hatch); SVG and other text-based formats always read as text. Non-vision models keep the previous text-only behavior, and the tool description switches per model.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: remove partial file when a multi-chunk write fails
  ([`5c65914`](https://github.com/thiesgerken/carapace/commit/5c659141a14d08c95c0bf1b05386762502ec7610))

  A multi-chunk write truncates on the first command and appends on the rest, so a mid-stream failure could leave a truncated file. Clean it up like upload_tmp_file. Single-command writes (incl. folded-chmod credential writes) stay atomic and are left untouched.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: chunk file writes to avoid "Argument list too long"
  ([`029b748`](https://github.com/thiesgerken/carapace/commit/029b7485cfdd698cc38f750b80da0c75928a911f))

  file_write/file_write_in_container inlined the whole base64 payload as one shell argument, so a large agent `write` (or credential materialization) could exceed Linux MAX_ARG_STRLEN (128 KiB) and fail. Stream the content in 64 KiB base64 chunks (truncate-then-append), folding any chmod into the last command so single-chunk writes stay one exec (unchanged behavior for credentials).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: shrink upload chunk to avoid "Argument list too long"
  ([`553bb9e`](https://github.com/thiesgerken/carapace/commit/553bb9e073e6b524463f5cb41cfc49f3ba1933e2))

  Uploads stream each chunk as base64 inlined in a single shell argument (`printf %s <b64> | base64 -d`). At 256 KiB per chunk the base64 (~341 KB) exceeds Linux MAX_ARG_STRLEN (128 KiB), so any upload over ~96 KiB — e.g. a typical JPEG — failed with "Argument list too long". Drop the chunk to 64 KiB (~85 KiB base64) and add a regression test bounding the inlined arg length.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`6d50139`](https://github.com/thiesgerken/carapace/commit/6d50139b77b0f8d4a41cca1c9472d573bc582f07))

- ⬆️ chore: upgrade all routine dependency updates
  ([`b025e9c`](https://github.com/thiesgerken/carapace/commit/b025e9c7a1fabf213b3c0cdf96f260ccaa8505ff))

### 🐛 Bug Fixes


- 🐛Merge pull request #203 from thiesgerken/fix/upload-arg-too-long
  ([`4318d96`](https://github.com/thiesgerken/carapace/commit/4318d969c1a7877a91ad2319540ab59a3faaeb5d))

- 🐛 fix: "Argument list too long" for large base64-inlined writes & uploads
  ([`4318d96`](https://github.com/thiesgerken/carapace/commit/4318d969c1a7877a91ad2319540ab59a3faaeb5d))

### ✨ Features


- ✨Merge pull request #202 from thiesgerken/feature/multimodal-input
  ([`b7e1fa2`](https://github.com/thiesgerken/carapace/commit/b7e1fa273c4dbb0552ae87cd8ddd47d2c0576086))

- ✨ feat: image input via the read tool
  ([`b7e1fa2`](https://github.com/thiesgerken/carapace/commit/b7e1fa273c4dbb0552ae87cd8ddd47d2c0576086))

## v0.136.2 (2026-06-04)


### Other


- Merge pull request #191 from thiesgerken/renovate/lock-file-maintenance
  ([`3e7d0c2`](https://github.com/thiesgerken/carapace/commit/3e7d0c2c7d8f1462cea712ca04648ca253e67b93))

- Merge pull request #200 from thiesgerken/renovate/all-routine-dependencies
  ([`e65c723`](https://github.com/thiesgerken/carapace/commit/e65c723c9da6c7463c98fa0e5db77b94b1cfe44f))

- fix: forward file attachments over Matrix cross-channel
  ([`093369d`](https://github.com/thiesgerken/carapace/commit/093369de5446d37ba0c2828cf288b41c82571f9f))

  Matrix on_user_message ignored attachments, so web-UI uploads showed only the text (or an empty body for attachment-only sends). Append file names and their /tmp paths, and skip sending when there's nothing to show.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: address Bugbot review on file uploads
  ([`63a9472`](https://github.com/thiesgerken/carapace/commit/63a9472bfe9c9dfb51ea4ef936d21146e7fded36))

  - retry_latest_turn: re-pass stored attachments so retries keep the preamble
  - websocket: only accept client attachment paths under /tmp
  - upload endpoint: reject archived sessions (409), matching up/down/wipe
  - chat-view: queued attachment-only sends show the banner and block re-queue
  - tests for retry attachment retention and archived upload rejection

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- Merge branch 'main' into feature/file-uploads
  ([`d6e59ed`](https://github.com/thiesgerken/carapace/commit/d6e59ed58405bf84159d726fcc6b2c23938f84ff))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`ec4da93`](https://github.com/thiesgerken/carapace/commit/ec4da93ec5c80e8e6ac1aa6819facf2b3bf1ef0b))

### ⬆️ Dependencies


- ⬆️ chore: Lock file maintenance
  ([`3e7d0c2`](https://github.com/thiesgerken/carapace/commit/3e7d0c2c7d8f1462cea712ca04648ca253e67b93))

- ⬆️ chore: Lock file maintenance
  ([`1a05912`](https://github.com/thiesgerken/carapace/commit/1a059123a92d020f0809af3d8f7736a200b6afe9))

- ⬆️ chore: upgrade all routine dependency updates
  ([`e65c723`](https://github.com/thiesgerken/carapace/commit/e65c723c9da6c7463c98fa0e5db77b94b1cfe44f))

- ⬆️ chore: upgrade all routine dependency updates
  ([`af0567d`](https://github.com/thiesgerken/carapace/commit/af0567d0541a291da0096cd2036d7cc5ea11393a))

### ✨ Features


- ✨Merge pull request #199 from thiesgerken/feature/file-uploads
  ([`b59416c`](https://github.com/thiesgerken/carapace/commit/b59416cb73b2d357b74a2e49d8176096f234bd61))

- ✨ feat: Upload files to sandbox /tmp from chat input
  ([`b59416c`](https://github.com/thiesgerken/carapace/commit/b59416cb73b2d357b74a2e49d8176096f234bd61))

## v0.136.1 (2026-06-03)


### Other


- 📋 docs: remove done item from todo list
  ([`31fb8bd`](https://github.com/thiesgerken/carapace/commit/31fb8bd2e7a7f05429136a4911b17bc6df84f043))

- feat: upload files to sandbox /tmp from chat input
  ([`406ee50`](https://github.com/thiesgerken/carapace/commit/406ee508c927e4e064d271ebbf34e7e3139ac5db))

  Add file attachments to the chat composer. Files stream into the running sandbox's /tmp via chunked base64 appends (cross-runtime, no exec stdin), show as chips in the input, and on send the agent prompt gets a hidden preamble describing where each file landed. The user's bubble stays clean; only the LLM/history sees the preamble.

  - POST /api/sessions/{id}/sandbox/files (running-only, 50MB cap)
  - SandboxManager.upload_tmp_file with collision hashing
  - Attachment model threaded through turn; original text in events,
    augmented prompt in history.yaml
  - chat-input: attach button + drag-drop + paste, progress chips
  - tests for preamble, streaming write, and the endpoint

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### 🐛 Bug Fixes


- 🐛 fix: non-blocking warm-pool startup and longer readiness timeout
  ([`15314ff`](https://github.com/thiesgerken/carapace/commit/15314ffb639b58e6b58feed30bec65d371ea91db))

  API startup awaited the initial ensure_warm_pool, so the server only began serving after the pool was up. Provision the pool via the background _warm_pool_loop instead (first iteration runs immediately). Also raise the sandbox readiness timeout from 30s to 180s, since image pull and pod scheduling commonly exceed 30s.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

## v0.136.0 (2026-06-03)


### ✨ Features


- ✨Merge pull request #194 from thiesgerken/feature/warm-sandboxes
  ([`84464ae`](https://github.com/thiesgerken/carapace/commit/84464ae34cb45901c531c93a4585820bda5bd68a))

- ✨ feat: keep a pool of warm sandboxes
  ([`84464ae`](https://github.com/thiesgerken/carapace/commit/84464ae34cb45901c531c93a4585820bda5bd68a))

- ✨ feat: keep a pool of warm sandboxes
  ([`4d959f8`](https://github.com/thiesgerken/carapace/commit/4d959f8bfd9c5af2c3878de6ad769fa54d62678a))

### Other


- fix: shorten warm-pool sandbox id to fit 63-byte label limit
  ([`7e111f1`](https://github.com/thiesgerken/carapace/commit/7e111f18a86efbc3c2e16bdafe0c5cf782ef1c78))

  uuid4().hex (32 chars) made the StatefulSet name plus k8s's controller-revision-hash exceed the 63-byte label limit. Use a 12-hex-char random suffix (secrets.token_hex(6)) instead.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: migrate to pydantic-ai retries dict
  ([`873209a`](https://github.com/thiesgerken/carapace/commit/873209a16d6c5ec0f8d72a296bb71b73a5f41e86))

  Replace deprecated Agent(tool_retries=, output_retries=) with retries={'tools': , 'output': } (removed in pydantic-ai v2.0).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- refactor: random uuid ids for warm-pool sandboxes
  ([`20db501`](https://github.com/thiesgerken/carapace/commit/20db5014eb320eb0199d6257d34ff685d70cbc23))

  Sequential warm-N ids were recycled: if a claimed sandbox's StatefulSet was deleted out-of-band, the pool would recreate the same warm-N name and a stale session could reattach by name to a sandbox now owned by another session. Give pool members unique pool-<uuid4> ids that are never reused, and on reattach error out if a name-matched sandbox is not labelled for the requesting session (should never happen, but never hijack).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- refactor: key sandbox selector on sandbox id, session label = owner
  ([`9fb7c28`](https://github.com/thiesgerken/carapace/commit/9fb7c28f84d5678ffb376346e48f54b4bc65535d))

  The StatefulSet pod selector keyed on carapace.session, which is immutable, forcing pool members to be seeded with a fake session (the slot id, e.g. warm-1) and requiring a separate claimed-session label to track the real owner.

  Key the selector on carapace.sandbox (the stable, immutable identity) instead. Pool members are now created with no carapace.session; claiming one stamps carapace.session with the owning session id and clears carapace.pool. Drops the redundant carapace.claimed-session label and simplifies list_sandboxes.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: actually clear carapace.pool label on warm claim
  ([`dc1a32e`](https://github.com/thiesgerken/carapace/commit/dc1a32e8888191ae8af9e33b63def992e123800d))

  The claim merge-patch popped carapace.pool from the labels dict, but a merge patch only deletes a label when set to null — omitting the key leaves it. So claimed StatefulSets kept pool=true, list_pool_sandboxes counted them, the pool always looked full, and no replacement warm sandbox was created. Set the label to null explicitly and record the owning session via carapace.session / carapace.claimed-session.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- ci: push immutable per-commit PR image tags
  ([`ff43609`](https://github.com/thiesgerken/carapace/commit/ff436097d36ad6be6b9f994495baa892a5ef9137))

  PR images were tagged only with the mutable prN tag, which images default to via Chart.AppVersion. With pullPolicy IfNotPresent, a chart bump wouldn't re-pull the actual code. Also tag each image prN-<sha> and set the SHA chart's app-version to it, so pinning ArgoCD to the SHA chart version forces both a refetch and a re-pull.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: replenish warm pool in background after claim
  ([`b030130`](https://github.com/thiesgerken/carapace/commit/b03013049c44d8f66962b3fe594aca7d9e99e866))

  The post-claim/post-cold-create ensure_warm_pool was awaited inline, so session start blocked on the replacement pod's create + wait_for_ready (up to 30s) under _warm_claim_lock. Schedule it as a background task so the new warm sandbox starts provisioning immediately without delaying the session.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- ci: publish PR chart with commit-hash version
  ([`dfa692d`](https://github.com/thiesgerken/carapace/commit/dfa692d151bc6a5924715222c8dbbca6f585e5ce))

  The -pr.N chart version is identical on every push, so ArgoCD won't refetch. Also package and push an immutable -pr.N.<sha> version; pin ArgoCD targetRevision to it to force a refresh.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat(chart): expose logLevel value
  ([`ac989dd`](https://github.com/thiesgerken/carapace/commit/ac989ddf1e508047f2e706d7943246fc10f992f9))

  Add a first-class logLevel Helm value (default info) wired to CARAPACE_LOG_LEVEL, instead of setting it manually via extraEnv.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- feat(chart): expose sandbox.warmPoolSize value
  ([`edb513c`](https://github.com/thiesgerken/carapace/commit/edb513c497c179e7fb7bab66c58b69d1ce0a1e64))

  Add a first-class sandbox.warmPoolSize Helm value (default 1) wired to CARAPACE_SANDBOX_WARM_POOL_SIZE, instead of requiring users to set the env var manually via extraEnv. Update README and k8s docs accordingly.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: tear down warm pool when size is 0
  ([`4df7d0b`](https://github.com/thiesgerken/carapace/commit/4df7d0bd7450ba61956b5af6017000f044b52184))

  Run the warm-pool loop on Kubernetes regardless of warm_pool_size; a target of 0 destroys leftover carapace.pool StatefulSets after the feature is disabled or shrunk, instead of leaking them until manual cleanup.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: serialize warm-pool maintenance and refill after cold create
  ([`0fa7730`](https://github.com/thiesgerken/carapace/commit/0fa7730f37682a9e2cc362fa2eeddf8df6183660))

  - Guard ensure_warm_pool with _warm_claim_lock so periodic maintenance
    never resumes/recreates/destroys a pool entry mid-claim.
  - Replenish the pool after a cold-create fallback instead of waiting for
    the 60s background loop.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix: rebuild proxy env on warm-sandbox reattach
  ([`07490cc`](https://github.com/thiesgerken/carapace/commit/07490cc836c075c8d557662981bf870f883bfdbc))

  Claimed warm sandboxes carry no proxy env in their pod spec; exec relies on session_env. The reattach/resume path rebuilt SessionContainer without it, so after idle cleanup or server restart exec ran with no proxy vars. Rebuild session_env (and merge stashed env) on reattach.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- fix tests + code
  ([`95bea8d`](https://github.com/thiesgerken/carapace/commit/95bea8d00c6726ce82411c0555ac5a6201a5779b))

- version variables
  ([`6aa4880`](https://github.com/thiesgerken/carapace/commit/6aa4880b2d62274977fb19ab4f1c19346750242f))

- more crc
  ([`23b2e4e`](https://github.com/thiesgerken/carapace/commit/23b2e4e45ee23eaf6225eb963fc85d82cc2bfc8d))

- simplify
  ([`6910f0d`](https://github.com/thiesgerken/carapace/commit/6910f0d087cecf31c1d0690962d3939c607f0158))

- crc
  ([`9a5e034`](https://github.com/thiesgerken/carapace/commit/9a5e0348634e5ece3998403eed67d30a92ad5ea9))

- reduce CARAPACE_SANDBOX_WARM_POOL_SIZE from 2 to 1 for optimized resource usage
  ([`49a308f`](https://github.com/thiesgerken/carapace/commit/49a308fabcfa96563899143643d0228cd8aa3431))

- crc
  ([`65414cc`](https://github.com/thiesgerken/carapace/commit/65414cc21dfab20a6a4e223fdc63d0f093cc3e78))

- Merge branch 'main' into feature/warm-sandboxes
  ([`885c3ba`](https://github.com/thiesgerken/carapace/commit/885c3ba2a5ba60d24c25a3f79dec8a7e5db6473f))

- Merge branch 'main' into feature/warm-sandboxes
  ([`b5f934e`](https://github.com/thiesgerken/carapace/commit/b5f934efb648726fd25336bc7708c3be5a50033a))

## v0.135.4 (2026-06-03)


### Other


- Merge pull request #197 from thiesgerken/renovate/all-routine-dependencies
  ([`d457849`](https://github.com/thiesgerken/carapace/commit/d45784947105c55a3988c0a3acade6a532988cda))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates to df4cb1c
  ([`d457849`](https://github.com/thiesgerken/carapace/commit/d45784947105c55a3988c0a3acade6a532988cda))

- ⬆️ chore: upgrade all routine dependency updates to df4cb1c
  ([`4a838a2`](https://github.com/thiesgerken/carapace/commit/4a838a2054ec4539d83aca82b4b720fadab0c966))

## v0.135.3 (2026-06-03)


### Other


- Merge pull request #196 from thiesgerken/renovate/major-github-artifact-actions
  ([`41afbae`](https://github.com/thiesgerken/carapace/commit/41afbae9606e73899cadc4d8e987807adb487fbd))

- Merge pull request #198 from thiesgerken/renovate/astral-sh-setup-uv-8.x
  ([`6e7004f`](https://github.com/thiesgerken/carapace/commit/6e7004f68534bff5f2538783aa4e4ebdbd4700ca))

### ⬆️ Dependencies


- ⬆️ chore: upgrade GitHub Artifact Actions to v7.0.1
  ([`41afbae`](https://github.com/thiesgerken/carapace/commit/41afbae9606e73899cadc4d8e987807adb487fbd))

- ⬆️ chore: upgrade GitHub Artifact Actions to v7.0.1
  ([`e9b00dd`](https://github.com/thiesgerken/carapace/commit/e9b00dd29423a49cb79c881b35f6ad343db28d35))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v8.2.0
  ([`6e7004f`](https://github.com/thiesgerken/carapace/commit/6e7004f68534bff5f2538783aa4e4ebdbd4700ca))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v8.2.0
  ([`76863a5`](https://github.com/thiesgerken/carapace/commit/76863a55272562fab9fa36cd42656702343c11d9))

## v0.135.2 (2026-06-02)


### Other


- Merge pull request #192 from thiesgerken/renovate/all-routine-dependencies
  ([`2ceefd6`](https://github.com/thiesgerken/carapace/commit/2ceefd69e14f6cfdbe7e8a63e739c4b00dacff9e))

- Merge pull request #193 from thiesgerken/renovate/pnpm-11.x
  ([`ab53c14`](https://github.com/thiesgerken/carapace/commit/ab53c14d0fd6dc8cb156f5932eedfed729c176e8))

- 💚Merge pull request #195 from thiesgerken/feature/pr-builds
  ([`019c118`](https://github.com/thiesgerken/carapace/commit/019c118349b8da0a6f80307a9ae673bb0b968fee))

  💚 ci: publish pr docker images + helm chart

- fix hash
  ([`fb1f051`](https://github.com/thiesgerken/carapace/commit/fb1f051ffffbd0d72c2342002c71f11bcaaf581e))

- fix backend test
  ([`3268f35`](https://github.com/thiesgerken/carapace/commit/3268f353a7d18ccc4673cb74ddf3a738f2683825))

- add pretest
  ([`4d8369b`](https://github.com/thiesgerken/carapace/commit/4d8369b2c9c6099fbd11b8d95cd6882e70131238))

- 💚 ci: publish pr docker images + helm chart
  ([`3779fa5`](https://github.com/thiesgerken/carapace/commit/3779fa5a019a1073bc688c46a0d9f92229d41d09))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`2ceefd6`](https://github.com/thiesgerken/carapace/commit/2ceefd69e14f6cfdbe7e8a63e739c4b00dacff9e))

- ⬆️ chore: upgrade all routine dependency updates
  ([`1f080b2`](https://github.com/thiesgerken/carapace/commit/1f080b2f9a9ae7f2551be9dfe2bfa695cffa041e))

- ⬆️ chore: upgrade pnpm to 11.5.0
  ([`ab53c14`](https://github.com/thiesgerken/carapace/commit/ab53c14d0fd6dc8cb156f5932eedfed729c176e8))

- ⬆️ chore: upgrade pnpm to 11.5.0
  ([`26b6a2a`](https://github.com/thiesgerken/carapace/commit/26b6a2a15a4c4fe156f985917f83592a2bf67800))

## v0.135.1 (2026-06-02)


### 💄 UI/UX


- 💄 ui: use EmojiText component for session titles in ChatView and JobsView
  ([`5b8e1a9`](https://github.com/thiesgerken/carapace/commit/5b8e1a96f05550b698ad139059e756fc16a8caa9))

## v0.135.0 (2026-06-01)


### ✨ Features


- ✨ feat: if a tool output is too long, redirect it to a file
  ([`119a3ea`](https://github.com/thiesgerken/carapace/commit/119a3ea9a587f4137e64a4721f4a6b5740e3c130))

## v0.134.4 (2026-06-01)


### 🐛 Bug Fixes


- 🐛 fix: enable switching attended -> unattended again
  ([`f3ac0b2`](https://github.com/thiesgerken/carapace/commit/f3ac0b239b28e3672b81113865d72a904f3c07a3))

## v0.134.3 (2026-06-01)


### 🐛 Bug Fixes


- 🐛 fix: disable some caching for frontend and backend to avoid refresh loops
  ([`2ff5c95`](https://github.com/thiesgerken/carapace/commit/2ff5c955e81bd050a0201a486e4e88234e53f18a))

## v0.134.2 (2026-06-01)


### 🐛 Bug Fixes


- 🐛 fix: improve bundled skills
  ([`f72ac46`](https://github.com/thiesgerken/carapace/commit/f72ac46063b7882c4d72e4a5ce292acc4ad800ef))

## v0.134.1 (2026-06-01)


### 🐛 Bug Fixes


- 🐛 fix: initialize knowledge repo registry on startup
  ([`8b0cc34`](https://github.com/thiesgerken/carapace/commit/8b0cc34b23a7c6374cd49fd5f9f7e41b57e67612))

### Other


- 📋 docs: fix ci badge
  ([`ff2461c`](https://github.com/thiesgerken/carapace/commit/ff2461c1e18351ca907784bb19469e75cb6494e6))

- 📋 docs: fix ci badge
  ([`d8ab672`](https://github.com/thiesgerken/carapace/commit/d8ab672947ad2909e90566c063d8df6af7803c4a))

- 📋 docs: fix ci badge
  ([`24a9837`](https://github.com/thiesgerken/carapace/commit/24a9837e5cd97be81aad341a43716680cbc5957f))

- 📋 docs: fix ci badge
  ([`7901154`](https://github.com/thiesgerken/carapace/commit/7901154eb305c4c0896f568ce7b74462c02531a2))

## v0.134.0 (2026-05-31)


### ✨ Features


- ✨Merge pull request #190 from thiesgerken/feature/individual-knowledge
  ([`c9ebece`](https://github.com/thiesgerken/carapace/commit/c9ebecec8ceb31240bc2a95edaf6c8439cbbf00f))

- ✨ feat: individual knowledge repos per user
  ([`c9ebece`](https://github.com/thiesgerken/carapace/commit/c9ebecec8ceb31240bc2a95edaf6c8439cbbf00f))

- ✨ feat: individual knowledge repos per user
  ([`b40496e`](https://github.com/thiesgerken/carapace/commit/b40496e81315712df22ca9ea98d8546baaefb96d))

### Other


- fix: update knowledge directory resolution to use "knowledges"
  ([`d303d4e`](https://github.com/thiesgerken/carapace/commit/d303d4e10dc2f93e3c1de36035720b495fae78b3))

- auth review issues
  ([`70f2e05`](https://github.com/thiesgerken/carapace/commit/70f2e05f7aaf3ecb5f61a302ae5017fd14c48e85))

- crc
  ([`7589e32`](https://github.com/thiesgerken/carapace/commit/7589e32b0414424c85aebcd556d2c2df8f1cf00e))

- test warnings
  ([`bec7fe1`](https://github.com/thiesgerken/carapace/commit/bec7fe1d1440eeca4c32fe558afb61c67606f434))

- fix tests
  ([`4f92472`](https://github.com/thiesgerken/carapace/commit/4f92472915a9af5095ab0aed42f1b1cd7b61dc6a))

- crc
  ([`735cf33`](https://github.com/thiesgerken/carapace/commit/735cf33e9430f7200c9a040556427e5fdc58b70d))

- fixes
  ([`4a73740`](https://github.com/thiesgerken/carapace/commit/4a73740fc6efff9d4ebc5d47a03b0941523126f6))

- fixes
  ([`76fa463`](https://github.com/thiesgerken/carapace/commit/76fa463768a4c6069c01d8bf6bd1fb4dc22f5a4c))

## v0.133.1 (2026-05-31)


### 🐛 Bug Fixes


- 🐛 fix: introduce strict username patterns
  ([`d41bcb9`](https://github.com/thiesgerken/carapace/commit/d41bcb9c39aa2dc26d510267d25b179b6bab8b4a))

## v0.133.0 (2026-05-31)


### 🐛 Bug Fixes


- 🐛 fix: update defaultMode for nginx-auth secret to 0444
  ([`b98c11e`](https://github.com/thiesgerken/carapace/commit/b98c11e1b71154c6780b2eda57e5084e706e824f))

### ✨ Features


- ✨ feat: add configurable probes for Bitwarden and nginx in values.yaml
  ([`56858db`](https://github.com/thiesgerken/carapace/commit/56858db0d80e28f6b13e15d6f05c32a551fa552a))

## v0.132.1 (2026-05-31)


### 🐛 Bug Fixes


- 🐛 fix: update defaultMode for nginx-auth secret to 0440
  ([`8b9f08f`](https://github.com/thiesgerken/carapace/commit/8b9f08ff540aa35507ab4eebfaf4ed4d2d164916))

## v0.132.0 (2026-05-31)


### ✨ Features


- ✨Merge pull request #189 from thiesgerken/feat/openrouter
  ([`dd8ebfe`](https://github.com/thiesgerken/carapace/commit/dd8ebfe8e01a93f7132f3facdb93f6e9c8cb313f))

- ✨ feat: support openrouter + fix small issues with model editing
  ([`dd8ebfe`](https://github.com/thiesgerken/carapace/commit/dd8ebfe8e01a93f7132f3facdb93f6e9c8cb313f))

- ✨ feat: support openrouter + small issues with model editing
  ([`d4306ec`](https://github.com/thiesgerken/carapace/commit/d4306ec2b75f4355c823521467a427b9584fd264))

### Other


- crc
  ([`1c970b7`](https://github.com/thiesgerken/carapace/commit/1c970b73da257a01abec1f79eb6595be51019973))

- sort models
  ([`b18b441`](https://github.com/thiesgerken/carapace/commit/b18b4415ca56ea462c0e59c47e0e9bc453aecd30))

- add second settings link
  ([`a949300`](https://github.com/thiesgerken/carapace/commit/a9493004f68bf36f7186c82e9c43cd23054bee0a))

- new model on top
  ([`e716283`](https://github.com/thiesgerken/carapace/commit/e71628364100156d1ad39c79e6d3630c6687fc19))

- fallback pricing
  ([`f8367ba`](https://github.com/thiesgerken/carapace/commit/f8367ba27a704839fd8616a33aa3225133c018f3))

- take usage from response if possible and better colors
  ([`b2b6cbc`](https://github.com/thiesgerken/carapace/commit/b2b6cbcfbae569b3b3de5b7d1a7908534001eed7))

- 📋 docs: update stale docs that didn't reflect config or multi user changes
  ([`723759c`](https://github.com/thiesgerken/carapace/commit/723759c351a3b940437d9a86b9b8bccc40f09e90))

### 🐛 Bug Fixes


- 🐛 improve i18n a bit
  ([`19c0a59`](https://github.com/thiesgerken/carapace/commit/19c0a59b04a666ab5517f5845098863d13269ae4))

## v0.131.1 (2026-05-30)


### 🐛 Bug Fixes


- 🐛 fix: do not auto fill git token + use WriteOnlyPasswordInput component there
  ([`21b070f`](https://github.com/thiesgerken/carapace/commit/21b070f16bd42639584a57314b086341799e295f))

## v0.131.0 (2026-05-30)


### ✨ Features


- ✨ feat: increase default probe delays in helm chart and make them configurable
  ([`34d2a61`](https://github.com/thiesgerken/carapace/commit/34d2a615d38458377010f906394c2de0edb97972))

## v0.130.1 (2026-05-30)


### 🐛 Bug Fixes


- 🐛 fix: sender check for _on_reaction handling in matrix channel
  ([`2c0a9f1`](https://github.com/thiesgerken/carapace/commit/2c0a9f185e150327ad8f81ad6ad6e8cf483133ad))

## v0.130.0 (2026-05-30)


### ✨ Features


- ✨Merge pull request #187 from thiesgerken/feature/editable-platform-config
  ([`866ea57`](https://github.com/thiesgerken/carapace/commit/866ea578564b8e26b00580b23f5165748ddb080e))

- ✨ feat: make config adjustable from ui
  ([`866ea57`](https://github.com/thiesgerken/carapace/commit/866ea578564b8e26b00580b23f5165748ddb080e))

- ✨ feat: make config adjustable from ui
  ([`bbf899c`](https://github.com/thiesgerken/carapace/commit/bbf899c1f0d754e545cddd63383a316452047fff))

### 🐛 Bug Fixes


- 🐛 fix: clear provider-specific model fields
  ([`57601d2`](https://github.com/thiesgerken/carapace/commit/57601d2845f64b38c53b747881719ddfd31df334))

- 🐛 fix: constrain platform model secret fields
  ([`0705c83`](https://github.com/thiesgerken/carapace/commit/0705c83d12705d8a19bc7333c3d32ce7ca38e33e))

- 🐛 fix: preserve disk platform config fields
  ([`fd5891c`](https://github.com/thiesgerken/carapace/commit/fd5891c6cd707952d2023986da0f1e670e5ced43))

- 🐛 fix: honor read-only platform config
  ([`cf33dac`](https://github.com/thiesgerken/carapace/commit/cf33dacda2e2d3d00143bed425a7eb209441dbfc))

- 🐛 fix: address platform settings review comments
  ([`f6b6532`](https://github.com/thiesgerken/carapace/commit/f6b6532088ef284188ecf7ba030d14dad2cc91bc))

### Other


- update platform settings UI with enhanced model display and badge functionality
  ([`9cb617b`](https://github.com/thiesgerken/carapace/commit/9cb617b22aa5537b3efc3c4890c768df2143fa0b))

- update configuration paths and remove deprecated PVC for config
  ([`fc98b30`](https://github.com/thiesgerken/carapace/commit/fc98b30d3177645564fcbc6bdbafbdcda80f4580))

## v0.129.1 (2026-05-30)


### Other


- Merge pull request #188 from thiesgerken/renovate/pnpm-11.x
  ([`103cb83`](https://github.com/thiesgerken/carapace/commit/103cb83e90d67da0a3b853f447377903a56c7ef4))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.4.0
  ([`103cb83`](https://github.com/thiesgerken/carapace/commit/103cb83e90d67da0a3b853f447377903a56c7ef4))

- ⬆️ chore: upgrade pnpm to 11.4.0
  ([`701e54e`](https://github.com/thiesgerken/carapace/commit/701e54e84625e068489ff654b4e06c9ecbd5323f))

## v0.129.0 (2026-05-30)


### ✨ Features


- ✨Merge pull request #186 from thiesgerken/feature/editable-settings
  ([`eb83ae9`](https://github.com/thiesgerken/carapace/commit/eb83ae99070e02ece6178c58a294f04d10064f6a))

- ✨ feat: make user settings editable
  ([`eb83ae9`](https://github.com/thiesgerken/carapace/commit/eb83ae99070e02ece6178c58a294f04d10064f6a))

- ✨ feat: make user settings editable
  ([`d848aa8`](https://github.com/thiesgerken/carapace/commit/d848aa88c399c4281247b62f3e576973d4ba6f5e))

### Other


- feat: enhance user settings management with credential handling and validation
  ([`d342760`](https://github.com/thiesgerken/carapace/commit/d342760a0b02854ccf001b535d07d43a7b91a8e5))

- feat: implement matrix token management during user settings update
  ([`4a35c7e`](https://github.com/thiesgerken/carapace/commit/4a35c7ed017cb1219757782006b353ff01199f6e))

- feat: add current model description to defaults in settings and enhance user settings view
  ([`8d592ab`](https://github.com/thiesgerken/carapace/commit/8d592ab797a2ab8d8399be2e8ca34e00f91ce290))

- feat: update translations for account and cost labels in German and English
  ([`1e2b4fb`](https://github.com/thiesgerken/carapace/commit/1e2b4fbf7052a19b2f1c44b0ed0cf7a49dbd6d24))

- crc
  ([`b0e2ecd`](https://github.com/thiesgerken/carapace/commit/b0e2ecd074c730951958f52e93e66355ca72b257))

- refactor: remove unused clearGitToken field and related logic from user settings
  ([`ed8bd64`](https://github.com/thiesgerken/carapace/commit/ed8bd64612fa0d609af371a7403f0c199745c489))

- feat: enhance password input fields with autocomplete and ignore attributes
  ([`5307ed1`](https://github.com/thiesgerken/carapace/commit/5307ed1bcda89b1b0c2ebf2eb411f8fb09f17b21))

- Refactor user settings field to include help tooltip and update file path hint to tooltip
  ([`b8a30bb`](https://github.com/thiesgerken/carapace/commit/b8a30bbcdf740906f79b69eef8209c65be5d45b0))

- Add account settings localization and enhance user settings view
  ([`0fe5fda`](https://github.com/thiesgerken/carapace/commit/0fe5fda4dd33e7af19e0963bc5ac7abb29aa35ab))

  - Introduced German translations for account settings, including status messages, notices, errors, sections, fields, defaults, placeholders, hints, tooltips, actions, and credential types.
  - Updated the user settings view to utilize the new translations, improving accessibility for German-speaking users.
  - Refactored credential backend handling to support dynamic addition and removal of credential types (file and Bitwarden).
  - Enhanced input components for better user experience, including multi-select for allowed rooms and users, and improved password handling.

- crc, flatten cred settings caps
  ([`6bf64a4`](https://github.com/thiesgerken/carapace/commit/6bf64a4392eb368f8749990e9372946ff4893172))

- reload if needed
  ([`02dc74b`](https://github.com/thiesgerken/carapace/commit/02dc74b80f6e0c471ed88330afee5647bc89e5d0))

### 🐛 Bug Fixes


- 🐛 fix: serialize settings runtime updates
  ([`a435036`](https://github.com/thiesgerken/carapace/commit/a435036771b1d71479fba7d8b2eedfc9bc3f2a67))

- 🐛 fix: harden editable settings reloads
  ([`5edee8e`](https://github.com/thiesgerken/carapace/commit/5edee8e21d14b1a84b1182c5f5a2548984af539e))

## v0.128.1 (2026-05-30)


### Other


- Merge pull request #183 from thiesgerken/renovate/all-routine-dependencies
  ([`41f5670`](https://github.com/thiesgerken/carapace/commit/41f5670733c04aa0e8fa9300b9d816b2df490cbe))

- Merge pull request #185 from thiesgerken/renovate/redis-8.x
  ([`69d6882`](https://github.com/thiesgerken/carapace/commit/69d6882e965622d9893f9c3284ec32f2ee9426e3))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`41f5670`](https://github.com/thiesgerken/carapace/commit/41f5670733c04aa0e8fa9300b9d816b2df490cbe))

- ⬆️ chore: upgrade all routine dependency updates
  ([`dde1cd5`](https://github.com/thiesgerken/carapace/commit/dde1cd5bf70f4e11f681212ba9073d51ed79b8be))

- ⬆️ chore: upgrade redis to 8.0.0
  ([`69d6882`](https://github.com/thiesgerken/carapace/commit/69d6882e965622d9893f9c3284ec32f2ee9426e3))

- ⬆️ chore: upgrade redis to 8.0.0
  ([`929a732`](https://github.com/thiesgerken/carapace/commit/929a732a7834d09bad05c8bec8a60ce57785d253))

## v0.128.0 (2026-05-27)


### ✨ Features


- ✨Merge pull request #184 from thiesgerken/feature/no-global-creds-disable-file-backend
  ([`df07178`](https://github.com/thiesgerken/carapace/commit/df071787138e52c18a254db15f47ce11fb3f76f9))

- ✨ feat: no global credential config + disable file cred backend by default
  ([`df07178`](https://github.com/thiesgerken/carapace/commit/df071787138e52c18a254db15f47ce11fb3f76f9))

- ✨ feat: no global credential config + disable file cred backend by default
  ([`a98e9eb`](https://github.com/thiesgerken/carapace/commit/a98e9eb556710d9f81c84884d094b5c8eb4c634d))

### Other


- thies -> alice
  ([`95e439f`](https://github.com/thiesgerken/carapace/commit/95e439f7c8c61b28d3776bb39f36120c7e0477d7))

- 8087 -> 80
  ([`fca7b68`](https://github.com/thiesgerken/carapace/commit/fca7b68a2603605ff3e81ca1ee59991306a73daf))

## v0.127.0 (2026-05-27)


### Other


- Merge pull request #181 from thiesgerken/renovate/all-routine-dependencies
  ([`3464bfd`](https://github.com/thiesgerken/carapace/commit/3464bfd2d6521f673b9809f5c56fff8a8e26c50b))

- Merge pull request #182 from thiesgerken/renovate/pnpm-11.x
  ([`01ad8b1`](https://github.com/thiesgerken/carapace/commit/01ad8b1170dd46c1ec6e990e2501000a8f2a8102))

- remove sidecar mode
  ([`f5eb3e1`](https://github.com/thiesgerken/carapace/commit/f5eb3e1bce5708abea70ba2a1e25144f7cbe2061))

### ⬆️ Dependencies


- ⬆️ chore: upgrade redis:8-alpine Docker digest to ad0a6ef
  ([`3464bfd`](https://github.com/thiesgerken/carapace/commit/3464bfd2d6521f673b9809f5c56fff8a8e26c50b))

- ⬆️ chore: upgrade redis:8-alpine Docker digest to ad0a6ef
  ([`882f9ef`](https://github.com/thiesgerken/carapace/commit/882f9ef150b829dfb59a35daf99284b1a4285f08))

- ⬆️ chore: upgrade pnpm to 11.3.0
  ([`01ad8b1`](https://github.com/thiesgerken/carapace/commit/01ad8b1170dd46c1ec6e990e2501000a8f2a8102))

- ⬆️ chore: upgrade pnpm to 11.3.0
  ([`6140c72`](https://github.com/thiesgerken/carapace/commit/6140c72ea8b4b9b12ff4658381f6fe83ddb19f2f))

### ✨ Features


- ✨Merge pull request #180 from thiesgerken/feat/bw-standalone
  ([`6965e1e`](https://github.com/thiesgerken/carapace/commit/6965e1eecbd131f80180f6240c099c2d4ac5d6b7))

- ✨ feat: use standalone Bitwarden instances with HTTP Basic Auth
  ([`6965e1e`](https://github.com/thiesgerken/carapace/commit/6965e1eecbd131f80180f6240c099c2d4ac5d6b7))

- ✨ feat: Add support for standalone Bitwarden instances with HTTP Basic Auth
  ([`02ed3be`](https://github.com/thiesgerken/carapace/commit/02ed3befb01324e569f1519fca66f4bca57da152))

  - Introduced new Helm template for Bitwarden deployment in standalone mode, including Nginx proxy configuration.
  - Updated values.yaml to include configuration for Nginx image and Bitwarden instances.
  - Enhanced Bitwarden backend to support HTTP Basic Auth for user-specific configurations.
  - Implemented credential registry handling for user-specific sessions.
  - Added tests for Bitwarden backend authentication and user configuration redaction.
  - Updated documentation to reflect changes in credential backend configuration and usage.

### 🐛 Bug Fixes


- 🐛 fix: separate KeyError handling in fetch_credential to return 403 for missing user vs 404 for missing credential
  ([`2f353a0`](https://github.com/thiesgerken/carapace/commit/2f353a005d076a1cc08ea3d06df7b5adc600462c))

  Applied via @cursor push command

- 🐛 fix: separate KeyError handling in fetch_credential to return 403 for missing user vs 404 for missing credential
  ([`27c08a5`](https://github.com/thiesgerken/carapace/commit/27c08a541759e6e924fa068e9a428bb19a29e1cd))

- 🐛 fix: Update Bitwarden proxy configuration to enforce port restrictions for standalone instances
  ([`cbfdf25`](https://github.com/thiesgerken/carapace/commit/cbfdf252336baf8347c9b57911a968917a2c46e2))

## v0.126.1 (2026-05-26)


### Other


- force ci
  ([`bf8ebb0`](https://github.com/thiesgerken/carapace/commit/bf8ebb06fe670c68330a5b648fcdf5f0a19049c9))

### 🐛 Bug Fixes


- 🐛 fix: force a release
  ([`5b40c04`](https://github.com/thiesgerken/carapace/commit/5b40c04ebf74d890f36bf738bf97917403366245))

### ♻️ Refactoring


- ♻️Merge pull request #179 from thiesgerken/feature/remove-user-upgrade
  ([`7c4d946`](https://github.com/thiesgerken/carapace/commit/7c4d94652c6c14fdf11027c5b7242320f681d2cc))

- ♻️ refactor: migrate Git configuration to user records and remove global Git settings
  ([`7c4d946`](https://github.com/thiesgerken/carapace/commit/7c4d94652c6c14fdf11027c5b7242320f681d2cc))

- ♻️ refactor: migrate Git configuration to user records and remove global Git settings
  ([`4dfc589`](https://github.com/thiesgerken/carapace/commit/4dfc589229b5b83b0019fe27e0fed92237ce616f))

## v0.126.0 (2026-05-26)


### ✨ Features


- ✨🔥Merge pull request #178 from thiesgerken/feature/remove-user-upgrade
  ([`e1b7ec0`](https://github.com/thiesgerken/carapace/commit/e1b7ec041e2e5494f71686f444b9dd74e7c99843))

- ✨🔥 feat: remove upgrade-data-to-user functionality, make user non-optional everywhere
  ([`e1b7ec0`](https://github.com/thiesgerken/carapace/commit/e1b7ec041e2e5494f71686f444b9dd74e7c99843))

- ✨ feat: remove upgrade-data-to-user functionality, make user non-optional everywhere
  ([`a377742`](https://github.com/thiesgerken/carapace/commit/a377742ec8ddbab50f1a17ae214632bba05179c8))

### Other


- refactor user configuration and remove secret source objects for Git and Matrix settings
  ([`3262305`](https://github.com/thiesgerken/carapace/commit/32623053816dfaa7b3c0951e90f38659eb4213b5))

- readd port mapping for carapace service in docker-compose
  ([`73db07a`](https://github.com/thiesgerken/carapace/commit/73db07a3d9dee9575ba475cb48b9a3b33e586749))

- adjust roadmap
  ([`f811707`](https://github.com/thiesgerken/carapace/commit/f8117073138ad863bf0688b15a587a53eb1b15b7))

## v0.125.4 (2026-05-25)


### 🐛 Bug Fixes


- 🐛 fix: add types-docker dependency to project
  ([`55e5887`](https://github.com/thiesgerken/carapace/commit/55e588702f2acc0b47aa1554658b86cb317e64e7))

## v0.125.3 (2026-05-25)


### 🐛 Bug Fixes


- 🐛Merge pull request #177 from thiesgerken/fix/compose-proxy
  ([`ec22c17`](https://github.com/thiesgerken/carapace/commit/ec22c17518cb661236150961c94d200cf6418728))

- 🐛 fix: add reverse proxy to compose deployment
  ([`ec22c17`](https://github.com/thiesgerken/carapace/commit/ec22c17518cb661236150961c94d200cf6418728))

- 🐛 fix: reorder docker import statements for consistency
  ([`d842148`](https://github.com/thiesgerken/carapace/commit/d8421487689957810f07c893996d60123f086557))

- 🐛 fix: add reverse proxy to compose deployment
  ([`d66d5f4`](https://github.com/thiesgerken/carapace/commit/d66d5f410a111214e1fc8f9a8fac0edb426fab31))

## v0.125.2 (2026-05-25)


### 🐛 Bug Fixes


- 🐛 fix: update username placeholder in localization files for consistency
  ([`5f3cb6d`](https://github.com/thiesgerken/carapace/commit/5f3cb6d94b91a0a553b52d440a9efdb36f86d646))

## v0.125.1 (2026-05-25)


### Other


- Merge pull request #169 from thiesgerken/renovate/pnpm-11.x
  ([`e9e96c7`](https://github.com/thiesgerken/carapace/commit/e9e96c7583d3865a1e6adcaec6fe7533289b4594))

- Merge pull request #172 from thiesgerken/renovate/all-routine-dependencies
  ([`4eb04dd`](https://github.com/thiesgerken/carapace/commit/4eb04dd5163d60be2cf5b340a7e8e1f5f1ad0bbb))

- Merge pull request #174 from thiesgerken/renovate/katex-0.x
  ([`7838576`](https://github.com/thiesgerken/carapace/commit/7838576625191d3667b5454614c5be47e259be62))

- Merge pull request #176 from thiesgerken/fix/session-pruning-retains-revoked
  ([`3eaf228`](https://github.com/thiesgerken/carapace/commit/3eaf228e3bf23786dd127de89b74ee3abceef0e9))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.2.2
  ([`e9e96c7`](https://github.com/thiesgerken/carapace/commit/e9e96c7583d3865a1e6adcaec6fe7533289b4594))

- ⬆️ chore: upgrade pnpm to 11.2.2
  ([`dcb7264`](https://github.com/thiesgerken/carapace/commit/dcb726412522de4289db3eaacb90a9736ecf43af))

- ⬆️ chore: upgrade nginx:alpine Docker digest to 8b1e787
  ([`4eb04dd`](https://github.com/thiesgerken/carapace/commit/4eb04dd5163d60be2cf5b340a7e8e1f5f1ad0bbb))

- ⬆️ chore: upgrade nginx:alpine Docker digest to 8b1e787
  ([`0e165d5`](https://github.com/thiesgerken/carapace/commit/0e165d5ad9d198f042f7af1044deaeecb3ffa4fb))

- ⬆️ chore: upgrade katex to 0.17.0
  ([`7838576`](https://github.com/thiesgerken/carapace/commit/7838576625191d3667b5454614c5be47e259be62))

- ⬆️ chore: upgrade katex to 0.17.0
  ([`ffae414`](https://github.com/thiesgerken/carapace/commit/ffae4146b47ad14c6aba035da5dbd59d85f79728))

### 🐛 Bug Fixes


- 🐛 fix: revoked session pruning audit trail
  ([`3eaf228`](https://github.com/thiesgerken/carapace/commit/3eaf228e3bf23786dd127de89b74ee3abceef0e9))

- 🐛 fix: retain revoked session audit trail
  ([`12d5be2`](https://github.com/thiesgerken/carapace/commit/12d5be27f55ce72bfa1b4f0cc067197c2c609a4c))

## v0.125.0 (2026-05-25)


### ✨ Features


- ✨Merge pull request #175 from thiesgerken/feature/same-origin-frontend-backend
  ([`ad8a2f3`](https://github.com/thiesgerken/carapace/commit/ad8a2f3ea265c4f8dc8fb0d6ccd2a83daba2e1ea))

- ✨ Use same-origin backend for frontend
  ([`ad8a2f3`](https://github.com/thiesgerken/carapace/commit/ad8a2f3ea265c4f8dc8fb0d6ccd2a83daba2e1ea))

- ✨ feat: use same-origin frontend backend
  ([`6c0c799`](https://github.com/thiesgerken/carapace/commit/6c0c799f609b67929d7c6f71baaebffaeefd2ecb))

## v0.124.0 (2026-05-25)


### ✨ Features


- ✨Merge pull request #173 from thiesgerken/feature/multi-user-auth
  ([`7f53bbd`](https://github.com/thiesgerken/carapace/commit/7f53bbdc06db9d1d989653739853e5677e073166))

- ✨ User Support
  ([`7f53bbd`](https://github.com/thiesgerken/carapace/commit/7f53bbdc06db9d1d989653739853e5677e073166))

- ✨ feat: add admin user deletion
  ([`6f06272`](https://github.com/thiesgerken/carapace/commit/6f062723d3dccdd3ebc4078f1fdd4239805d78f4))

- ✨ feat: embed platform admin settings
  ([`5d32374`](https://github.com/thiesgerken/carapace/commit/5d323744fe061da5fa3f753046199bab1b17af25))

- ✨ feat: add admin data upgrade action
  ([`18327a6`](https://github.com/thiesgerken/carapace/commit/18327a6cd5bb900642031e8b6cafaeb781a8bfd0))

- ✨ feat: add admin users page
  ([`83ef362`](https://github.com/thiesgerken/carapace/commit/83ef362e216528468cf063be10a78637511d0f70))

- ✨ feat: add multi-user cookie auth
  ([`9637ae7`](https://github.com/thiesgerken/carapace/commit/9637ae789bdd5c31469fd79619d4db45a01d566a))

### 🐛 Bug Fixes


- 🐛 fix: repair disabled bootstrap admin
  ([`a9841ca`](https://github.com/thiesgerken/carapace/commit/a9841ca77fcf14461500fb599bea8c73eb2c5e13))

- 🐛 fix: return to login on auth expiry
  ([`c1a466a`](https://github.com/thiesgerken/carapace/commit/c1a466a3da08d6ef2f2dc85a3b085195416a46cf))

- 🐛 fix: skip bootstrap when admins exist
  ([`594c06c`](https://github.com/thiesgerken/carapace/commit/594c06c55658bb3dca040765a074b27655f5793f))

- 🐛 fix: address multi-user auth review comments
  ([`5e57678`](https://github.com/thiesgerken/carapace/commit/5e576781512db46d3812ac6795bb70a05c909139))

- 🐛 fix: address auth ownership review comments
  ([`7cdb506`](https://github.com/thiesgerken/carapace/commit/7cdb5068a53045aa0a4eb54b74bf60f40e075dc0))

- 🐛 fix: clean up code formatting and improve readability in API functions
  ([`56a75e0`](https://github.com/thiesgerken/carapace/commit/56a75e01f8ea06f879535fd91442401795ba927c))

- 🐛 fix: handle auth review edge cases
  ([`c9bed88`](https://github.com/thiesgerken/carapace/commit/c9bed882b6f669911ca181e68bc8c42e3d8f194b))

- 🐛 fix: address multi-user review feedback
  ([`4ed57aa`](https://github.com/thiesgerken/carapace/commit/4ed57aad16306459b424c2a38ea6e8d9f22c2fcd))

### 💄 UI/UX


- 💄 style: make account logout icon-only
  ([`33d1680`](https://github.com/thiesgerken/carapace/commit/33d16808c73b4e64c701cc1ae5ad74587627c07a))

- 💄 style: show admin user badge
  ([`16acbd8`](https://github.com/thiesgerken/carapace/commit/16acbd85f16896219c3788c49788ba42500693ba))

- 💄 style: separate account name from avatar
  ([`aa85168`](https://github.com/thiesgerken/carapace/commit/aa8516866329d39ba7f80b0aa8a9f9754c7c4f15))

- 💄 style: show account name in header
  ([`d14f016`](https://github.com/thiesgerken/carapace/commit/d14f0164a257dd97147cca350fefb48be414e7c8))

- 💄 style: simplify account menu header
  ([`924db2a`](https://github.com/thiesgerken/carapace/commit/924db2ac4baab2012f9660d530b23b100694be87))

- 💄 style: narrow home navigation target
  ([`e6eb50f`](https://github.com/thiesgerken/carapace/commit/e6eb50fb660925f4c57f83e3f3eecfcb47c51697))

- 💄 style: polish account menu
  ([`356b9ac`](https://github.com/thiesgerken/carapace/commit/356b9ac61ced96712e949cc9e072e4a8f8fa4334))

- 💄 style: make brand navigate home
  ([`39217a6`](https://github.com/thiesgerken/carapace/commit/39217a66f5c361b97ef365cb48cb460a2e68fd13))

- 💄 style: add account menu avatar
  ([`8e96466`](https://github.com/thiesgerken/carapace/commit/8e96466f5d49710eea09df58d3012cda2cf98a7f))

- 💄 style: simplify users settings tab
  ([`857267d`](https://github.com/thiesgerken/carapace/commit/857267dee326814d4de21374f5f2e1455be7e9c5))

- 💄 style: mark current admin user
  ([`abbf424`](https://github.com/thiesgerken/carapace/commit/abbf42476eee45103621b8e800963589be2885ff))

- 💄 style: simplify admin settings labels
  ([`b71240b`](https://github.com/thiesgerken/carapace/commit/b71240b9a802604d33e7ffb156b5be05b8bb2723))

### Other


- 📝 docs: update admin user management docs
  ([`74f74e3`](https://github.com/thiesgerken/carapace/commit/74f74e3d428025ef409ad9f850cc54d8678f8c2f))

- 🔐 security: gate admin UI by user role
  ([`95a5284`](https://github.com/thiesgerken/carapace/commit/95a5284a72ebc4843ca006b033c35ac852b169c7))

- 🔐 security: require stronger admin token
  ([`b2e8e52`](https://github.com/thiesgerken/carapace/commit/b2e8e5261725e663fb3e052b2af035c31498230d))

### 🗑️ Deprecations


- 🗑️ remove standalone admin portal
  ([`8984a4d`](https://github.com/thiesgerken/carapace/commit/8984a4dc19b0e4239ed800ddef503dd62dc8a86d))

### ♻️ Refactoring


- ♻️ refactor: remove get_token auth shim
  ([`0999785`](https://github.com/thiesgerken/carapace/commit/099978544737103067b6c90fc99c9f6746e987ef))

## v0.123.3 (2026-05-24)


### ♻️ Refactoring


- ♻️ Merge pull request #171 from thiesgerken/feature/split-long-files
  ([`24bf823`](https://github.com/thiesgerken/carapace/commit/24bf823693111c987ee890f9a21bff5004fb951d))

- ♻️ refactor: backend file structure
  ([`24bf823`](https://github.com/thiesgerken/carapace/commit/24bf823693111c987ee890f9a21bff5004fb951d))

- ♻️ refactor: split engine.py into multiple files
  ([`d924c04`](https://github.com/thiesgerken/carapace/commit/d924c042e4cbdc2c944e343e6a6120e27a8d84c1))

### Other


- refactor
  ([`1ed7d6d`](https://github.com/thiesgerken/carapace/commit/1ed7d6d5d0393b67a94a8979d3e98086d025fecd))

- refactor init into history and sessions
  ([`f0be756`](https://github.com/thiesgerken/carapace/commit/f0be756d710b69357875a7b0b1bf453dd2c631b1))

- remove more legacy stuff
  ([`9b20ab4`](https://github.com/thiesgerken/carapace/commit/9b20ab4718664f7657adba6d3597925fba1afdbe))

- remove stale memory stuff and update docs
  ([`16ca62d`](https://github.com/thiesgerken/carapace/commit/16ca62d2ff785b3d6f95bf5ab421fabdfbe77a76))

- split server.py
  ([`490dcf1`](https://github.com/thiesgerken/carapace/commit/490dcf1ee81e7c795c9439f2839dd98e8f9f8266))

- use relative imports
  ([`c4aadc2`](https://github.com/thiesgerken/carapace/commit/c4aadc2c421561705f0f10c004cac5b9e1212046))

- further model refactor
  ([`8fd33b3`](https://github.com/thiesgerken/carapace/commit/8fd33b34f94fa28f90d08d7e66f158586ee977e7))

- refactor models.py into submodule
  ([`b56db99`](https://github.com/thiesgerken/carapace/commit/b56db9927a995e2fcf8ff10f08e039935b588bbd))

- approvals + usage/budget
  ([`86be3d6`](https://github.com/thiesgerken/carapace/commit/86be3d6e02b4a83a4fb5e55c22d753cedf92b9a5))

## v0.123.2 (2026-05-23)


### 🐛 Bug Fixes


- 🐛Merge pull request #168 from thiesgerken/bugfix/unknown-slash-user-message
  ([`cdb2090`](https://github.com/thiesgerken/carapace/commit/cdb2090d352103a0b2907accb24809f58ce67cc8))

- 🐛 fix: unknown slash text routing
  ([`cdb2090`](https://github.com/thiesgerken/carapace/commit/cdb2090d352103a0b2907accb24809f58ce67cc8))

- 🐛 fix: treat unknown slash text as user messages
  ([`cd0f8a6`](https://github.com/thiesgerken/carapace/commit/cd0f8a69359d030053e7e4d3a9a033f5f8212720))

## v0.123.1 (2026-05-23)


### Other


- Merge pull request #167 from thiesgerken/renovate/all-routine-dependencies
  ([`2968359`](https://github.com/thiesgerken/carapace/commit/296835948618fcbce97db41d86b1dcc9bbca2ca0))

- reorganize roadmap sections and enhance clarity on planned features
  ([`048d2ee`](https://github.com/thiesgerken/carapace/commit/048d2eefc4b9824fa943a5b4225c1fee47ff4c7e))

### ⬆️ Dependencies


- ⬆️ chore: upgrade nginx:alpine Docker digest to 7e8ff0a
  ([`2968359`](https://github.com/thiesgerken/carapace/commit/296835948618fcbce97db41d86b1dcc9bbca2ca0))

- ⬆️ chore: upgrade nginx:alpine Docker digest to 7e8ff0a
  ([`76423b8`](https://github.com/thiesgerken/carapace/commit/76423b8392ae9d66d70a00ef8f1abe4dc79683ec))

## v0.123.0 (2026-05-22)


### ✨ Features


- ✨Merge pull request #166 from thiesgerken/feature/voice-input
  ([`329c439`](https://github.com/thiesgerken/carapace/commit/329c439f0d08ea5f58aa0d84aa293cc630929ce4))

- ✨ feat: add voice input functionality to chat component
  ([`329c439`](https://github.com/thiesgerken/carapace/commit/329c439f0d08ea5f58aa0d84aa293cc630929ce4))

- ✨ feat: add voice input functionality to chat component
  ([`9b5a49c`](https://github.com/thiesgerken/carapace/commit/9b5a49ccef8de61932a07f3b020e9d10d9b840b8))

### 🐛 Bug Fixes


- 🐛 fix: prevent race condition on voice toggle
  ([`e52778f`](https://github.com/thiesgerken/carapace/commit/e52778fac2b779de1f787da79efc14160929dba6))

- 🐛 fix: resolve hydration mismatch on voice input check
  ([`3ca94cc`](https://github.com/thiesgerken/carapace/commit/3ca94ccb5164d4207b7508f46db8c329c236bd85))

### Other


- Merge branch 'main' into feature/voice-input
  ([`34f45a4`](https://github.com/thiesgerken/carapace/commit/34f45a40517f712f8acd7718b33aad20f7a56ac5))

- Merge pull request #164 from thiesgerken/renovate/all-routine-dependencies
  ([`324d40a`](https://github.com/thiesgerken/carapace/commit/324d40aace63c825b02d66c53b69a767852e32eb))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`324d40a`](https://github.com/thiesgerken/carapace/commit/324d40aace63c825b02d66c53b69a767852e32eb))

- ⬆️ chore: upgrade all routine dependency updates
  ([`1995fb0`](https://github.com/thiesgerken/carapace/commit/1995fb004f5b7e5d19cfee773b1029e94177308d))

## v0.122.0 (2026-05-22)


### ✨ Features


- ✨Merge pull request #165 from thiesgerken/feat/live-unattended-attended-toggle
  ([`76646c3`](https://github.com/thiesgerken/carapace/commit/76646c379ca98d604fa03f0f4091fbd6ca89c39b))

- ✨ feat: implement in-place unattended-attended toggles
  ([`76646c3`](https://github.com/thiesgerken/carapace/commit/76646c379ca98d604fa03f0f4091fbd6ca89c39b))

- ✨ feat: implement in-place unattended-attended toggles
  ([`0d91c32`](https://github.com/thiesgerken/carapace/commit/0d91c324a62f6047c42ed7c8cad5dc337820f90a))

### ♻️ Refactoring


- ♻️ refactor: apply bugbot autofixes for session history concurrency & safety
  ([`81dc80c`](https://github.com/thiesgerken/carapace/commit/81dc80cb88d847e182f2014a004ff51260d7645e))

## v0.121.0 (2026-05-21)


### ✨ Features


- ✨ feat: mount /tmp in pvc as well
  ([`9b49452`](https://github.com/thiesgerken/carapace/commit/9b49452c4ccb38d12e88db5628b9f5b96a5c3b2c))

## v0.120.5 (2026-05-21)


### 🐛 Bug Fixes


- 🐛 fix: increase timeouts for sentinel
  ([`140100f`](https://github.com/thiesgerken/carapace/commit/140100f2e39e3752c204c189c3c2823cd4dd97d9))

### Other


- 📋 docs: forgot a screenshot
  ([`6176b17`](https://github.com/thiesgerken/carapace/commit/6176b179f8fc84be0c6331098575a6dc0cf3eba1))

- typo
  ([`48977d5`](https://github.com/thiesgerken/carapace/commit/48977d58f5af293367cb6b11b15672dd3a64deef))

- 📋 docs: more readme changes
  ([`7d8f69c`](https://github.com/thiesgerken/carapace/commit/7d8f69c3fc1cb9ce5143f4889ebed89c4dc24bc7))

## v0.120.4 (2026-05-18)


### Other


- Merge pull request #163 from thiesgerken/renovate/all-routine-dependencies
  ([`5e33854`](https://github.com/thiesgerken/carapace/commit/5e33854940c160e23cbb10be2a056f28724bb9b9))

- 📋Merge pull request #162 from thiesgerken/docs/new-screens
  ([`6779e7f`](https://github.com/thiesgerken/carapace/commit/6779e7fe0fb85722d415ad93f31840f8886047a5))

  📋 docs: new screenshots, use cute turtle logo

- spacing
  ([`61c6bf3`](https://github.com/thiesgerken/carapace/commit/61c6bf30d4b30f0268b9f2fcf3f3f97b6c5dbcce))

- 📋 docs: new screenshots, use cute turtle logo
  ([`23b605f`](https://github.com/thiesgerken/carapace/commit/23b605f5d34f4499b236e341ea7dde43198ea5dc))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`5e33854`](https://github.com/thiesgerken/carapace/commit/5e33854940c160e23cbb10be2a056f28724bb9b9))

- ⬆️ chore: upgrade all routine dependency updates
  ([`0b6d8b7`](https://github.com/thiesgerken/carapace/commit/0b6d8b7a5dd1338803cded4d0aaeeec5279b12bd))

## v0.120.3 (2026-05-18)


### Other


- Merge pull request #161 from thiesgerken/renovate/lock-file-maintenance
  ([`1c95662`](https://github.com/thiesgerken/carapace/commit/1c9566235936b6eb8cf852d81a0d5bf6e1464e8b))

- docs: add note about matrix and CLI connectors in README
  ([`19fd98e`](https://github.com/thiesgerken/carapace/commit/19fd98efd39e3bcf936e75643a5974b969290859))

- 📋 docs: update project notes to motivation section with personal assistant rationale
  ([`44f9ae3`](https://github.com/thiesgerken/carapace/commit/44f9ae3bd10594b6ad5d3a6ba29cf4e40d6abf86))

- 📋 docs: update stale docs
  ([`036dc1d`](https://github.com/thiesgerken/carapace/commit/036dc1de9936a399276cbeed8183f70175576517))

### ⬆️ Dependencies


- ⬆️ chore: Lock file maintenance
  ([`1c95662`](https://github.com/thiesgerken/carapace/commit/1c9566235936b6eb8cf852d81a0d5bf6e1464e8b))

- ⬆️ chore: Lock file maintenance
  ([`fee3dfa`](https://github.com/thiesgerken/carapace/commit/fee3dfab00e53732f9a49a9be2bc7b2414909ec6))

## v0.120.2 (2026-05-17)


### Other


- Merge pull request #160 from thiesgerken/renovate/all-routine-dependencies
  ([`a13b795`](https://github.com/thiesgerken/carapace/commit/a13b7950726f499575aa210d850dc2a471c16bdb))

### ⬆️ Dependencies


- ⬆️ chore: upgrade all routine dependency updates
  ([`a13b795`](https://github.com/thiesgerken/carapace/commit/a13b7950726f499575aa210d850dc2a471c16bdb))

- ⬆️ chore: upgrade all routine dependency updates
  ([`fd4ff0a`](https://github.com/thiesgerken/carapace/commit/fd4ff0a1a82895b8bd6dd9070e7dd2ecdd8acb87))

## v0.120.1 (2026-05-17)


### Other


- 💚 ci: only use pyrefly, remove pyright config
  ([`ec3153f`](https://github.com/thiesgerken/carapace/commit/ec3153f919c7205e0e657a42af7d9af11ae72dce))

### 🐛 Bug Fixes


- 🐛 fix: deprecation warnings
  ([`f8ab31e`](https://github.com/thiesgerken/carapace/commit/f8ab31e2cefd28734f46fd5e3014dfee9032b97d))

## v0.120.0 (2026-05-17)


### 🐛 Bug Fixes


- 🐛 fix: tests
  ([`f6f6231`](https://github.com/thiesgerken/carapace/commit/f6f6231d391d3634691e4f61f234f6cc0f6554ac))

### ✨ Features


- ✨ feat: move shims from /root/.carapace to /workspace/.carapace for persistence
  ([`b98a1f0`](https://github.com/thiesgerken/carapace/commit/b98a1f0bd8f175e73f8258c889254a91a5351ae7))

## v0.119.5 (2026-05-15)


### 💄 UI/UX


- 💄 ui: fix ligatures for "--"
  ([`ab024fa`](https://github.com/thiesgerken/carapace/commit/ab024fa6ff9bcf4eb150202f674b4b03e7f5276d))

## v0.119.4 (2026-05-15)


### 🐛 Bug Fixes


- 🐛 fix: remove title=null
  ([`65398fc`](https://github.com/thiesgerken/carapace/commit/65398fca7709b7c6a8e872206ba1fbfec9720a98))

## v0.119.3 (2026-05-15)


### 🐛 Bug Fixes


- 🐛 fix: tell the agent that it's in readonly mode
  ([`d03be44`](https://github.com/thiesgerken/carapace/commit/d03be4434af5b03aa87abcde0d901a2610ea7561))

## v0.119.2 (2026-05-15)


### ⬆️ Dependencies


- ⬆️ chore: uv sync -U
  ([`7e593ad`](https://github.com/thiesgerken/carapace/commit/7e593ad61776b13ba281a1d3939c872dcf1c299a))

## v0.119.1 (2026-05-15)


### 🐛 Bug Fixes


- 🐛 fix: ValidationError during conflicting options during fork()
  ([`240190f`](https://github.com/thiesgerken/carapace/commit/240190f8f91e4ae9a7809d456b270935532a29ed))

## v0.119.0 (2026-05-15)


### ✨ Features


- ✨Merge pull request #158 from thiesgerken/feature/yolo_readonly
  ([`0378de0`](https://github.com/thiesgerken/carapace/commit/0378de0e3356c0a68373711054702ed54fe01917))

- ✨ feat: yolo and read-only modes for sessions
  ([`0378de0`](https://github.com/thiesgerken/carapace/commit/0378de0e3356c0a68373711054702ed54fe01917))

- ✨ feat: yolo and read-only modes for sessions
  ([`5f2dbc5`](https://github.com/thiesgerken/carapace/commit/5f2dbc557dd24928c11f82078fa9504fb03a9ee7))

### Other


- fix review comments
  ([`2d6955e`](https://github.com/thiesgerken/carapace/commit/2d6955e1bc7201922720ef7f229d5c5407e0f663))

- more aggressive grouping for renovate
  ([`2f8075e`](https://github.com/thiesgerken/carapace/commit/2f8075e93528fb8c9aef6135b5cb6e5087046925))

- fix test warnings
  ([`ce7023f`](https://github.com/thiesgerken/carapace/commit/ce7023f0bb20fb9827e3bb70cec69ae14387ef78))

- fix tests
  ([`8caa775`](https://github.com/thiesgerken/carapace/commit/8caa775772c19f00baa10b6753f528c0fd8ea6be))

- fix linter issues
  ([`fb07e7e`](https://github.com/thiesgerken/carapace/commit/fb07e7e8037dba0fd04d1abc72bab4b1cc6f21e8))

- remove default_private flag
  ([`d454078`](https://github.com/thiesgerken/carapace/commit/d454078af2d76d0a4ec8a28724717d7b31db5d41))

- improve persistent session handling in JobsView component
  ([`802cc21`](https://github.com/thiesgerken/carapace/commit/802cc212afa294bdfba59fb53fc9db75f880501c))

- augment jobs with new flags, refactor
  ([`1524d78`](https://github.com/thiesgerken/carapace/commit/1524d78ba4123a41c341ddca3f9257905f0c3b79))

### 💄 UI/UX


- 💄 styling for preferences
  ([`8fb4216`](https://github.com/thiesgerken/carapace/commit/8fb42166db220eef9fa6c96ee800561cf1e1eadc))

- 💄 ui: add theme picker
  ([`224f3d6`](https://github.com/thiesgerken/carapace/commit/224f3d68bb3d08d36f8fa709e1bc7b6a1bfdf1df))

- 💄 i18n: simplify model labels in English and German translations
  ([`31e88ec`](https://github.com/thiesgerken/carapace/commit/31e88eca5321a4205bec2e1e1a2089ba4d8b6051))

## v0.118.13 (2026-05-15)


### Other


- Merge pull request #154 from thiesgerken/renovate/ghcr.io-astral-sh-uv-python3.14-trixie-slim
  ([`d11dfea`](https://github.com/thiesgerken/carapace/commit/d11dfeaa7f4e962ef0584dd1ce95868f2b2daccd))

- Merge pull request #156 from thiesgerken/renovate/nginx-alpine
  ([`35ea6c8`](https://github.com/thiesgerken/carapace/commit/35ea6c8539ead4de2e8e1ae63a60e65384c22636))

- Merge pull request #153 from thiesgerken/renovate/ghcr.io-astral-sh-uv
  ([`876246f`](https://github.com/thiesgerken/carapace/commit/876246f3fd3c0a39e5d111a7aa9cde7fa1ae1723))

- Merge pull request #159 from thiesgerken/renovate/j178-prek-action-digest
  ([`b68b731`](https://github.com/thiesgerken/carapace/commit/b68b7319b76411fa94c6c2908de22a3f79676150))

- Merge pull request #152 from thiesgerken/renovate/pnpm-action-setup-digest
  ([`62fe9cc`](https://github.com/thiesgerken/carapace/commit/62fe9cc58508c9b42c73b0f4f243525601026eef))

- Merge pull request #151 from thiesgerken/renovate/all-minor-patch
  ([`90005af`](https://github.com/thiesgerken/carapace/commit/90005afd421d2ab63cf557a978a310164867eace))

### ⬆️ Dependencies


- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to 8090f78
  ([`d11dfea`](https://github.com/thiesgerken/carapace/commit/d11dfeaa7f4e962ef0584dd1ce95868f2b2daccd))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to 8090f78
  ([`4a22bb8`](https://github.com/thiesgerken/carapace/commit/4a22bb87c6f87ce119e55f527488f9672c31b1f7))

- ⬆️ chore: upgrade nginx:alpine Docker digest to feb6f75
  ([`35ea6c8`](https://github.com/thiesgerken/carapace/commit/35ea6c8539ead4de2e8e1ae63a60e65384c22636))

- ⬆️ chore: upgrade nginx:alpine Docker digest to feb6f75
  ([`cafb5d8`](https://github.com/thiesgerken/carapace/commit/cafb5d8dcf6306abdaa1b115322e0301fb0fa3c1))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 1025398
  ([`876246f`](https://github.com/thiesgerken/carapace/commit/876246f3fd3c0a39e5d111a7aa9cde7fa1ae1723))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 1025398
  ([`526cfa5`](https://github.com/thiesgerken/carapace/commit/526cfa55197807a9593c61b9f1ea38636e427449))

- ⬆️ chore: upgrade j178/prek-action digest to bdca6f1
  ([`b68b731`](https://github.com/thiesgerken/carapace/commit/b68b7319b76411fa94c6c2908de22a3f79676150))

- ⬆️ chore: upgrade j178/prek-action digest to bdca6f1
  ([`cadb0f6`](https://github.com/thiesgerken/carapace/commit/cadb0f6af626e1c7249d551843453335e1d713af))

- ⬆️ chore: upgrade pnpm/action-setup digest to 0e279bb
  ([`62fe9cc`](https://github.com/thiesgerken/carapace/commit/62fe9cc58508c9b42c73b0f4f243525601026eef))

- ⬆️ chore: upgrade pnpm/action-setup digest to 0e279bb
  ([`0b90802`](https://github.com/thiesgerken/carapace/commit/0b9080228a905e262c5263c7c88624f14b83ed01))

- ⬆️ chore: upgrade pnpm to 11.1.0
  ([`90005af`](https://github.com/thiesgerken/carapace/commit/90005afd421d2ab63cf557a978a310164867eace))

- ⬆️ chore: upgrade pnpm to 11.1.0
  ([`c3f51eb`](https://github.com/thiesgerken/carapace/commit/c3f51ebb18d1032a4904810710913542e36f79a6))

## v0.118.12 (2026-05-14)


### 💄 UI/UX


- 💄 ui: remove user bubble colors and update message component styling
  ([`ff13f99`](https://github.com/thiesgerken/carapace/commit/ff13f99dc737df3e40a40f6ceabf505af5ce80d4))

## v0.118.11 (2026-05-14)


### 💄 UI/UX


- 💄 ui: adjust user bubble colors in globals.css
  ([`5938c72`](https://github.com/thiesgerken/carapace/commit/5938c7275defc3e85d1e7a4a3c42d8f4db68aa2f))

- 💄 ui: update German translation for 'thinking' status
  ([`ca9bddf`](https://github.com/thiesgerken/carapace/commit/ca9bddfae218ef7876360659b30a983490851d01))

### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`af2b714`](https://github.com/thiesgerken/carapace/commit/af2b7143b37eefff518617ae7a1bb087bc175360))

## v0.118.10 (2026-05-14)


### 💄 UI/UX


- 💄 ui: update German translation for 'thinking' status
  ([`fff79d7`](https://github.com/thiesgerken/carapace/commit/fff79d7954291695a0c06759bfed1c2dc70d4324))

- 💄 ui: even more tweaking
  ([`16d7185`](https://github.com/thiesgerken/carapace/commit/16d7185b5781b42f4109153efb12f7b3b17a0b9d))

## v0.118.9 (2026-05-14)


### 🐛 Bug Fixes


- 🐛 fix(ui): pinning+grouping
  ([`41a31a8`](https://github.com/thiesgerken/carapace/commit/41a31a8da148d5d916284d3a087323d7b7ef12b3))

## v0.118.8 (2026-05-14)


### 💄 UI/UX


- 💄 ui: add archived chat visibility preference and related functionality
  ([`c2f986d`](https://github.com/thiesgerken/carapace/commit/c2f986de91b46cc81effcd746677f996536a58b1))

- 💄 ui: add model linking functionality in ChatView component
  ([`eac4e6e`](https://github.com/thiesgerken/carapace/commit/eac4e6e5a1f6cbc77cdbb6e57b6966b583e751eb))

- 💄 ui: adjust font styles and sizes in ThinkingBadge and ToolCallBadge components
  ([`2d54fd9`](https://github.com/thiesgerken/carapace/commit/2d54fd9434daf001ec2c49a8a92799d50072f7d0))

## v0.118.7 (2026-05-14)


### 💄 UI/UX


- 💄 ui: enhance session grouping by adding date sections and improving sidebar rendering
  ([`6d47437`](https://github.com/thiesgerken/carapace/commit/6d4743713e1f1e90e6a54f53c812c2e5086013e5))

## v0.118.6 (2026-05-14)


### 💄 UI/UX


- 💄 ui: disable hover buttons on mobile
  ([`4a3f262`](https://github.com/thiesgerken/carapace/commit/4a3f262b65ab66ad99876663f2f6101828cfb9bc))

## v0.118.5 (2026-05-14)


### 💄 UI/UX


- 💄 ui: allow user msgs full width as well
  ([`c37bc27`](https://github.com/thiesgerken/carapace/commit/c37bc271eb7c860c87124e916ff60a018b2394e6))

## v0.118.4 (2026-05-14)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`6cd6db7`](https://github.com/thiesgerken/carapace/commit/6cd6db773674a3bb376890b625535a4f2c50bff7))

## v0.118.3 (2026-05-14)


### 💄 UI/UX


- 💄 ui: small tweaks
  ([`4e72a24`](https://github.com/thiesgerken/carapace/commit/4e72a241acc611ea9ed4873984a5fb38da9a919a))

### 🐛 Bug Fixes


- 🐛 fix: aliases in k8s
  ([`7f41922`](https://github.com/thiesgerken/carapace/commit/7f4192253054895ed5cba5838ae71d2171b4de84))

### Other


- idea for ask mode
  ([`3395903`](https://github.com/thiesgerken/carapace/commit/33959031decbf552c4d0603776d1ef6ffb934e99))

- 🌐 fix(i18n): german thinking
  ([`53a8729`](https://github.com/thiesgerken/carapace/commit/53a8729bfa47aaae7fb737ded24dcd5abe1d0abc))

## v0.118.2 (2026-05-14)


### 💄 UI/UX


- 💄 style: refine chat detail typography
  ([`e31b011`](https://github.com/thiesgerken/carapace/commit/e31b0110c1dc39ae04dac64a3ae8aeffa59a3f02))

## v0.118.1 (2026-05-14)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`f0b2255`](https://github.com/thiesgerken/carapace/commit/f0b22551518c95dfa6ea4a7e69af41f7d3582704))

## v0.118.0 (2026-05-14)


### 🐛 Bug Fixes


- 🐛 remove weather mention from web skill
  ([`7bde63a`](https://github.com/thiesgerken/carapace/commit/7bde63ac7ee5564eede00e0daae89776b0027c36))

### ✨ Features


- ✨ feat: inject artificial tool responses upon interrupt
  ([`d684e03`](https://github.com/thiesgerken/carapace/commit/d684e03460e9e634651db0c41c107deaeda2dbe5))

## v0.117.9 (2026-05-14)


### 💄 UI/UX


- 💄 ui: tune font size and use serif font for text body
  ([`c49d729`](https://github.com/thiesgerken/carapace/commit/c49d72923620fb88322c011262362f483e50c067))

## v0.117.8 (2026-05-14)


### 🐛 Bug Fixes


- 🐛 fix: rerun skill setup after sandbox resume
  ([`5eda3a1`](https://github.com/thiesgerken/carapace/commit/5eda3a1b37ae073633374e323b664424a789c1fe))

## v0.117.7 (2026-05-14)


### 💄 UI/UX


- 💄 ui: two line tool calls
  ([`51340bb`](https://github.com/thiesgerken/carapace/commit/51340bb599af1abf5cb9f01e992fb9e9b5ae1387))

## v0.117.6 (2026-05-14)


### 🐛 Bug Fixes


- 🐛 fix: skip archive warning without sandbox state
  ([`ac00cbb`](https://github.com/thiesgerken/carapace/commit/ac00cbb44df5953bccddd6134b400afc879de021))

## v0.117.5 (2026-05-14)


### 🐛 Bug Fixes


- 🐛Merge pull request #157 from thiesgerken/feature/notifications
  ([`ffcd0f2`](https://github.com/thiesgerken/carapace/commit/ffcd0f227689dc55496ff7eb45a422a45d79e71d))

### ♻️ Refactoring


- ♻️ refactor: drop dead renotify path
  ([`ffcd0f2`](https://github.com/thiesgerken/carapace/commit/ffcd0f227689dc55496ff7eb45a422a45d79e71d))

- ♻️ refactor: drop dead renotify path
  ([`adb2f10`](https://github.com/thiesgerken/carapace/commit/adb2f102c440a9f2ff073b67cfeb9bb582faa28d))

### Other


- roadmap
  ([`82589db`](https://github.com/thiesgerken/carapace/commit/82589db39bb0d43a9b2639b00559bd740d05007c))

- Merge remote-tracking branch 'refs/remotes/origin/feature/notifications' into feature/notifications
  ([`75d5c64`](https://github.com/thiesgerken/carapace/commit/75d5c643b15928ee1e1ad29dbe10a25936b5f5be))

## v0.117.4 (2026-05-14)


### ✨ Features


- ✨Merge pull request #155 from thiesgerken/feature/notifications
  ([`64f4d69`](https://github.com/thiesgerken/carapace/commit/64f4d69894a1e1906514eaa1ecb042d3e3f57ca4))

- ✨ feat: notifications
  ([`64f4d69`](https://github.com/thiesgerken/carapace/commit/64f4d69894a1e1906514eaa1ecb042d3e3f57ca4))

### Other


- more linting
  ([`f326581`](https://github.com/thiesgerken/carapace/commit/f326581c1cbf778bede7d29bc17412a984e669ae))

- remove some logs again
  ([`d74558a`](https://github.com/thiesgerken/carapace/commit/d74558a46a03fc6286ca9f1320b8c3ca4d20a02e))

- renotify
  ([`402b726`](https://github.com/thiesgerken/carapace/commit/402b72605734e8f3a343ca80bd55142166cf4632))

- add debug logs
  ([`efa57aa`](https://github.com/thiesgerken/carapace/commit/efa57aa55dc1d884586b1a5534ff561d4ddd5cf3))

- cors
  ([`bfe6c8e`](https://github.com/thiesgerken/carapace/commit/bfe6c8edd16fcd635c3530a7afe85abe79118900))

- scrollable settings container
  ([`f88f4a3`](https://github.com/thiesgerken/carapace/commit/f88f4a38ffc94700c0defc9d27ea73d0063b3ef7))

- crc
  ([`21c9615`](https://github.com/thiesgerken/carapace/commit/21c9615cc75cfd5f79f90422dae68dcdfc348669))

- fix pem loading
  ([`059ffd8`](https://github.com/thiesgerken/carapace/commit/059ffd89e9637dd38aae4792a0748724fca421e5))

- typing
  ([`0da88a9`](https://github.com/thiesgerken/carapace/commit/0da88a987f20892556d6fa977ad9cc434b953f92))

- fix typing in channel.py
  ([`aa55fe4`](https://github.com/thiesgerken/carapace/commit/aa55fe4ea257f07480f9202c4c940ce304c5ad79))

- Merge remote-tracking branch 'refs/remotes/origin/feature/notifications' into feature/notifications
  ([`cdc6b99`](https://github.com/thiesgerken/carapace/commit/cdc6b99bc7a821ebe4ed0d62a2df1d9bbc7dd2f3))

- add pyrefly
  ([`877e378`](https://github.com/thiesgerken/carapace/commit/877e3786f24af0eca1f874b1fa8fe1d85234fffa))

- make the notifications testable
  ([`512ac86`](https://github.com/thiesgerken/carapace/commit/512ac86b144e27e461ad2ff31570c5b9c3075870))

- auto-generate vapid keys
  ([`efbde84`](https://github.com/thiesgerken/carapace/commit/efbde842e8f5840f4ada53e1d8853da75ec46fb3))

- add tests
  ([`b77dbcb`](https://github.com/thiesgerken/carapace/commit/b77dbcbf42e99a1a5f8460b0cfbb1fd2c279ac66))

- crc
  ([`c20c3bf`](https://github.com/thiesgerken/carapace/commit/c20c3bf0d00ba4f715cdf076bf0ed356d87c5e5e))

- crc
  ([`c191ecc`](https://github.com/thiesgerken/carapace/commit/c191ecc89dccb7a2320bb050e99196f5cbfd609d))

- fix lint
  ([`ea069bb`](https://github.com/thiesgerken/carapace/commit/ea069bb3ed582dc1c695ab1176bd0230940a7a91))

- crc
  ([`372a81e`](https://github.com/thiesgerken/carapace/commit/372a81eef9e167ac31016106ed461d821abfdb1a))

- fix: update esbuild configuration and enhance notification subscription component
  ([`8e7b99e`](https://github.com/thiesgerken/carapace/commit/8e7b99ed4eb885b9256e96759cbbca2051a9d08d))

- remove plans
  ([`96640c6`](https://github.com/thiesgerken/carapace/commit/96640c609a9be8e033b2948a61c3f59c516348b6))

- more tests
  ([`6cf0c2b`](https://github.com/thiesgerken/carapace/commit/6cf0c2bb82afd9f16d08bcd69a13a9ea70e66517))

- more tests
  ([`06abad4`](https://github.com/thiesgerken/carapace/commit/06abad485095ca62160b9f1a972a5d4a4fc01796))

- add tests
  ([`a9810c7`](https://github.com/thiesgerken/carapace/commit/a9810c7af710f5578c5ecc264c21d31006d71535))

- notifications in ui
  ([`e87b7a9`](https://github.com/thiesgerken/carapace/commit/e87b7a958757bce111607f2941b00b16d1b88a5e))

- docs
  ([`304d330`](https://github.com/thiesgerken/carapace/commit/304d3307b6c3f75901ac9a835528faddf2f396ef))

- documentation
  ([`b91b59f`](https://github.com/thiesgerken/carapace/commit/b91b59fc832728f72b9d14be29ba4163111955e1))

- implement push delivery
  ([`fc4ba4a`](https://github.com/thiesgerken/carapace/commit/fc4ba4ae8d4d249bd8644cd22a80de9eb13afef2))

- wire presence to ui
  ([`8f0ad37`](https://github.com/thiesgerken/carapace/commit/8f0ad3709c86f03653fac600c4777b15e8029c05))

- notifications backend
  ([`4f88c88`](https://github.com/thiesgerken/carapace/commit/4f88c887716543bfb9c3ae2e7c3d065627cfbe0b))

- notification planning
  ([`ae9d19c`](https://github.com/thiesgerken/carapace/commit/ae9d19c226ff8e643086258a773e0891bac06afc))

### 🐛 Bug Fixes


- 🐛 fix: address notification review feedback
  ([`e65ad75`](https://github.com/thiesgerken/carapace/commit/e65ad75a050a3273cdbf5a1119bbcae88cbeecbe))

- 🐛 fix: harden web presence heartbeats
  ([`25fce02`](https://github.com/thiesgerken/carapace/commit/25fce021c24af66857a1bddc96a999f127c84017))

- 🐛 fix: retain pending notification targets on clear failures
  ([`e83c201`](https://github.com/thiesgerken/carapace/commit/e83c20182c96594edc2353398f50633d135e948f))

### ♻️ Refactoring


- ♻️ refactor: derive VAPID public key from private key
  ([`a0d77b1`](https://github.com/thiesgerken/carapace/commit/a0d77b152ef9acdd71488f18e31eb1555b79f887))

## v0.117.3 (2026-05-12)


### 🐛 Bug Fixes


- 🐛 better locale detection
  ([`734543b`](https://github.com/thiesgerken/carapace/commit/734543b8de35afbcb5d55060893439f9a0265b60))

## v0.117.2 (2026-05-12)


### 💄 UI/UX


- 💄 ui: add model filtering functionality for model picker
  ([`28a594b`](https://github.com/thiesgerken/carapace/commit/28a594bfc3d31e3ec3bacf0ba82f5c39f0ade462))

### Other


- 💚 ci: update renovate configuration to include group:allNonMajor
  ([`91ef0a9`](https://github.com/thiesgerken/carapace/commit/91ef0a971eb43d68605ea61d3f5125229c27f2b0))

## v0.117.1 (2026-05-11)


### 🐛 Bug Fixes


- 🐛 fixes for mobile layout
  ([`1a47dfb`](https://github.com/thiesgerken/carapace/commit/1a47dfb47930ce866039fab3bd52beefefe8e22c))

## v0.117.0 (2026-05-11)


### ✨ Features


- ✨ feat: model pickers for jobs and sessions
  ([`0a71183`](https://github.com/thiesgerken/carapace/commit/0a71183d424c71596feff4b431f843327fbfd429))

## v0.116.0 (2026-05-11)


### ✨ Features


- ✨🔥Merge pull request #149 from thiesgerken/feature/model-slash
  ([`9537c74`](https://github.com/thiesgerken/carapace/commit/9537c74dbd82d2b670e1a36287af08e318db4d06))

- ✨🔥 feat: clean up slash commands
  ([`9537c74`](https://github.com/thiesgerken/carapace/commit/9537c74dbd82d2b670e1a36287af08e318db4d06))

- ✨ fix: correct argument matching in /model command suggestions
  ([`1d01f44`](https://github.com/thiesgerken/carapace/commit/1d01f44665d0d768776f09be5affd99b3768b1d6))

- ✨ feat: /model <role> <model> instead of /model-<role> commands
  ([`33964b6`](https://github.com/thiesgerken/carapace/commit/33964b624c7910cac3327ca4868c624d87e302d2))

### Other


- better /models slash command
  ([`8d37e5f`](https://github.com/thiesgerken/carapace/commit/8d37e5f47790d17ace15df1b925e77064b482127))

- 🔥 cleanup more slash commands
  ([`1e75277`](https://github.com/thiesgerken/carapace/commit/1e7527752a9cc1b44dc71bd2ebe53a25559e686a))

- 🔥 remove legacy slash commands for model setting
  ([`11abf1a`](https://github.com/thiesgerken/carapace/commit/11abf1ae65662e3eb370db73163bd88c2d3dba8d))

- 🔥 remove /verbose slash command in web ui
  ([`9606834`](https://github.com/thiesgerken/carapace/commit/96068342ba9f48147c7bd6fdb74c7b61799c14b1))

## v0.115.1 (2026-05-11)


### Other


- Merge pull request #146 from thiesgerken/renovate/ghcr.io-astral-sh-uv
  ([`16eed45`](https://github.com/thiesgerken/carapace/commit/16eed457e1b8b8b3dfebb2128ef2a79f3146f698))

- Merge pull request #147 from thiesgerken/renovate/ghcr.io-astral-sh-uv-python3.14-trixie-slim
  ([`60f694f`](https://github.com/thiesgerken/carapace/commit/60f694f20a1536341198b4f05b90716fe20f0008))

- Merge pull request #145 from thiesgerken/renovate/lock-file-maintenance
  ([`e9462d6`](https://github.com/thiesgerken/carapace/commit/e9462d679df8f6efbbf7dd036c3bc068e6fd4b9f))

- Merge pull request #148 from thiesgerken/renovate/pnpm-action-setup-digest
  ([`c906a03`](https://github.com/thiesgerken/carapace/commit/c906a032af9ae134d2b55ac6eb80b68f1cd73077))

### ⬆️ Dependencies


- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 841c8e6
  ([`16eed45`](https://github.com/thiesgerken/carapace/commit/16eed457e1b8b8b3dfebb2128ef2a79f3146f698))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 841c8e6
  ([`42e1ba2`](https://github.com/thiesgerken/carapace/commit/42e1ba26f0293a6d204d019d3ed9c0e4626a9909))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to f0b28d1
  ([`60f694f`](https://github.com/thiesgerken/carapace/commit/60f694f20a1536341198b4f05b90716fe20f0008))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to f0b28d1
  ([`42fda20`](https://github.com/thiesgerken/carapace/commit/42fda2051b2a0deb71457b1d2eb148a6674a9b05))

- ⬆️ chore: Lock file maintenance
  ([`e9462d6`](https://github.com/thiesgerken/carapace/commit/e9462d679df8f6efbbf7dd036c3bc068e6fd4b9f))

- ⬆️ chore: Lock file maintenance
  ([`a898cf1`](https://github.com/thiesgerken/carapace/commit/a898cf1f403ccd420a814e14b65bc5621986e76f))

- ⬆️ chore: upgrade pnpm/action-setup digest to 739bfe4
  ([`c906a03`](https://github.com/thiesgerken/carapace/commit/c906a032af9ae134d2b55ac6eb80b68f1cd73077))

- ⬆️ chore: upgrade pnpm/action-setup digest to 739bfe4
  ([`2f03ac4`](https://github.com/thiesgerken/carapace/commit/2f03ac4a52758425d5047a6cb29f9979923288f5))

## v0.115.0 (2026-05-11)


### ✨ Features


- ✨ feat: make the ui installable as a PWA
  ([`43ca221`](https://github.com/thiesgerken/carapace/commit/43ca221c7ed03a8099662fab3a2cec83282ac043))

## v0.114.2 (2026-05-11)


### 🐛 Bug Fixes


- 🐛 fix: normalize exec title fallbacks
  ([`d9f1664`](https://github.com/thiesgerken/carapace/commit/d9f16643e6604f494c95facff4296b76ffe8ceeb))

## v0.114.1 (2026-05-10)


### 🐛 Bug Fixes


- 🐛 fix: normalizeOptionalLabel to filter out empty-ish response from agent for title of exec call
  ([`aa940f2`](https://github.com/thiesgerken/carapace/commit/aa940f203566b09b8d91c810955a68aacedd8020))

## v0.114.0 (2026-05-10)


### ✨ Features


- ✨🌐Merge pull request #144 from thiesgerken/feature/i18n
  ([`6546319`](https://github.com/thiesgerken/carapace/commit/6546319a519b8694878213f9b0f95d4e2e730e37))

- ✨🌐 feat: frontend i18n
  ([`6546319`](https://github.com/thiesgerken/carapace/commit/6546319a519b8694878213f9b0f95d4e2e730e37))

### Other


- roadmap
  ([`56c99fe`](https://github.com/thiesgerken/carapace/commit/56c99feea6ac8eac8b9f3180546421707d833690))

- docs
  ([`7a57f73`](https://github.com/thiesgerken/carapace/commit/7a57f731598b6c2e1a8bf52d32582ffdcc63675e))

- fix: replace useLayoutEffect with useEffect in HomeContent for better performance
  ([`637b0a4`](https://github.com/thiesgerken/carapace/commit/637b0a4222c736b4298da283fd740ea71963663f))

- feat: add code block copy functionality with internationalization support
  ([`ce6bf22`](https://github.com/thiesgerken/carapace/commit/ce6bf22843060597d3d498dacf90444d78ecd6cc))

- more i18n
  ([`9c3ee20`](https://github.com/thiesgerken/carapace/commit/9c3ee20b47e6ce6e4a6462bc9579389540966943))

- feat: add internationalization support for new session button
  ([`34bdc5e`](https://github.com/thiesgerken/carapace/commit/34bdc5e91d7cc679e27d2a261e3c4af6b1593257))

- fix: update German translations for preferences and improve error handling in JobsView
  ([`b946830`](https://github.com/thiesgerken/carapace/commit/b9468304949dc7dd71e56ae98e98f9aca813d39e))

- fix: update HomeContent to use useLayoutEffect and include searchParamsKey
  ([`5cf545c`](https://github.com/thiesgerken/carapace/commit/5cf545c032120f33dfdbb5e6db8676c531352a69))

- further i18n
  ([`91cf87d`](https://github.com/thiesgerken/carapace/commit/91cf87d56e0fd08d800ff365c312acd64be984c0))

- i18n
  ([`e0aade6`](https://github.com/thiesgerken/carapace/commit/e0aade6ade3dd8159cdade7ce08de9bf3aa3ed2f))

- ui ux fixes
  ([`132c9c5`](https://github.com/thiesgerken/carapace/commit/132c9c5000b0e4553a40bf24453b257e61f89e50))

- Merge remote-tracking branch 'refs/remotes/origin/feature/i18n' into feature/i18n
  ([`b014fa7`](https://github.com/thiesgerken/carapace/commit/b014fa78a3ec2633db60bc86c49a5e5bb7dddec0))

- Merge branch 'main' into feature/i18n
  ([`bfac240`](https://github.com/thiesgerken/carapace/commit/bfac24088ccf5bd8f42107b5024698517aa06ca7))

## v0.113.3 (2026-05-10)


### 🐛 Bug Fixes


- 🐛 fix reuse check for Twemoji preparation
  ([`c0a91f4`](https://github.com/thiesgerken/carapace/commit/c0a91f4ed22a68c370a044b6f1f6465cef1f2c21))

## v0.113.2 (2026-05-10)


### 🐛 Bug Fixes


- 🐛 fix: replace button with span for unattended session indicator
  ([`3e1e1a9`](https://github.com/thiesgerken/carapace/commit/3e1e1a9428c7aca40717e6f8a54e6d8529a1b409))

- 🐛 fix: keep locale under settings tabs
  ([`dc23481`](https://github.com/thiesgerken/carapace/commit/dc23481e5a6857a4a24836c90c53095ae13fbfa0))

### Other


- fix: update initial active session logic based on view type
  ([`75e89d4`](https://github.com/thiesgerken/carapace/commit/75e89d4f747235dda68b78b7079d9dc51e1f9e98))

- fix: correct German translations in de.json
  ([`94f89d0`](https://github.com/thiesgerken/carapace/commit/94f89d0d51168af76df29630238f940ae0643d8d))

- fix lint issues
  ([`387905e`](https://github.com/thiesgerken/carapace/commit/387905e58251e502625b4711b65f83c277eca857))

- Merge remote-tracking branch 'origin/main' into feature/i18n
  ([`1201178`](https://github.com/thiesgerken/carapace/commit/12011788cc37001bd9d0f098b6a9aede02f95a9a))

- ideas
  ([`23c2214`](https://github.com/thiesgerken/carapace/commit/23c221421dddef81c8388eba14144e26d3f43a69))

## v0.113.1 (2026-05-10)


### ✨ Features


- ✨Merge pull request #141 from thiesgerken/feature/favicon-version
  ([`9aab266`](https://github.com/thiesgerken/carapace/commit/9aab26632f1d76e76bcd5d500885556d4c478098))

- ✨ style: favicon + add version display
  ([`9aab266`](https://github.com/thiesgerken/carapace/commit/9aab26632f1d76e76bcd5d500885556d4c478098))

### Other


- Merge branch 'main' into feature/favicon-version
  ([`75a45c5`](https://github.com/thiesgerken/carapace/commit/75a45c583ed37b9cd4d847c09442bd748aaaebb3))

- Merge pull request #143 from thiesgerken/renovate/pnpm-11.x
  ([`7d90d33`](https://github.com/thiesgerken/carapace/commit/7d90d33247b0e1837a8b5bd71d036a12142fa825))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 11.0.8
  ([`7d90d33`](https://github.com/thiesgerken/carapace/commit/7d90d33247b0e1837a8b5bd71d036a12142fa825))

- ⬆️ chore: upgrade pnpm to 11.0.8
  ([`800504e`](https://github.com/thiesgerken/carapace/commit/800504e5774f172a505f3d0bee4ec75401b660c7))

## v0.113.0 (2026-05-10)


### ✨ Features


- ✨Merge pull request #140 from thiesgerken/feature/cron
  ([`649e117`](https://github.com/thiesgerken/carapace/commit/649e117de85d7ea943ebf3c9d6296406445d6ef2))

- ✨ feat: add (cron)jobs
  ([`649e117`](https://github.com/thiesgerken/carapace/commit/649e117de85d7ea943ebf3c9d6296406445d6ef2))

### 🐛 Bug Fixes


- 🐛 fix: address follow-up review comments
  ([`b94d293`](https://github.com/thiesgerken/carapace/commit/b94d293643f3cc7d5f7b45a2da8ebdbf2ccba5a7))

- 🐛 fix: address remaining frontend review comments
  ([`4835dca`](https://github.com/thiesgerken/carapace/commit/4835dca780392154b84f4243c190fdf15ee54a01))

## v0.112.4 (2026-05-09)


### ✨ Features


- ✨ feat: add frontend i18n foundation
  ([`6d1dab3`](https://github.com/thiesgerken/carapace/commit/6d1dab3c19f82e4adf378bfd914dd6c71445676e))

- ✨ feat: update document title based on active session and view
  ([`2f63122`](https://github.com/thiesgerken/carapace/commit/2f63122ec26fddc66f28b07558bfb9d87e79c19c))

- ✨ feat: improve job run data and jobs ui
  ([`96afbba`](https://github.com/thiesgerken/carapace/commit/96afbbaea991259a059df45d08e33c6cd35ccc0f))

- ✨ feat: add (cron)jobs
  ([`9372a01`](https://github.com/thiesgerken/carapace/commit/9372a01822360ba86e20e2c923d94e7b0c4ad35d))

### Other


- Merge remote-tracking branch 'origin/feature/cron' into feature/favicon-version
  ([`d0de72c`](https://github.com/thiesgerken/carapace/commit/d0de72c1ecece7c7b7f202e8a569231911aea205))

- add timezone support for cron job triggers and corresponding tests
  ([`3e39444`](https://github.com/thiesgerken/carapace/commit/3e39444cfc3606b65ee3f065eb447a98d2eff02e))

- fix twemoji setup
  ([`02186f5`](https://github.com/thiesgerken/carapace/commit/02186f562c019dc55a86ef6e7864fd510e9171d4))

- pnpm update
  ([`c2a6a99`](https://github.com/thiesgerken/carapace/commit/c2a6a996c9f3a4ed76bb767303613fd3f407236a))

- fix hash
  ([`0b24400`](https://github.com/thiesgerken/carapace/commit/0b244007bfbd3529c50d76c3eb02d889c9098bea))

- improve job UI
  ([`29888ba`](https://github.com/thiesgerken/carapace/commit/29888ba7e015b4d3f4c6409bb844ecf35790019c))

- better timestamps for the agent
  ([`001e1da`](https://github.com/thiesgerken/carapace/commit/001e1da7f379947d6ca257eb7bd1f993820a3771))

- fix tests
  ([`b290c77`](https://github.com/thiesgerken/carapace/commit/b290c77dd9a9a9825218440ab86af000237c0989))

- improve job prompts
  ([`6c0288f`](https://github.com/thiesgerken/carapace/commit/6c0288fc2596443b54109fa0fd0e6585e063d04e))

- ui: add a nice cron display
  ([`de86dfd`](https://github.com/thiesgerken/carapace/commit/de86dfdcd85e1df2da6d1263699cb0455302196c))

- Add aria-labels to buttons in Sidebar for improved accessibility
  ([`1f018d1`](https://github.com/thiesgerken/carapace/commit/1f018d12b57695e6af723c77f67d6856513acfda))

- Merge branch 'feature/cron' into feature/favicon-version
  ([`7328d8e`](https://github.com/thiesgerken/carapace/commit/7328d8ee2a38ec6dcaa2d40b628e0634386241bd))

- Merge remote-tracking branch 'origin/main' into feature/cron
  ([`ec1b2db`](https://github.com/thiesgerken/carapace/commit/ec1b2db238c4048503c73b5ff988d1f40273bc1f))

- Merge pull request #138 from thiesgerken/renovate/ghcr.io-astral-sh-uv-python3.14-trixie-slim
  ([`b323d50`](https://github.com/thiesgerken/carapace/commit/b323d50779d5970cffaf1797ca9bb993ff7f9110))

- Merge pull request #136 from thiesgerken/renovate/debian-trixie-20260505
  ([`3b99732`](https://github.com/thiesgerken/carapace/commit/3b997320324798925c960907045a6275c385c2b9))

- Merge pull request #137 from thiesgerken/renovate/ghcr.io-astral-sh-uv
  ([`7fe4192`](https://github.com/thiesgerken/carapace/commit/7fe419202ae22f346900cdeec9e987e99e72ff62))

- Merge pull request #139 from thiesgerken/renovate/pnpm-action-setup-digest
  ([`10b5dcf`](https://github.com/thiesgerken/carapace/commit/10b5dcf7320ef369bb9441a810d66206bd3e2f57))

- Merge pull request #142 from thiesgerken/renovate/redis-8-alpine
  ([`ff7aa7e`](https://github.com/thiesgerken/carapace/commit/ff7aa7e0d75dc7f0ffa53e52bbec4b65e342cc60))

- favicon
  ([`def5d78`](https://github.com/thiesgerken/carapace/commit/def5d78e2ec8bd0dc366be11cadc0b4018170a1d))

- Merge branch 'feature/cron' into feature/favicon-version
  ([`4bc8e0e`](https://github.com/thiesgerken/carapace/commit/4bc8e0e86871066787eedc1a3f57d833b9b2fc35))

- add route
  ([`dfc5ba6`](https://github.com/thiesgerken/carapace/commit/dfc5ba63be2edba4eecab8502bec0c59bb5b13da))

- add version display
  ([`88068af`](https://github.com/thiesgerken/carapace/commit/88068af68dc7da052b603a6994ea34b204c18868))

- 🎨 style: update turtle favicon
  ([`ec45484`](https://github.com/thiesgerken/carapace/commit/ec45484696b546c322859be2aa230bdef1866443))

- ui for cronjobs
  ([`7ab651c`](https://github.com/thiesgerken/carapace/commit/7ab651c1bc31487f66c0201911aa586255e80f47))

- add scheduler service
  ([`72f3da5`](https://github.com/thiesgerken/carapace/commit/72f3da548aff321049dbdd8fd154a4284985ccfa))

- docs: update roadmap to include new features and remove memory section
  ([`13e8e43`](https://github.com/thiesgerken/carapace/commit/13e8e432c787064acce23b28caba6a4805c2d40e))

### ♻️ Refactoring


- ♻️ refactor: drop dead CARAPACE_VERSION fallback and test /api/meta
  ([`52d2b3a`](https://github.com/thiesgerken/carapace/commit/52d2b3a4add9ad78e3a0c59810fe66500b8fb0f4))

### ⬆️ Dependencies


- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to 4ec5872
  ([`b323d50`](https://github.com/thiesgerken/carapace/commit/b323d50779d5970cffaf1797ca9bb993ff7f9110))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to 4ec5872
  ([`8b54e0d`](https://github.com/thiesgerken/carapace/commit/8b54e0d70157efd24780b3f5b7c13e346c22c821))

- ⬆️ chore: upgrade debian:trixie-20260505 Docker digest to e2d08da
  ([`3b99732`](https://github.com/thiesgerken/carapace/commit/3b997320324798925c960907045a6275c385c2b9))

- ⬆️ chore: upgrade debian:trixie-20260505 Docker digest to e2d08da
  ([`1943b32`](https://github.com/thiesgerken/carapace/commit/1943b32de4cbd7d899e6d31c00c6f77c3d78def9))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 3a59a3c
  ([`7fe4192`](https://github.com/thiesgerken/carapace/commit/7fe419202ae22f346900cdeec9e987e99e72ff62))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 3a59a3c
  ([`3f78150`](https://github.com/thiesgerken/carapace/commit/3f78150ef7cbcce93862aa81c298f9687e957266))

- ⬆️ chore: upgrade pnpm/action-setup digest to 91ab88e
  ([`10b5dcf`](https://github.com/thiesgerken/carapace/commit/10b5dcf7320ef369bb9441a810d66206bd3e2f57))

- ⬆️ chore: upgrade pnpm/action-setup digest to 91ab88e
  ([`bc6c72e`](https://github.com/thiesgerken/carapace/commit/bc6c72eec5277a5407fb4bf7528ffd028b873e2f))

- ⬆️ chore: upgrade redis:8-alpine Docker digest to d146f83
  ([`ff7aa7e`](https://github.com/thiesgerken/carapace/commit/ff7aa7e0d75dc7f0ffa53e52bbec4b65e342cc60))

- ⬆️ chore: upgrade redis:8-alpine Docker digest to d146f83
  ([`a2c84a1`](https://github.com/thiesgerken/carapace/commit/a2c84a1a709b4d6b1b4cb1a44f847979c94f1757))

### 🐛 Bug Fixes


- 🐛 fix: auto-generate Job ID from name input and prevent running unsaved jobs
  ([`83a556c`](https://github.com/thiesgerken/carapace/commit/83a556c35a9f2e9b5338bd098c7ff00259f06cd2))

- 🐛 fix: avoid duplicate cron boundary runs
  ([`939f7ae`](https://github.com/thiesgerken/carapace/commit/939f7ae710f989332325fe23b3e585b2a5d677ec))

- 🐛 fix: address jobs review comments
  ([`a3d1433`](https://github.com/thiesgerken/carapace/commit/a3d1433b4e55e321099b66ba9ad460ee1f677982))

### 💄 UI/UX


- 💄 style: polish sidebar navigation
  ([`bf1866a`](https://github.com/thiesgerken/carapace/commit/bf1866aa6fdd2e368445c3854e0fb86544a244b0))

## v0.112.3 (2026-05-08)


### Other


- Merge pull request #130 from thiesgerken/renovate/redis-8.x
  ([`0c8226b`](https://github.com/thiesgerken/carapace/commit/0c8226b6dba02ddbe0472474ebbcec3c0fa2e9fe))

- Merge pull request #132 from thiesgerken/renovate/pnpm-11.x
  ([`a53a884`](https://github.com/thiesgerken/carapace/commit/a53a88426d4518b022f0b5fdf5b699362298b6c9))

- Merge pull request #131 from thiesgerken/renovate/redis-7.x
  ([`8008168`](https://github.com/thiesgerken/carapace/commit/800816818ef9567de320a5c6592d434a9f79285e))

- fix: cast ping method to Awaitable for proper type handling
  ([`706a28f`](https://github.com/thiesgerken/carapace/commit/706a28fb0b4820c583ebfa82173ab5964467f2bd))

- Merge branch 'main' into renovate/redis-7.x
  ([`cf7c126`](https://github.com/thiesgerken/carapace/commit/cf7c12665dedb09db6e993d6025b1aecfe45ad2f))

### ⬆️ Dependencies


- ⬆️ chore: upgrade redis Docker tag to v8
  ([`0c8226b`](https://github.com/thiesgerken/carapace/commit/0c8226b6dba02ddbe0472474ebbcec3c0fa2e9fe))

- ⬆️ chore: upgrade redis Docker tag to v8
  ([`21ca6b8`](https://github.com/thiesgerken/carapace/commit/21ca6b80b35eb4fb4329a23cf543ca228b74cc16))

- ⬆️ chore: upgrade pnpm to 11.0.6
  ([`a53a884`](https://github.com/thiesgerken/carapace/commit/a53a88426d4518b022f0b5fdf5b699362298b6c9))

- ⬆️ chore: upgrade pnpm to 11.0.6
  ([`3f1c6f6`](https://github.com/thiesgerken/carapace/commit/3f1c6f631f98e3107417f71dcf08ee9490d9e5d7))

- ⬆️ chore: upgrade redis to 7.4.0
  ([`8008168`](https://github.com/thiesgerken/carapace/commit/800816818ef9567de320a5c6592d434a9f79285e))

- ⬆️ chore: upgrade redis to 7.4.0
  ([`0c609a9`](https://github.com/thiesgerken/carapace/commit/0c609a96d68b1679065931c2e1d285f992b5408a))

## v0.112.2 (2026-05-08)


### Other


- Merge pull request #128 from thiesgerken/renovate/pin-dependencies
  ([`1cbd5f8`](https://github.com/thiesgerken/carapace/commit/1cbd5f8ed70ebdcc2ffe5fb40bfc2bdc01faab9d))

- Merge branch 'main' into renovate/pin-dependencies
  ([`a390f6a`](https://github.com/thiesgerken/carapace/commit/a390f6a357ec0b9e6cc170a9e0ba5205b3194716))

- Merge pull request #135 from thiesgerken/renovate/debian-13.x
  ([`87f9559`](https://github.com/thiesgerken/carapace/commit/87f955903fdf19ff868a438e1ca78958f9e84260))

- Merge pull request #133 from thiesgerken/renovate/pnpm-10.x
  ([`20cd320`](https://github.com/thiesgerken/carapace/commit/20cd320c70734ac3b5dc6f0bb27e1e0e24c38096))

- Merge branch 'main' into renovate/pnpm-10.x
  ([`8e69c59`](https://github.com/thiesgerken/carapace/commit/8e69c59250b6229b7d91e5792119e104961547b4))

### ⬆️ Dependencies


- ⬆️ chore: Pin redis Docker tag to 9de7101
  ([`1cbd5f8`](https://github.com/thiesgerken/carapace/commit/1cbd5f8ed70ebdcc2ffe5fb40bfc2bdc01faab9d))

- ⬆️ chore: Pin redis Docker tag to 9de7101
  ([`dd8fdc0`](https://github.com/thiesgerken/carapace/commit/dd8fdc01349cec0dc0148a57563db108382073e7))

- ⬆️ chore: upgrade debian Docker tag to trixie-20260505
  ([`87f9559`](https://github.com/thiesgerken/carapace/commit/87f955903fdf19ff868a438e1ca78958f9e84260))

- ⬆️ chore: upgrade debian Docker tag to trixie-20260505
  ([`39589bc`](https://github.com/thiesgerken/carapace/commit/39589bc27ca688160777d86276d15ea970817f9f))

- ⬆️ chore: upgrade pnpm to 10.33.3
  ([`20cd320`](https://github.com/thiesgerken/carapace/commit/20cd320c70734ac3b5dc6f0bb27e1e0e24c38096))

## v0.112.1 (2026-05-08)


### Other


- Merge pull request #127 from thiesgerken/renovate/ghcr.io-astral-sh-uv-python3.14-trixie-slim
  ([`0f13148`](https://github.com/thiesgerken/carapace/commit/0f13148a49ae514566ccfeed12c097e32fa0a8b6))

- Merge pull request #126 from thiesgerken/renovate/ghcr.io-astral-sh-uv
  ([`3aff610`](https://github.com/thiesgerken/carapace/commit/3aff61077c9732797fea8af04d49fe2deb0d47da))

- Merge pull request #125 from thiesgerken/renovate/pnpm-action-setup-digest
  ([`b3face9`](https://github.com/thiesgerken/carapace/commit/b3face934957324b521a5577731ddda3e774bd40))

- Merge pull request #129 from thiesgerken/renovate/docker.io-library-redis-8.x
  ([`3af0e25`](https://github.com/thiesgerken/carapace/commit/3af0e25f69b91399c1064ba74aaa930dcdddfba2))

### ⬆️ Dependencies


- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to 3e70f58
  ([`0f13148`](https://github.com/thiesgerken/carapace/commit/0f13148a49ae514566ccfeed12c097e32fa0a8b6))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to 3e70f58
  ([`b761294`](https://github.com/thiesgerken/carapace/commit/b761294bca7794e390d0bbc9fe30b781c7893c8e))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 798712e
  ([`3aff610`](https://github.com/thiesgerken/carapace/commit/3aff61077c9732797fea8af04d49fe2deb0d47da))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 798712e
  ([`4adb946`](https://github.com/thiesgerken/carapace/commit/4adb94659e650a0c652a4e0e906dd00200b1c252))

- ⬆️ chore: upgrade pnpm/action-setup digest to 8912a91
  ([`b3face9`](https://github.com/thiesgerken/carapace/commit/b3face934957324b521a5577731ddda3e774bd40))

- ⬆️ chore: upgrade pnpm/action-setup digest to 8912a91
  ([`22695d2`](https://github.com/thiesgerken/carapace/commit/22695d2d98a4b6f75d972a10deb3ff34290fd457))

- ⬆️ chore: upgrade docker.io/library/redis Docker tag to v8
  ([`3af0e25`](https://github.com/thiesgerken/carapace/commit/3af0e25f69b91399c1064ba74aaa930dcdddfba2))

- ⬆️ chore: upgrade docker.io/library/redis Docker tag to v8
  ([`3185041`](https://github.com/thiesgerken/carapace/commit/3185041f43722aa62d112406e207e125339c37dc))

## v0.112.0 (2026-05-08)


### 🐛 Bug Fixes


- 🐛Merge pull request #134 from thiesgerken/fix/ci-builds
  ([`993caf7`](https://github.com/thiesgerken/carapace/commit/993caf787e383846f61d1bcec18447f4ab2617a1))

- 🐛 fix(ci): add pnpm workspace configuration for sharp and unrs-resolver builds
  ([`993caf7`](https://github.com/thiesgerken/carapace/commit/993caf787e383846f61d1bcec18447f4ab2617a1))

- 🐛 fix(ci): add pnpm workspace configuration for sharp and unrs-resolver builds
  ([`5cdb400`](https://github.com/thiesgerken/carapace/commit/5cdb400128328f008d5331e5f2fbbd4cf0cdc4c2))

- 🐛 fix: paginate CLI session listing
  ([`a11ffae`](https://github.com/thiesgerken/carapace/commit/a11ffae40f4028834843cdb843f21b26218bd00b))

- 🐛 fix: address session list review comments
  ([`0d8eb92`](https://github.com/thiesgerken/carapace/commit/0d8eb92f307539295533c91757c1a03aca587e52))

### Other


- fix(ci): include pnpm-workspace.yaml in Dockerfile for build context
  ([`71ff82f`](https://github.com/thiesgerken/carapace/commit/71ff82f46b5e9daddd8f61c2a5538d022f70b8e1))

- Merge pull request #124 from thiesgerken/renovate/lock-file-maintenance
  ([`1d6fd06`](https://github.com/thiesgerken/carapace/commit/1d6fd06937aaf62a16e95c803da9187dd0b60e39))

- fix: normalize unattended history with thinking parts and update final status handling
  ([`fb2c12a`](https://github.com/thiesgerken/carapace/commit/fb2c12a56f5ec84b4a19853c96e50df222f65a73))

- wire final messages to UI and show them
  ([`004302d`](https://github.com/thiesgerken/carapace/commit/004302d91a5a3ea12eeb5d4f7d2436a69e5c954e))

- Merge branch 'main' into feat/unattended-session-mode
  ([`2c96e5c`](https://github.com/thiesgerken/carapace/commit/2c96e5ca46473014b2294b269a37d166edd6e226))

- cache more stuff about sessions
  ([`5395ee4`](https://github.com/thiesgerken/carapace/commit/5395ee4e440e93b9ee2860fdaf6fc4a5e77ae82b))

  Co-authored-by: Copilot <copilot@github.com>

- fix lint issues
  ([`cdfb6b0`](https://github.com/thiesgerken/carapace/commit/cdfb6b03fb4e8f95a6fcdb4ca51da4a26250ce2f))

  Co-authored-by: Copilot <copilot@github.com>

- 💚 run tests in ci
  ([`9160bc2`](https://github.com/thiesgerken/carapace/commit/9160bc2615ec686be71804b422b3424c8bc5b180))

- setup pyright correctly
  ([`b11fc20`](https://github.com/thiesgerken/carapace/commit/b11fc2012cb3ac5d911d9573141b49a29e762ac7))

### ⬆️ Dependencies


- ⬆️ chore: Lock file maintenance
  ([`1d6fd06`](https://github.com/thiesgerken/carapace/commit/1d6fd06937aaf62a16e95c803da9187dd0b60e39))

- ⬆️ chore: Lock file maintenance
  ([`d39c370`](https://github.com/thiesgerken/carapace/commit/d39c370d7048e7ddc43ff9fc84edda3f37f8b127))

- ⬆️ chore: upgrade pnpm to 10.33.3
  ([`df394ff`](https://github.com/thiesgerken/carapace/commit/df394ffc006221e7e1b91ab4e111a0a9d083494a))

### ✨ Features


- ✨Merge pull request #123 from thiesgerken/feat/unattended-session-mode
  ([`f068d72`](https://github.com/thiesgerken/carapace/commit/f068d7290c0e6b7e2959f8363db41da123d9a72b))

- ✨ feat: Add unattended session mode
  ([`f068d72`](https://github.com/thiesgerken/carapace/commit/f068d7290c0e6b7e2959f8363db41da123d9a72b))

- ✨ feat: enhance ChatView and Sidebar with unattended session indicators and update NewSessionButton integration
  ([`601a236`](https://github.com/thiesgerken/carapace/commit/601a236811ac25f846262a5721ff76c76024a0f7))

- ✨ feat: add NewSessionButton component for creating sessions
  ([`f2d6d9d`](https://github.com/thiesgerken/carapace/commit/f2d6d9d63b84ec09fd15e1c0f2d29ff621e2f10d))

- ✨ feat: add unattended session mode
  ([`4e62129`](https://github.com/thiesgerken/carapace/commit/4e62129329ff62438790c0b864cb0fbb9a2cff79))

- ✨Merge pull request #122 from thiesgerken/feat/session-list-infinite-loading
  ([`6f13334`](https://github.com/thiesgerken/carapace/commit/6f13334842f2ea5c36660dceb67e883e30f9b2cb))

- ✨ feat: Paginate session list loading in the web UI
  ([`6f13334`](https://github.com/thiesgerken/carapace/commit/6f13334842f2ea5c36660dceb67e883e30f9b2cb))

- ✨ feat: add logging for disk read operations in SessionManager
  ([`f53f9ef`](https://github.com/thiesgerken/carapace/commit/f53f9ef136b12d899f323c37a99d31a090d6a052))

  Co-authored-by: Copilot <copilot@github.com>

- ✨ feat: cache session list in redis
  ([`9776618`](https://github.com/thiesgerken/carapace/commit/97766185da31e3c085a89da40f6d7e015d2e6891))

  Co-authored-by: Copilot <copilot@github.com>

### ♻️ Refactoring


- ♻️ refactor: avoid duplicate session state loads
  ([`60a0ad7`](https://github.com/thiesgerken/carapace/commit/60a0ad75809c1361a0c37d802aa4224f196baa14))

- ♻️ refactor: remove dead budget alias remap
  ([`4c03e88`](https://github.com/thiesgerken/carapace/commit/4c03e889f7a44c6f062933f347e2dda2694936fc))

- ♻️ refactor: collapse sessions page endpoint
  ([`f2b368c`](https://github.com/thiesgerken/carapace/commit/f2b368c1347dd62b19ddcb38422d09500209c8e2))

### ⚡ Performance


- ⚡ perf: paginate session list loading
  ([`b5f9043`](https://github.com/thiesgerken/carapace/commit/b5f9043b66ba455c599e5f10df3ac60e74e65a6b))

## v0.111.2 (2026-05-03)


### 🐛 Bug Fixes


- 🐛 fix: sidebar session switching area
  ([`68c40d7`](https://github.com/thiesgerken/carapace/commit/68c40d73c470acd7129e50337c7731f667592717))

### Other


- add screenshot
  ([`845dd58`](https://github.com/thiesgerken/carapace/commit/845dd58a4b4ad3dee647b63bf6b4d63c035a2375))

- docs: enhance highlights section with icons for better readability
  ([`c8cacfa`](https://github.com/thiesgerken/carapace/commit/c8cacfad701d490e7ec59e5dd7d1106708bafefb))

  Co-authored-by: Copilot <copilot@github.com>

- clean roadmap
  ([`5bab579`](https://github.com/thiesgerken/carapace/commit/5bab5796e29c0b297fb7e2e816d81bd2a0f6ee79))

- docs: update project notes with AI usage disclaimer and personal motivations
  ([`4d00038`](https://github.com/thiesgerken/carapace/commit/4d000386435eae32fa80bb984a9b585ae3d749d6))

- docs: update project notes with AI usage disclaimer and personal project motivations
  ([`d6fedb3`](https://github.com/thiesgerken/carapace/commit/d6fedb3587d113589ccd2bac0b41baf6947a6971))

- Merge pull request #121 from thiesgerken/docs/branding
  ([`9aed92f`](https://github.com/thiesgerken/carapace/commit/9aed92f7459ed414e041d789e7b30fc27e08ae8e))

  📋 docs: enhance README with Bitwarden and Vaultwarden support for context-scoped credentials

- 📋 docs: enhance README with Bitwarden and Vaultwarden support for context-scoped credentials
  ([`510547c`](https://github.com/thiesgerken/carapace/commit/510547c69fc56047f2579031bf5b939776fd9706))

  Co-authored-by: Copilot <copilot@github.com>

- Merge pull request #120 from thiesgerken/docs/branding
  ([`00efe09`](https://github.com/thiesgerken/carapace/commit/00efe09ca0e373cb81df5c2975bfb59c8ca31ea6))

  📋 docs: nicer readme, add AI-generated logo

- fix: correct casing of _COMMIT_TRAILER_KEY to "carapace-session"
  ([`c862c52`](https://github.com/thiesgerken/carapace/commit/c862c52dba453d857637c29de78ce83f5fac43b5))

- refactor: standardize casing of "Carapace" to "carapace" across documentation and codebase
  ([`42631e4`](https://github.com/thiesgerken/carapace/commit/42631e438315afa8c1c27ad31b03b7d2002eb3a6))

- use banner
  ([`779c7e1`](https://github.com/thiesgerken/carapace/commit/779c7e1b525639e1d8e84f6471244120b1d38fb4))

- 📋 docs: update README formatting and remove unnecessary horizontal rule
  ([`453a721`](https://github.com/thiesgerken/carapace/commit/453a721f9c79322bac34c8d0c574d984198a9be7))

  Co-authored-by: Copilot <copilot@github.com>

- 📋 docs: nicer readme, add AI-generated logo
  ([`aea2f8b`](https://github.com/thiesgerken/carapace/commit/aea2f8bdafaf75f07c3dafa8267ead202e7bd74a))

  Co-authored-by: Copilot <copilot@github.com>

- 📋 docs: clarify roles of events.yaml and history.yaml better
  ([`314f2fb`](https://github.com/thiesgerken/carapace/commit/314f2fb8e53dc163ad1d29c644afe5f13ccddd1d))

## v0.111.1 (2026-05-02)


### ♻️ Refactoring


- ♻️Merge pull request #119 from thiesgerken/refactor/session_tests
  ([`594ff06`](https://github.com/thiesgerken/carapace/commit/594ff068dc5eac477b66383d05b8cc651ae7d0c4))

- ♻️ refactor: split session tests into multiple files
  ([`594ff06`](https://github.com/thiesgerken/carapace/commit/594ff068dc5eac477b66383d05b8cc651ae7d0c4))

- ♻️ refactor: remove redundant import of carapace.usage in test_session_engine_lifecycle.py
  ([`eb4e7bb`](https://github.com/thiesgerken/carapace/commit/eb4e7bb9b0d0f17d0bd0cb375f7b8ee69e8329a3))

  Co-authored-by: Copilot <copilot@github.com>

- ♻️ refactor: split session tests into multiple files
  ([`a3221e5`](https://github.com/thiesgerken/carapace/commit/a3221e52bb6e9caa6f95afb1cbd06bfd13eb17d6))

  Co-authored-by: Copilot <copilot@github.com>

## v0.111.0 (2026-05-02)


### ✨ Features


- ✨Merge pull request #118 from thiesgerken/feature/tool-budget
  ([`daec073`](https://github.com/thiesgerken/carapace/commit/daec0739177305476b692d470cfb0ab2527b4a1b))

- ✨ feat: make tool calls budgetable
  ([`daec073`](https://github.com/thiesgerken/carapace/commit/daec0739177305476b692d470cfb0ab2527b4a1b))

- ✨ feat: make tool calls budgetable
  ([`13364ef`](https://github.com/thiesgerken/carapace/commit/13364efb6a464596b31f034f43c8172ebc77292e))

  Co-authored-by: Copilot <copilot@github.com>

### 🐛 Bug Fixes


- 🐛 fix: correct tool call budget error messages and enforce budget regardless of verbose mode
  ([`aa0a031`](https://github.com/thiesgerken/carapace/commit/aa0a0313cb642c30bea1dd0fdd8c821cf5985d9a))

  Applied via @cursor push command

## v0.110.0 (2026-05-02)


### ✨ Features


- ✨Merge pull request #117 from thiesgerken/feature/sentinel-timeout
  ([`f2e4ede`](https://github.com/thiesgerken/carapace/commit/f2e4ede82a8017c6b582edf3f09bffcfef6eb75c))

- ✨ feat: add a timeout for the sentinel
  ([`f2e4ede`](https://github.com/thiesgerken/carapace/commit/f2e4ede82a8017c6b582edf3f09bffcfef6eb75c))

- ✨ feat: add a timeout for the sentinel
  ([`98dd3cc`](https://github.com/thiesgerken/carapace/commit/98dd3ccc182ca9ebca0cc75bdffde6bdd46e27d6))

## v0.109.0 (2026-05-02)


### ✨ Features


- ✨Merge pull request #116 from thiesgerken/feat/session-attributes-sidebar-controls
  ([`953481c`](https://github.com/thiesgerken/carapace/commit/953481cac0824bdf47df57dac0a895fb931351ac))

- ✨ feat: Add session attributes and sidebar controls
  ([`953481c`](https://github.com/thiesgerken/carapace/commit/953481cac0824bdf47df57dac0a895fb931351ac))

- ✨ feat: add session attributes and sidebar controls
  ([`8e83ed3`](https://github.com/thiesgerken/carapace/commit/8e83ed3032594ea384468cbada5cc7f50014783a))

### 🐛 Bug Fixes


- 🐛 fix: harden sidebar session updates
  ([`b68d744`](https://github.com/thiesgerken/carapace/commit/b68d7446dfc34660656d6f1e547b9b1fca832093))

- 🐛 fix: keep sessions active when unarchiving
  ([`a081be6`](https://github.com/thiesgerken/carapace/commit/a081be6fe08728160b7607b72d33c5ed9136bef7))

- 🐛 fix: reset forked session attributes
  ([`cf6a53c`](https://github.com/thiesgerken/carapace/commit/cf6a53cb530dbb9c878e0d6f7039968a9655f995))

- 🐛 fix: confirm sidebar destructive actions
  ([`11c06dc`](https://github.com/thiesgerken/carapace/commit/11c06dcd497253959fba720fb3ffd7504f45f10f))

## v0.108.1 (2026-05-02)


### 💄 UI/UX


- 💄 ui: update ApprovalBadge styles and icon sizes for improved UI consistency
  ([`058111d`](https://github.com/thiesgerken/carapace/commit/058111dc9913988e4539b4451ccd8837954a2e2d))

## v0.108.0 (2026-05-02)


### ✨ Features


- ✨ feat: implement auto-allow for exact domain in exec command and add corresponding tests
  ([`0c047e5`](https://github.com/thiesgerken/carapace/commit/0c047e5327faf8351639e46b70bbac3c3a854280))

  Co-authored-by: Copilot <copilot@github.com>

### Other


- ideas
  ([`642a9e4`](https://github.com/thiesgerken/carapace/commit/642a9e4ca19e324b65f822e3755177f3d3296549))

## v0.107.0 (2026-05-02)


### ✨ Features


- ✨Merge pull request #114 from thiesgerken/feat/persist-interrupted-llm-requests
  ([`648c6fa`](https://github.com/thiesgerken/carapace/commit/648c6faff42bae21fbf1a09285965f62146fbded))

- ✨ feat: Persist interrupted LLM requests on cancel
  ([`648c6fa`](https://github.com/thiesgerken/carapace/commit/648c6faff42bae21fbf1a09285965f62146fbded))

- ✨ feat: persist interrupted llm requests on cancel
  ([`91ac779`](https://github.com/thiesgerken/carapace/commit/91ac7796362687848fcd890d413142a65d5a99ec))

## v0.106.0 (2026-05-02)


### ✨ Features


- ✨Merge pull request #113 from thiesgerken/feature/auto-allow-read-execs
  ([`41199dc`](https://github.com/thiesgerken/carapace/commit/41199dc1b1406ab59c29c5e47cdbb645745e7cfb))

- ✨ feat: auto-allow some read-only exec ops
  ([`41199dc`](https://github.com/thiesgerken/carapace/commit/41199dc1b1406ab59c29c5e47cdbb645745e7cfb))

- ✨ feat: auto-allow some read-only exec ops
  ([`fb010c1`](https://github.com/thiesgerken/carapace/commit/fb010c1395e742e7b333789a5cd8c5c9c6e9a2ce))

- ✨ Merge pull request #111 from thiesgerken/fix/proxy-sentinel-domain-gating
  ([`f67a529`](https://github.com/thiesgerken/carapace/commit/f67a529e79c91fb7125982e9d41d4d1a497dd6a8))

- ✨ feat: Batch proxy sentinel domain reviews
  ([`f67a529`](https://github.com/thiesgerken/carapace/commit/f67a529e79c91fb7125982e9d41d4d1a497dd6a8))

### Other


- Merge branch 'fix/proxy-sentinel-domain-gating' into feature/auto-allow-read-execs
  ([`a2eaa4b`](https://github.com/thiesgerken/carapace/commit/a2eaa4bdd321c13cf22bc116e5b4bfde7bc34be8))

- Merge pull request #110 from thiesgerken/renovate/pnpm-action-setup-digest
  ([`875bea6`](https://github.com/thiesgerken/carapace/commit/875bea6c2ea9524cce1e3c9eb55f61447d181920))

- Fix proxy gating race and budget refund
  ([`7437bfe`](https://github.com/thiesgerken/carapace/commit/7437bfe73e0bfd823b28e5a3aa16e0fd6ea4778c))

- Show auto badge for reused domains
  ([`d87d5e9`](https://github.com/thiesgerken/carapace/commit/d87d5e9981008ea437a00b9716f9a3005f62394f))

- Deduplicate proxy domain UI rows
  ([`447d85d`](https://github.com/thiesgerken/carapace/commit/447d85dd4949a8be8a30ad6905c92fe47b6ab896))

- Merge remote-tracking branch 'origin/main' into fix/proxy-sentinel-domain-gating
  ([`3d5542b`](https://github.com/thiesgerken/carapace/commit/3d5542bc32719d3bc2852500603cc83d2c99a789))

### 🐛 Bug Fixes


- 🐛 fix: reject shell comments in exec allowlist
  ([`c7f5772`](https://github.com/thiesgerken/carapace/commit/c7f577241f882f8ae4dcfdb30558d96ea41a9747))

- 🐛 fix: tighten read-only exec allowlist matching
  ([`585f664`](https://github.com/thiesgerken/carapace/commit/585f664beaf9e0a958d12f60b7a77de25bf9f1ea))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm/action-setup digest to 26f6d4f
  ([`875bea6`](https://github.com/thiesgerken/carapace/commit/875bea6c2ea9524cce1e3c9eb55f61447d181920))

- ⬆️ chore: upgrade pnpm/action-setup digest to 26f6d4f
  ([`165779d`](https://github.com/thiesgerken/carapace/commit/165779d3936ce664a2c106bb0da61b467a5eab5c))

## v0.105.6 (2026-05-01)


### ✨ Features


- ✨Merge pull request #112 from thiesgerken/fix/model-override-persistence
  ([`1b37eae`](https://github.com/thiesgerken/carapace/commit/1b37eaebc3f4ec291ddacb6428888f198fe5e24f))

- ✨ feat: Persist model overrides across backend restarts
  ([`1b37eae`](https://github.com/thiesgerken/carapace/commit/1b37eaebc3f4ec291ddacb6428888f198fe5e24f))

### 🐛 Bug Fixes


- 🐛 fix: fall back from stale model overrides
  ([`90c3482`](https://github.com/thiesgerken/carapace/commit/90c34821732ae2b6d59846130d1cd5302907415e))

- 🐛 fix: persist model overrides across restarts
  ([`f2d4f8f`](https://github.com/thiesgerken/carapace/commit/f2d4f8fc5bf2858ba51a4becf4754b7bb04b9f8e))

### Other


- Fix proxy gating review follow-ups
  ([`33250be`](https://github.com/thiesgerken/carapace/commit/33250be2684af111df11a2d1e69da44918490c10))

- Simplify batched sentinel verdicts
  ([`1a6c75d`](https://github.com/thiesgerken/carapace/commit/1a6c75dd547993a2a37c7204bc01f596465a41ed))

- Fix proxy gating review feedback
  ([`6fa49e4`](https://github.com/thiesgerken/carapace/commit/6fa49e48a1182b801553573d408e910a9b8c3bc7))

- Batch proxy sentinel domain reviews
  ([`efc6ada`](https://github.com/thiesgerken/carapace/commit/efc6ada98d552df878d5ac947f9d72ae69d893c5))

- Fix proxy sentinel domain approval reuse and limits
  ([`72b3bf2`](https://github.com/thiesgerken/carapace/commit/72b3bf292302f1d29340809a15e2cf20cfca98bd))

## v0.105.5 (2026-05-01)


### 🐛 Bug Fixes


- 🐛 fix: add poppler-utils to Dockerfile dependencies
  ([`5992801`](https://github.com/thiesgerken/carapace/commit/5992801dd1d3851db1dbf6e05a583f05425ac2a1))

## v0.105.4 (2026-05-01)


### 🐛 Bug Fixes


- 🐛 fix: increase default timeout for SkillActivationProvider to 600 seconds
  ([`d5a4b8d`](https://github.com/thiesgerken/carapace/commit/d5a4b8d4a4588f3f8d647a188a68345f1f84a983))

## v0.105.3 (2026-05-01)


### 🐛 Bug Fixes


- 🐛 fix: set git config globally
  ([`eea4732`](https://github.com/thiesgerken/carapace/commit/eea47320d79c5a2d5808f53a7e83d2cb7d945ecc))

  Co-authored-by: Copilot <copilot@github.com>

## v0.105.2 (2026-05-01)


### 🐛 Bug Fixes


- 🐛 fix: improve formatting of sentinel review messages in ToolCallBadge
  ([`4c11dc5`](https://github.com/thiesgerken/carapace/commit/4c11dc595207e12d7061618de4b395e723e7727b))

  Co-authored-by: Copilot <copilot@github.com>

## v0.105.1 (2026-04-30)


### 🐛 Bug Fixes


- 🐛 fix: add tree to sandbox dockerfile
  ([`c6dedc3`](https://github.com/thiesgerken/carapace/commit/c6dedc356796387403e1858b88e42e46d83a8fa3))

## v0.105.0 (2026-04-30)


### ✨ Features


- ✨Merge pull request #109 from thiesgerken/feature/fork
  ([`420d6b5`](https://github.com/thiesgerken/carapace/commit/420d6b595e5afefa18dd1fe1514f1c7209600aed))

- ✨ feat: Add session fork action
  ([`420d6b5`](https://github.com/thiesgerken/carapace/commit/420d6b595e5afefa18dd1fe1514f1c7209600aed))

- ✨ feat: add session fork action
  ([`cb9ad37`](https://github.com/thiesgerken/carapace/commit/cb9ad37911659fa46c7673bec3cf793dc0304933))

### Other


- wording
  ([`71c632b`](https://github.com/thiesgerken/carapace/commit/71c632b1bc2c7c2f53da5d0120bc7fdfd6dc81c4))

## v0.104.1 (2026-04-29)


### ♻️ Refactoring


- ♻️Merge pull request #107 from thiesgerken/refactor/280426
  ([`97d82f8`](https://github.com/thiesgerken/carapace/commit/97d82f869365c7fc163600bb9bb383d9e006ac50))

- ♻️ refactor: frontend typing & engine.py split
  ([`97d82f8`](https://github.com/thiesgerken/carapace/commit/97d82f869365c7fc163600bb9bb383d9e006ac50))

### 🐛 Bug Fixes


- 🐛 fix: normalize replay contexts consistently
  ([`26ad78b`](https://github.com/thiesgerken/carapace/commit/26ad78bf4b257f48ac18ccac7e96e2fc2419b76a))

- 🐛 fix: mark unexpected output as terminal
  ([`a11fe36`](https://github.com/thiesgerken/carapace/commit/a11fe360977ddbd5eaf86de98c25ea246318a17a))

### Other


- Merge remote-tracking branch 'origin/main' into refactor/280426
  ([`66e8726`](https://github.com/thiesgerken/carapace/commit/66e8726cc9349449545bf4508107690242e9903b))

  # Conflicts: #	frontend/src/components/chat-view.tsx #	src/carapace/session/engine.py

## v0.104.0 (2026-04-29)


### Other


- Merge pull request #108 from thiesgerken/renovate/j178-prek-action-digest
  ([`aa2e915`](https://github.com/thiesgerken/carapace/commit/aa2e91588f53e1607182a2fe4a47fd3fc0049b57))

- fix: store current messages before resetting rollback reference in handleRetry
  ([`496524a`](https://github.com/thiesgerken/carapace/commit/496524afc13a04d2529aa73054a7e1aa19d5bfa6))

- implement reset rollback mechanism for error handling and message management
  ([`fa85753`](https://github.com/thiesgerken/carapace/commit/fa85753a1e03d45e76b10c2c230152d6a76b689a))

- update latest turn message index logic to handle completed turns
  ([`9490fc0`](https://github.com/thiesgerken/carapace/commit/9490fc0ce26f31db402d4925008e4f0b21ad6870))

- add history check for completed turn count excluding trailing requests
  ([`93b0da9`](https://github.com/thiesgerken/carapace/commit/93b0da976a8e4463fcfb3d9377e111bfd74dab0d))

  Co-authored-by: Copilot <copilot@github.com>

- polishing
  ([`6de70af`](https://github.com/thiesgerken/carapace/commit/6de70af221bb1592f0709d0d679cf27aefd3984f))

- refactor engine.py
  ([`b01626e`](https://github.com/thiesgerken/carapace/commit/b01626ef546b9dd25527afd69183c74e61d22d32))

  Co-authored-by: Copilot <copilot@github.com>

### ⬆️ Dependencies


- ⬆️ chore: upgrade j178/prek-action digest to 6ad8027
  ([`aa2e915`](https://github.com/thiesgerken/carapace/commit/aa2e91588f53e1607182a2fe4a47fd3fc0049b57))

- ⬆️ chore: upgrade j178/prek-action digest to 6ad8027
  ([`77a6384`](https://github.com/thiesgerken/carapace/commit/77a63843e9db8d8871b9be1adc7fd1e89711fad8))

### ✨ Features


- ✨Merge pull request #106 from thiesgerken/feature/retry_reset
  ([`5af2e0d`](https://github.com/thiesgerken/carapace/commit/5af2e0d06223b96184ac079355f7f119e341b6ba))

- ✨ feat: retry+reset for chat history
  ([`5af2e0d`](https://github.com/thiesgerken/carapace/commit/5af2e0d06223b96184ac079355f7f119e341b6ba))

- ✨ feat: retry+reset for chat history
  ([`93ddaa9`](https://github.com/thiesgerken/carapace/commit/93ddaa9b62389e371e77273f510aba5b91d47ec8))

  Co-authored-by: Copilot <copilot@github.com>

### 🐛 Bug Fixes


- 🐛 fix: clear rollback on disconnect
  ([`4187859`](https://github.com/thiesgerken/carapace/commit/418785916e18daf08550a0cbd18d17e55c957c39))

- 🐛 fix: gate reset ack on success
  ([`471d173`](https://github.com/thiesgerken/carapace/commit/471d173245a87f32de4b4023b1cceac05523a6ec))

- 🐛 fix: acknowledge reset rewind success
  ([`4dfea52`](https://github.com/thiesgerken/carapace/commit/4dfea52df99fb69ce2bf44a31be4f3dad264d440))

- 🐛 fix: distinguish terminal chat errors
  ([`d5c13f8`](https://github.com/thiesgerken/carapace/commit/d5c13f8ca78ddf9aa1a9110c8a526af0fdc4a74c))

- 🐛 fix: preserve empty model selection values
  ([`e973b37`](https://github.com/thiesgerken/carapace/commit/e973b3794a9e9604a2c0d4b5a3ca09164c11527a))

- 🐛 fix: address frontend decoding review comments
  ([`7199814`](https://github.com/thiesgerken/carapace/commit/71998147244524e27dbb14df9e218bc4093dab0b))

### ♻️ Refactoring


- ♻️ refactor: share command decoding helpers
  ([`448a8c7`](https://github.com/thiesgerken/carapace/commit/448a8c7dde601aa813de0d53586fc81d9360bcb5))

- ♻️ refactor: frontend typing
  ([`cbc6913`](https://github.com/thiesgerken/carapace/commit/cbc691324ff456e913196603417dc7946a5d7771))

## v0.103.1 (2026-04-28)


### ♻️ Refactoring


- ♻️ refactor: small linter changes
  ([`fe52812`](https://github.com/thiesgerken/carapace/commit/fe528128a0aa157783a40223f84673f6d05f5f9b))

## v0.103.0 (2026-04-28)


### ✨ Features


- ✨Merge pull request #105 from thiesgerken/feature/yaml_frontmatter
  ([`322e3a4`](https://github.com/thiesgerken/carapace/commit/322e3a43786204305d0a7d4443b06fa1b7464a10))

- ✨ feat: support putting carapace.yaml contents into SKILL.md frontmatter
  ([`322e3a4`](https://github.com/thiesgerken/carapace/commit/322e3a43786204305d0a7d4443b06fa1b7464a10))

- ✨ feat: support putting carapace.yaml contents into SKILL.md frontmatter
  ([`92d7115`](https://github.com/thiesgerken/carapace/commit/92d71159c7eaafd6c924b6f6d147c6ff6bd800f8))

  Co-authored-by: Copilot <copilot@github.com>

### Other


- fix tests
  ([`d01a8c1`](https://github.com/thiesgerken/carapace/commit/d01a8c156223262237a04bddb0c8e705b2a07650))

## v0.102.2 (2026-04-28)


### 💄 UI/UX


- 💄 ui: enhance message count display in sidebar with icon and accessibility improvements
  ([`bfb4225`](https://github.com/thiesgerken/carapace/commit/bfb422501e720b125034ba7f0408732852d6e7b7))

  Co-authored-by: Copilot <copilot@github.com>

### 🐛 Bug Fixes


- 🐛 fix: add validation for skill path length in access denial check
  ([`815c39f`](https://github.com/thiesgerken/carapace/commit/815c39f50f6bc32dee4566dd49c5917feb13ba12))

## v0.102.1 (2026-04-27)


### Other


- Merge pull request #101 from thiesgerken/renovate/lock-file-maintenance
  ([`ce0a0d9`](https://github.com/thiesgerken/carapace/commit/ce0a0d956c0a67437ccdd23575fae321a48dec0d))

### ⬆️ Dependencies


- ⬆️ chore: Lock file maintenance
  ([`ce0a0d9`](https://github.com/thiesgerken/carapace/commit/ce0a0d956c0a67437ccdd23575fae321a48dec0d))

- ⬆️ chore: Lock file maintenance
  ([`2966b75`](https://github.com/thiesgerken/carapace/commit/2966b75fa7ace866b85c5e87fff19112a5cb7c40))

## v0.102.0 (2026-04-27)


### ✨ Features


- ✨Merge pull request #104 from thiesgerken/feature/thinkingbudget
  ([`ca347b6`](https://github.com/thiesgerken/carapace/commit/ca347b62c427b5abdb9d58fb46e8f11101544b16))

- ✨ feat: thinking budget tokens + enforce usage limits better + limit sentinel turns to 5
  ([`ca347b6`](https://github.com/thiesgerken/carapace/commit/ca347b62c427b5abdb9d58fb46e8f11101544b16))

- ✨ feat: thinking budget tokens + enforce usage limits better + limit sentinel turns to 5
  ([`52db42f`](https://github.com/thiesgerken/carapace/commit/52db42f7e9ae634684222960e48763d1f0345361))

### Other


- 5->10
  ([`be7a2dd`](https://github.com/thiesgerken/carapace/commit/be7a2dd2102ca9756108cc3b35a7ca52759287a8))

- add test for preserving explicit thinking false in model settings
  ([`8fd76e1`](https://github.com/thiesgerken/carapace/commit/8fd76e10f751e7befcad49edb6548a4a65a829ed))

- review comment
  ([`a1bc133`](https://github.com/thiesgerken/carapace/commit/a1bc133c9689a2a164468a5c6f48457e2eb32e84))

- add LLM request logging to title generation
  ([`e5be41a`](https://github.com/thiesgerken/carapace/commit/e5be41a8842bf3f571db305cb7cd1880df691b2e))

- Merge branch 'main' into feature/thinkingbudget
  ([`7d1e069`](https://github.com/thiesgerken/carapace/commit/7d1e069df775beab408db421b61dc938278cbe93))

## v0.101.1 (2026-04-27)


### 💄 UI/UX


- 💄 ui: hide "sentinel" label
  ([`0defda5`](https://github.com/thiesgerken/carapace/commit/0defda5d4297d8977aca3c5473d905b8f6322334))

### 🐛 Bug Fixes


- 🐛 fix: avoid calling npm at container startup
  ([`75e075b`](https://github.com/thiesgerken/carapace/commit/75e075b26b8c62c45dac929403b158fd14a8471d))

## v0.101.0 (2026-04-27)


### ✨ Features


- ✨ feat: add context count display to exec row
  ([`bd6e375`](https://github.com/thiesgerken/carapace/commit/bd6e375659226bee7be62b50fd7158a60151aece))

## v0.100.1 (2026-04-27)


### Other


- Merge pull request #103 from thiesgerken/renovate/ghcr.io-astral-sh-uv-python3.14-trixie-slim
  ([`7e1d9df`](https://github.com/thiesgerken/carapace/commit/7e1d9df332786cab76e2eb680faa0cb62ae44c74))

- Merge pull request #102 from thiesgerken/renovate/ghcr.io-astral-sh-uv
  ([`ae555ac`](https://github.com/thiesgerken/carapace/commit/ae555ac40dfa170c5ac13149b57e1365334f1386))

### ⬆️ Dependencies


- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to b3b7ad9
  ([`7e1d9df`](https://github.com/thiesgerken/carapace/commit/7e1d9df332786cab76e2eb680faa0cb62ae44c74))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv:python3.14-trixie-slim Docker digest to b3b7ad9
  ([`e977ba1`](https://github.com/thiesgerken/carapace/commit/e977ba174488974b731c585e803c90b18fc604d5))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 3b7b60a
  ([`ae555ac`](https://github.com/thiesgerken/carapace/commit/ae555ac40dfa170c5ac13149b57e1365334f1386))

- ⬆️ chore: upgrade ghcr.io/astral-sh/uv Docker digest to 3b7b60a
  ([`834f36c`](https://github.com/thiesgerken/carapace/commit/834f36c0e55fa40ccc7311ebbe849a3befaedb3e))

## v0.100.0 (2026-04-27)


### ✨ Features


- ✨Merge pull request #100 from thiesgerken/feat/skill-command-aliases
  ([`6e52a95`](https://github.com/thiesgerken/carapace/commit/6e52a9516d5018a186383ffdfcd10ff8539d3359))

- ✨ feat: Add skill command aliases for activated skills
  ([`6e52a95`](https://github.com/thiesgerken/carapace/commit/6e52a9516d5018a186383ffdfcd10ff8539d3359))

- ✨ feat: enhance documentation for skill command aliases and update example skill
  ([`30200aa`](https://github.com/thiesgerken/carapace/commit/30200aa5a2acfdb0b576604379abdd0c8697f26b))

- ✨ feat: add skill command aliases
  ([`5ac05cf`](https://github.com/thiesgerken/carapace/commit/5ac05cfbb2eaf358e3e8165a5d3a47d726b99a4f))

### 🐛 Bug Fixes


- 🐛 fix: remove unnecessary check for skill command shim directory in command alias resolution
  ([`69b2d8b`](https://github.com/thiesgerken/carapace/commit/69b2d8bfd19382a30011ae70818aa22ce0f1ebee))

  Co-authored-by: Copilot <copilot@github.com>

- 🐛 fix: address command alias review feedback
  ([`2e8c49a`](https://github.com/thiesgerken/carapace/commit/2e8c49a2b3a67973cca8fc093c07d6e889cf1564))

- 🐛 fix: update warning message for automatic skill context addition
  ([`0eea34d`](https://github.com/thiesgerken/carapace/commit/0eea34d75e13acbba32c603ebc6f332b4d121414))

- 🐛 fix: remove obsolete skill command registration note from roadmap
  ([`82c6a8d`](https://github.com/thiesgerken/carapace/commit/82c6a8de8b7036ac4e441d36da36319ebc348297))

### Other


- update command alias handling to expose wrapper directory on PATH and simplify command resolution
  ([`a4d322b`](https://github.com/thiesgerken/carapace/commit/a4d322ba2625a57fbccd0796cd7861266fd1e990))

  Co-authored-by: Copilot <copilot@github.com>

## v0.99.0 (2026-04-26)


### Other


- Merge pull request #99 from thiesgerken/renovate/pnpm-10.x
  ([`02e0419`](https://github.com/thiesgerken/carapace/commit/02e041964b95c35ebe0cff2d061a0dfa63e6c3b1))

- Merge branch 'main' into feat/twemoji
  ([`496f317`](https://github.com/thiesgerken/carapace/commit/496f31772a1b127f1ce2647f77078b2d51666d9d))

- Merge branch 'feat/session-knowledge-archive' into feat/twemoji
  ([`3c02a60`](https://github.com/thiesgerken/carapace/commit/3c02a604e93763cf5d87b846c7c6a160732cddf1))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 10.33.2
  ([`02e0419`](https://github.com/thiesgerken/carapace/commit/02e041964b95c35ebe0cff2d061a0dfa63e6c3b1))

- ⬆️ chore: upgrade pnpm to 10.33.2
  ([`b2f1de0`](https://github.com/thiesgerken/carapace/commit/b2f1de089d2f2e2c03406945171356fcce97497a))

### ✨ Features


- ✨Merge pull request #98 from thiesgerken/feat/twemoji
  ([`5494a5e`](https://github.com/thiesgerken/carapace/commit/5494a5ed6ecde7fc860447c3b577e5a70fc3c6b7))

- ✨ feat: use twemoji emojis and bundle them
  ([`5494a5e`](https://github.com/thiesgerken/carapace/commit/5494a5ed6ecde7fc860447c3b577e5a70fc3c6b7))

- ✨ feat: use twemoji emojis and bundle them
  ([`3652988`](https://github.com/thiesgerken/carapace/commit/365298847ea6de542ca15733fafd8fe8e276513f))

  Co-authored-by: Copilot <copilot@github.com>

### 🐛 Bug Fixes


- 🐛 fix: harden twemoji rendering flow
  ([`0980377`](https://github.com/thiesgerken/carapace/commit/09803777d18f28beeaadc2b1123f99ed7e8b4d4e))

## v0.98.0 (2026-04-26)


### ✨ Features


- ✨Merge pull request #97 from thiesgerken/feat/session-knowledge-archive
  ([`37d7d61`](https://github.com/thiesgerken/carapace/commit/37d7d61e79f11cebb7138fb9d9a8db0a3e109098))

- ✨ Add session knowledge saving as json
  ([`37d7d61`](https://github.com/thiesgerken/carapace/commit/37d7d61e79f11cebb7138fb9d9a8db0a3e109098))

- ✨ feat: add ripgrep to Dockerfile dependencies
  ([`749dd68`](https://github.com/thiesgerken/carapace/commit/749dd68da6b161e946cc819d08cbbc344298965c))

  Co-authored-by: Copilot <copilot@github.com>

- ✨ feat: update session archive commit message format to reflect add/update actions
  ([`8689e3c`](https://github.com/thiesgerken/carapace/commit/8689e3ce471b6c76a7c87cc367c996ce284a3471))

- ✨ feat: push knowledge commits to remote
  ([`aaec5ec`](https://github.com/thiesgerken/carapace/commit/aaec5ec6e7a8793fc1e8b2610e55c07229ac1114))

- ✨ feat: archive sessions to knowledge repo
  ([`86e49cb`](https://github.com/thiesgerken/carapace/commit/86e49cb0303ac5b13ef0085133296a019114c393))

### 🐛 Bug Fixes


- 🐛 fix: preserve active session state during privacy updates
  ([`fad5762`](https://github.com/thiesgerken/carapace/commit/fad5762462efb8190b565cb2e6e2547ec8bece4e))

- 🐛 fix: harden session state updates
  ([`a1e6284`](https://github.com/thiesgerken/carapace/commit/a1e6284e7560e3c4a6ca11be8b640ad637545ddc))

- 🐛 fix: address session archive review comments
  ([`558158b`](https://github.com/thiesgerken/carapace/commit/558158b1710b84d0c6398e39c635c51ec1e408a5))

- 🐛 fix: address archive review feedback
  ([`46910a6`](https://github.com/thiesgerken/carapace/commit/46910a692944ddd4083f59f6cfa71567cf21ae52))

- 🐛 fix: avoid firefox layout break on history load
  ([`67c437d`](https://github.com/thiesgerken/carapace/commit/67c437d431c534b66b6c0fce975a3fb2e766344a))

- 🐛 fix: address PR review comments
  ([`23006e6`](https://github.com/thiesgerken/carapace/commit/23006e6c7950c03774be048d4cb12b7fa79f2b2e))

- 🐛 fix: dedupe unchanged session autosaves
  ([`87bafe4`](https://github.com/thiesgerken/carapace/commit/87bafe4baaa97b3e78e1e8b93969061a04a4afad))

### ♻️ Refactoring


- ♻️ refactor: hide active session internals
  ([`5be55f6`](https://github.com/thiesgerken/carapace/commit/5be55f697d0207405ff4831b40f23518f1b48d5e))

- ♻️ refactor: fix chat view indentation
  ([`842efb5`](https://github.com/thiesgerken/carapace/commit/842efb54b3bfa915b6e08a5b2e4d286d7a24a012))

- ♻️ refactor: rename session archive settings to commit
  ([`94dde65`](https://github.com/thiesgerken/carapace/commit/94dde650f2fb199dfb6ce002eb53b017d034ae92))

### 💄 UI/UX


- 💄 ui: refine knowledge archive status badge
  ([`dfa499e`](https://github.com/thiesgerken/carapace/commit/dfa499ebc38ee8d4ed783e51fc217dec9a72ea2e))

- 💄 ui: compact session header controls
  ([`ec02201`](https://github.com/thiesgerken/carapace/commit/ec022016c82e69df29ae4b14b8237e4ea7b4bb44))

- 💄 ui: show knowledge save and private state
  ([`840e018`](https://github.com/thiesgerken/carapace/commit/840e0184c9448e3f512ada9c395f3dc878dd54bb))

### Other


- 📝 docs: explain archived session snapshots in prompt
  ([`d1099e6`](https://github.com/thiesgerken/carapace/commit/d1099e64f92198143f03b4ac5107268bbc669ef3))

- fix tests
  ([`5240f7b`](https://github.com/thiesgerken/carapace/commit/5240f7b810bbf327472a773cbeddbde3dd7fc54b))

- 📝 docs: document session archive settings
  ([`e3ad42d`](https://github.com/thiesgerken/carapace/commit/e3ad42d91be0527cd517e745b64634f49f232a72))

### 🩹 Patches


- 🩹 fix: constrain chat layout shell
  ([`9d072e1`](https://github.com/thiesgerken/carapace/commit/9d072e1e9e871cc3347a6fdf6d37508c9a4bf524))

## v0.97.1 (2026-04-25)


### Other


- Merge pull request #96 from thiesgerken/renovate/pnpm-10.x
  ([`ca49371`](https://github.com/thiesgerken/carapace/commit/ca49371389c52da0ec3f619c38a9ff0e953104ab))

### ⬆️ Dependencies


- ⬆️ chore: upgrade pnpm to 10.33.1
  ([`ca49371`](https://github.com/thiesgerken/carapace/commit/ca49371389c52da0ec3f619c38a9ff0e953104ab))

- ⬆️ chore: upgrade pnpm to 10.33.1
  ([`2915e20`](https://github.com/thiesgerken/carapace/commit/2915e20b4ad5f2682c3581c5b7dd651e577b5798))

## v0.97.0 (2026-04-25)


### ✨ Features


- ✨ feat: show session message counts in sidebar
  ([`e397a37`](https://github.com/thiesgerken/carapace/commit/e397a3710610186d85fdb74690588283b2aa648c))

## v0.96.1 (2026-04-25)


### 🐛 Bug Fixes


- 🐛 fix: refresh sandbox state after first tool call
  ([`eb1f175`](https://github.com/thiesgerken/carapace/commit/eb1f1752c67f084d9feddf86084304ed07312744))

## v0.96.0 (2026-04-25)


### ✨ Features


- ✨ feat: install node v24 in sandbox image
  ([`47cbc02`](https://github.com/thiesgerken/carapace/commit/47cbc02175e6298e5418ffd96fa01da1544d5d4b))

  Co-authored-by: Copilot <copilot@github.com>

### Other


- docs: add guidance for handling generated credential files in .gitignore
  ([`d940bdf`](https://github.com/thiesgerken/carapace/commit/d940bdf0b86ae175f0aa7ab66a83a092f7b918f2))

## v0.95.0 (2026-04-25)


### ✨ Features


- ✨ feat: support absolute https proxy requests
  ([`2773231`](https://github.com/thiesgerken/carapace/commit/2773231d7e78ca63e7da1fc06e418d859344c6a0))

### Other


- docs: update skill documentation for clarity and practical guidance
  ([`926329b`](https://github.com/thiesgerken/carapace/commit/926329b7b1b10c82f2303bf2b77ef6fe041a50c9))

  Co-authored-by: Copilot <copilot@github.com>

## v0.94.3 (2026-04-24)


### 🐛 Bug Fixes


- 🐛 fix: require explicit sandbox owner in k8s
  ([`5642e20`](https://github.com/thiesgerken/carapace/commit/5642e203e5293f3cef86b0a83408152223415d7e))

### Other


- docs: better bundled example skill
  ([`f845b70`](https://github.com/thiesgerken/carapace/commit/f845b701278dab52e8f99c30ac3ba372b5ab83e1))

## v0.94.2 (2026-04-24)


### 🐛 Bug Fixes


- 🐛 docs: tell agent to put less docs into SKILL.md
  ([`b76fa55`](https://github.com/thiesgerken/carapace/commit/b76fa55a2972ddb917fb8333bed2bf677b5d6ebc))

### Other


- remove depends from docker-compose
  ([`4c90f29`](https://github.com/thiesgerken/carapace/commit/4c90f2909da4cb95c5a05144cba5b882fe2128b2))

- refactor roadmap: reorganize sections and remove outdated items
  ([`3a7bfe0`](https://github.com/thiesgerken/carapace/commit/3a7bfe069a5a0728fdcd2dc496bc21859b99cc97))

## v0.94.1 (2026-04-24)


### ⬆️ Dependencies


- ⬆️Merge pull request #82 from thiesgerken/renovate/major-eslint-monorepo
  ([`9074725`](https://github.com/thiesgerken/carapace/commit/9074725a1df320c2a963785892c7bbbe292461cc))

- ⬆️ chore: upgrade eslint to 10.2.1
  ([`9074725`](https://github.com/thiesgerken/carapace/commit/9074725a1df320c2a963785892c7bbbe292461cc))

- ⬆️ chore: upgrade eslint to 10.2.1
  ([`d0f2cd9`](https://github.com/thiesgerken/carapace/commit/d0f2cd9ab194e9b589658bc2ae6e71549d364fcd))

### Other


- fix lint errors
  ([`b23086f`](https://github.com/thiesgerken/carapace/commit/b23086f495b822c9e7867a917390fe733f369f75))

## v0.94.0 (2026-04-24)


### ✨ Features


- ✨Merge pull request #95 from thiesgerken/feat/sandbox-power-controls
  ([`eff3442`](https://github.com/thiesgerken/carapace/commit/eff3442dc50ec92f8de2392cae78a253c670255a))

- ✨ feat: Add sandbox start and scale-down controls
  ([`eff3442`](https://github.com/thiesgerken/carapace/commit/eff3442dc50ec92f8de2392cae78a253c670255a))

- ✨ feat: add sandbox start and scale-down controls
  ([`0cac29f`](https://github.com/thiesgerken/carapace/commit/0cac29fa73ee4599b64697b6fb644c93fb9fc6cf))

### 🐛 Bug Fixes


- 🐛 fix: avoid false no-storage sandbox label
  ([`7686e53`](https://github.com/thiesgerken/carapace/commit/7686e533dcf2f7fed3c3d97706c566e8d3b8fc05))

### Other


- Merge remote-tracking branch 'origin/main' into feat/sandbox-power-controls
  ([`83c65aa`](https://github.com/thiesgerken/carapace/commit/83c65aaf0dbddac0e2f61004f01e6dbb1e467a8a))

- Merge branch 'main' into feat/sandbox-power-controls
  ([`b8712bf`](https://github.com/thiesgerken/carapace/commit/b8712bf37ebb250742b437362fc70fc703dda64d))

- fix: remove unnecessary storage presence message in sandboxStorageLabel
  ([`5b13f23`](https://github.com/thiesgerken/carapace/commit/5b13f236eea2ea2a9fc9a68363832bc7d2f990e1))

- fix alignment
  ([`01c6016`](https://github.com/thiesgerken/carapace/commit/01c601630d5fb5bcfb2d2939919c45ebd267a8a4))

- remove fallback label
  ([`b74e5b9`](https://github.com/thiesgerken/carapace/commit/b74e5b92c93d654da3f8d531de7650f75b617425))

## v0.93.2 (2026-04-24)


### ⬆️ Dependencies


- ⬆️Merge pull request #87 from thiesgerken/renovate/pin-dependencies
  ([`60acb83`](https://github.com/thiesgerken/carapace/commit/60acb833e5b3bfbd77c7315108dbc4d92105785f))

- ⬆️ chore: Pin dependencies
  ([`60acb83`](https://github.com/thiesgerken/carapace/commit/60acb833e5b3bfbd77c7315108dbc4d92105785f))

- ⬆️ chore: Pin dependencies
  ([`f1d8766`](https://github.com/thiesgerken/carapace/commit/f1d876611a72c819a0759311fe00241a11dcab64))

### Other


- chore: add package rules to disable digest pinning for Helm chart values
  ([`74a9d6a`](https://github.com/thiesgerken/carapace/commit/74a9d6ada7cfbeb67b54aa0ad3e21c2392168683))

  Co-authored-by: Copilot <copilot@github.com>

## v0.93.1 (2026-04-24)


### Other


- Merge pull request #93 from thiesgerken/renovate/debian-13.x
  ([`93c6bd5`](https://github.com/thiesgerken/carapace/commit/93c6bd5c150351176aa08199008e939604eb31e2))

- Merge pull request #92 from thiesgerken/renovate/astral-sh-setup-uv-8.x
  ([`6b82a6d`](https://github.com/thiesgerken/carapace/commit/6b82a6dfb5ef6f5ac2fe72da6ae1945a10c4a816))

### ⬆️ Dependencies


- ⬆️ chore: upgrade debian Docker tag to trixie-20260421
  ([`93c6bd5`](https://github.com/thiesgerken/carapace/commit/93c6bd5c150351176aa08199008e939604eb31e2))

- ⬆️ chore: upgrade debian Docker tag to trixie-20260421
  ([`f2064ef`](https://github.com/thiesgerken/carapace/commit/f2064eff706748a2ffcc83b5b8fc1ef9006cb6df))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v8.1.0
  ([`6b82a6d`](https://github.com/thiesgerken/carapace/commit/6b82a6dfb5ef6f5ac2fe72da6ae1945a10c4a816))

- ⬆️ chore: upgrade astral-sh/setup-uv action to v8.1.0
  ([`f3184ab`](https://github.com/thiesgerken/carapace/commit/f3184ab3561bb3aa8c1c23cf0f7dc65ee2247bee))

## v0.93.0 (2026-04-24)


### ✨ Features


- ✨ feat: show pending sandbox state during startup
  ([`ec39ed8`](https://github.com/thiesgerken/carapace/commit/ec39ed85da484bf0942182eb5c6795695100856c))

### ⚡ Performance


- ⚡ perf: cache sandbox snapshots and skip message counts by default
  ([`c488d96`](https://github.com/thiesgerken/carapace/commit/c488d96a115e0a8920cd913243aa7ccd86e0a2da))

## v0.92.0 (2026-04-24)


### ✨ Features


- ✨Merge pull request #94 from thiesgerken/feat/sandbox-status-and-wipe
  ([`36153d2`](https://github.com/thiesgerken/carapace/commit/36153d26efc25319c769cc2dd8d87f94c87a81b5))

- ✨ Add sandbox status and wipe controls
  ([`36153d2`](https://github.com/thiesgerken/carapace/commit/36153d26efc25319c769cc2dd8d87f94c87a81b5))

- ✨ feat: persist sandbox startup state
  ([`3062af8`](https://github.com/thiesgerken/carapace/commit/3062af8dca0c7397cc07f4d728880a5ab04f40e7))

- ✨ feat: add sandbox status and wipe controls
  ([`2cffd6f`](https://github.com/thiesgerken/carapace/commit/2cffd6fa28a6e782bcfdd8a62c097d9dd3b76e42))

### ♻️ Refactoring


- ♻️ refactor: remove unused _workspace_path method from SandboxManager
  ([`65e9737`](https://github.com/thiesgerken/carapace/commit/65e9737af65c1c34222997a2fce5daedfa5409e4))

- ♻️ refactor: simplify sandbox file ops
  ([`42d67dc`](https://github.com/thiesgerken/carapace/commit/42d67dc4bfb395d5ba2083aec6e9c045086cc76c))

- ♻️ refactor: delegate sandbox cleanup selection
  ([`729af84`](https://github.com/thiesgerken/carapace/commit/729af84b934ef215045da6aac65e4adf6dd873ee))

- ♻️ refactor: refresh sandbox once per turn
  ([`573b4f7`](https://github.com/thiesgerken/carapace/commit/573b4f7076c42a04f9cdebc9b7c73de9714fbad0))

- ♻️ refactor: keep sandbox runtime contract strict
  ([`cb1f11d`](https://github.com/thiesgerken/carapace/commit/cb1f11d98bb5e30f7349f14a628a277fead0818b))

### 🐛 Bug Fixes


- 🐛 fix: harden sandbox refresh follow-ups
  ([`e1b52de`](https://github.com/thiesgerken/carapace/commit/e1b52de249486fc52a318ed6f32839fac3da081f))

- 🐛 fix: avoid blocking on sandbox snapshot refresh
  ([`fe690e1`](https://github.com/thiesgerken/carapace/commit/fe690e118683ae8b33c7bae43cf3ae15e5fe13ae))

- 🐛 fix: fully clear sandbox storage on reset
  ([`216775a`](https://github.com/thiesgerken/carapace/commit/216775ae45a2f96aa9abc3e14118369735d6e395))

- 🐛 fix: polish sandbox status display
  ([`4411247`](https://github.com/thiesgerken/carapace/commit/4411247c12c224f2f1dfd42bc46d821bf140419f))

- 🐛 bugfixes
  ([`768ad9e`](https://github.com/thiesgerken/carapace/commit/768ad9e894376505d05c5f83d0737da7873b4de5))

- 🐛 fix: use df for sandbox volume usage
  ([`c608b95`](https://github.com/thiesgerken/carapace/commit/c608b951bea618255a9746b4f2eb8d58a7c51fac))

- 🐛 fix: stop sandbox live remeasurement
  ([`92d5c01`](https://github.com/thiesgerken/carapace/commit/92d5c01e46f5c83876dfb256ec5bfea028614852))

- 🐛 fix: restore sandbox test compatibility
  ([`d4ec04d`](https://github.com/thiesgerken/carapace/commit/d4ec04de5f9827d04046688ef74998a285d8c7ab))

- 🐛 fix: address sandbox PR review comments
  ([`acada52`](https://github.com/thiesgerken/carapace/commit/acada52023d8749f8e2679ccea8477058ec3847f))

## v0.91.0 (2026-04-23)


### ✨ Features


- ✨ feat: warn when exec references skill dirs without context
  ([`692c6be`](https://github.com/thiesgerken/carapace/commit/692c6be934a5f62605f78da710b500422c8bb34a))

## v0.90.4 (2026-04-22)


### 🐛 Bug Fixes


- 🐛 fix: ensure links in markdown open in a new tab
  ([`c753695`](https://github.com/thiesgerken/carapace/commit/c753695023eb316e9238d6b27972f22e6edf1500))

## v0.90.3 (2026-04-21)


### 🐛 Bug Fixes


- 🐛 fix thinking timing for tool call only responses
  ([`1ff4cd0`](https://github.com/thiesgerken/carapace/commit/1ff4cd0679887c1161a8daaee105e4cfd8beb327))

## v0.90.2 (2026-04-21)


### 🐛 Bug Fixes


- 🐛 fix: lazily restore sandbox session tokens
  ([`dd2a209`](https://github.com/thiesgerken/carapace/commit/dd2a209b57be5f107a1b8810d591ebc025419153))

## v0.90.1 (2026-04-21)


### 🐛 Bug Fixes


- 🐛 fix: regressions that were introduced during the thinking refactor
  ([`b8d1163`](https://github.com/thiesgerken/carapace/commit/b8d11630084b0528025f8a66d2d43ce4cb70017a))

## v0.90.0 (2026-04-21)


### ✨ Features


- ✨Merge pull request #91 from thiesgerken/feat/persist-llm-activity-timing
  ([`cf82cf0`](https://github.com/thiesgerken/carapace/commit/cf82cf0a5661fb83ff03559000fdb12759c73c35))

- ✨ feat: Track persisted LLM activity timing
  ([`cf82cf0`](https://github.com/thiesgerken/carapace/commit/cf82cf0a5661fb83ff03559000fdb12759c73c35))

- ✨ feat: track persisted LLM activity
  ([`6a35e68`](https://github.com/thiesgerken/carapace/commit/6a35e68adb541a5b5de1afaf5c57dbd7c15ba5e1))

### 💄 UI/UX


- 💄 style: label thinking phase
  ([`69667eb`](https://github.com/thiesgerken/carapace/commit/69667eb852f6c2d9222a1c7cadffeff2ca274d70))

### 🐛 Bug Fixes


- 🐛 fix: restore waiting fallback
  ([`77cfa3c`](https://github.com/thiesgerken/carapace/commit/77cfa3c860dde7d6fc11eaf8fb25167edf1a8072))

- 🐛 fix: satisfy React purity lint
  ([`537859a`](https://github.com/thiesgerken/carapace/commit/537859a1421eeca8465957a2fb06f1c2aa9e06a9))

### Other


- cleanup roadmap
  ([`226fc73`](https://github.com/thiesgerken/carapace/commit/226fc7393094481f904edbf569802f92b5700bfb))

## v0.89.0 (2026-04-20)


### ✨ Features


- ✨ Improve tool-call feedback during sentinel review
  ([`c46346d`](https://github.com/thiesgerken/carapace/commit/c46346df841ea0f0b70201e613fc7ff5f68710cb))

### 🐛 Bug Fixes


- 🐛 fix: stream tool activity before sentinel decisions
  ([`c46346d`](https://github.com/thiesgerken/carapace/commit/c46346df841ea0f0b70201e613fc7ff5f68710cb))

- 🐛 fix: address tool feedback review comments
  ([`c46346d`](https://github.com/thiesgerken/carapace/commit/c46346df841ea0f0b70201e613fc7ff5f68710cb))

- 🐛 fix: stabilize tool and thinking feedback
  ([`c46346d`](https://github.com/thiesgerken/carapace/commit/c46346df841ea0f0b70201e613fc7ff5f68710cb))

## v0.88.9 (2026-04-20)


### ⬆️ Dependencies


- ⬆️ chore: Lock file maintenance
  ([`8dbd1ab`](https://github.com/thiesgerken/carapace/commit/8dbd1ab3567e1efb10d32e0c50a646e40971482c))

- ⬆️ chore: Lock file maintenance
  ([`8dbd1ab`](https://github.com/thiesgerken/carapace/commit/8dbd1ab3567e1efb10d32e0c50a646e40971482c))

### 🐛 Bug Fixes


- 🐛 make linter happy
  ([`8dbd1ab`](https://github.com/thiesgerken/carapace/commit/8dbd1ab3567e1efb10d32e0c50a646e40971482c))

  ---------

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

  Co-authored-by: Thies Gerken <thies.gerken@lector.ai>

## v0.88.8 (2026-04-19)


### 🐛 Bug Fixes


- 🐛 fix: trace sentinel tool calls
  ([`05a4640`](https://github.com/thiesgerken/carapace/commit/05a464031e22cd3a5f1032bd4e3446cef8d8160a))

## v0.88.7 (2026-04-19)


### 🐛 Bug Fixes


- 🐛 force a tool output for sentinel
  ([`d39a3f7`](https://github.com/thiesgerken/carapace/commit/d39a3f780d16a55262abcc96182d270118f79ec1))

## v0.88.6 (2026-04-19)


### 🐛 Bug Fixes


- 🐛 fix: improve agent loop diagnostics
  ([`011c404`](https://github.com/thiesgerken/carapace/commit/011c404ae7d77913fff9467516363ad5f714ee71))

## v0.88.5 (2026-04-19)


### ⬆️ Dependencies


- ⬆️ chore: relock
  ([`7e8e806`](https://github.com/thiesgerken/carapace/commit/7e8e806f555c44d5761284833fc6d5b0499f38a9))

## v0.88.4 (2026-04-19)


### 🐛 Bug Fixes


- 🐛 prevent sentinel from going into an endless loop reading the same files over and over again
  ([`b0b9146`](https://github.com/thiesgerken/carapace/commit/b0b9146e3517ec4d035b16a8f570e9ae6f950339))

## v0.88.3 (2026-04-19)


### ⬆️ Dependencies


- ⬆️ chore: Allow zero version in semantic release configuration
  ([`f1f56f8`](https://github.com/thiesgerken/carapace/commit/f1f56f82b46f84b6314f1a4b2049c07d8d607c1b))

- ⬆️ chore: Lock file maintenance
  ([`5ef05b6`](https://github.com/thiesgerken/carapace/commit/5ef05b694304771a29c7376fa1b3f242ef802368))

- ⬆️ chore: Lock file maintenance
  ([`5ef05b6`](https://github.com/thiesgerken/carapace/commit/5ef05b694304771a29c7376fa1b3f242ef802368))

- ⬆️ chore: upgrade azure/setup-helm action to v5
  ([`7d20f92`](https://github.com/thiesgerken/carapace/commit/7d20f927ea9fb50d32f2fd450065384636d96e94))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- ⬆️ chore: upgrade alpine Docker tag to v3.23
  ([`3c47814`](https://github.com/thiesgerken/carapace/commit/3c47814b4f27f45e9536407f953693d6bfab424b))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- ⬆️ chore: upgrade python-semantic-release/python-semantic-release action to v10
  ([`aa713af`](https://github.com/thiesgerken/carapace/commit/aa713af043be9518aad4dfd479b281a3b9005de3))

### Other


- restore correct version
  ([`05aeec9`](https://github.com/thiesgerken/carapace/commit/05aeec9cede5e41dea34e97bafae544914bb496f))

- Update ghcr.io/astral-sh/uv Docker digest to 240fb85
  ([`78b2af3`](https://github.com/thiesgerken/carapace/commit/78b2af3cf3162276c0f00cdab9ca23114e3d7a99))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- Update dependency node to v24
  ([`88726b5`](https://github.com/thiesgerken/carapace/commit/88726b56befc219191dfb14abc7985d6c5e5538f))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- Update pnpm to v10.33.0
  ([`022657a`](https://github.com/thiesgerken/carapace/commit/022657a2e82dfc8481eb9977aee3f8a325feabf9))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- Update debian Docker tag to trixie-20260406
  ([`357c501`](https://github.com/thiesgerken/carapace/commit/357c5019c47ba72d3e4bacc2676262b3f8402398))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- Update dependency diff to v9
  ([`17c6487`](https://github.com/thiesgerken/carapace/commit/17c648702c5ea90c82b0204e5b1f352df4674c80))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- Update dependency rich to v15
  ([`a3fc394`](https://github.com/thiesgerken/carapace/commit/a3fc39448919c06b6a7f057624619e0b170d6457))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- Update pnpm/action-setup action to v6
  ([`6ae46a6`](https://github.com/thiesgerken/carapace/commit/6ae46a6abf5ed20540f36f86fb54c6e532ba6e90))

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

- Merge pull request #86 from thiesgerken/renovate/python-semantic-release-python-semantic-release-10.x
  ([`aa713af`](https://github.com/thiesgerken/carapace/commit/aa713af043be9518aad4dfd479b281a3b9005de3))

- Update python-semantic-release/python-semantic-release action to v10
  ([`15b3bd4`](https://github.com/thiesgerken/carapace/commit/15b3bd480744dc3e29d3be59d4ce6fd42f84ae54))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`574912e`](https://github.com/thiesgerken/carapace/commit/574912e297602836878113b0397fe54fd2dcabf7))

### 🐛 Bug Fixes


- 🐛 make linter happy
  ([`5ef05b6`](https://github.com/thiesgerken/carapace/commit/5ef05b694304771a29c7376fa1b3f242ef802368))

  ---------

  Co-authored-by: renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>

  Co-authored-by: Thies Gerken <thies.gerken@lector.ai>

## v0.88.2 (2026-04-19)


### Other


- chore: update renovate configuration to extend best practices and enable lock file maintenance
  ([`b203daf`](https://github.com/thiesgerken/carapace/commit/b203daf3940bfbe5fe4cb58f059891772a10ed21))

- chore: update renovate configuration to set PR limits
  ([`ffdd4d3`](https://github.com/thiesgerken/carapace/commit/ffdd4d315280c9e4711547d7189ae38011454a44))

- Merge pull request #69 from thiesgerken/renovate/configure
  ([`75c5432`](https://github.com/thiesgerken/carapace/commit/75c5432bd80980851148744d8c4aaf1c2b34bc98))

  Configure Renovate

- Add renovate.json
  ([`9b64da6`](https://github.com/thiesgerken/carapace/commit/9b64da6d8be935dc2d8fb20845e6df47b2f3ab2e))

### ⬆️ Dependencies


- ⬆️ chore: configure renovate gitmoji commits
  ([`6c9dfdd`](https://github.com/thiesgerken/carapace/commit/6c9dfddb3f817dbb7ea5550807eb696d4e3505f8))

## v0.88.1 (2026-04-19)


### 🐛 Bug Fixes


- 🐛 fix tunneling wait cmd
  ([`450ae2e`](https://github.com/thiesgerken/carapace/commit/450ae2ee8c8bd260abd9b8b030ac0f74e6175722))

## v0.88.0 (2026-04-19)


### ✨ Features


- ✨Merge pull request #68 from thiesgerken/feat/exec-scoped-network-tunnels
  ([`6ffbcd4`](https://github.com/thiesgerken/carapace/commit/6ffbcd46e000a2fcc295c3640050c2d00b9201a3))

- ✨Add exec-scoped network tunnels for skill contexts
  ([`6ffbcd4`](https://github.com/thiesgerken/carapace/commit/6ffbcd46e000a2fcc295c3640050c2d00b9201a3))

- ✨ feat: add exec-scoped network tunnels
  ([`05655ce`](https://github.com/thiesgerken/carapace/commit/05655ce56a827c0bde93b0b81eb8cc424b267b1d))

### 🐛 Bug Fixes


- 🐛 fix: address remaining tunnel review issues
  ([`a76ebc5`](https://github.com/thiesgerken/carapace/commit/a76ebc510be6d2b688158cd4cb12233a05760127))

- 🐛 fix: harden tunnel startup and cancelled turn persistence
  ([`766951a`](https://github.com/thiesgerken/carapace/commit/766951aee9ac57cc0d1c6417e263eafce441eb08))

- 🐛 fix: preserve tunnel helper escapes
  ([`3f9f622`](https://github.com/thiesgerken/carapace/commit/3f9f622ab97aa6df732883ef06b127c3081ec00a))

- 🐛 fix: stabilize tunnel startup pid handling
  ([`8002c59`](https://github.com/thiesgerken/carapace/commit/8002c59ec4ee599bb560cdd295a9efd4b74b4a1c))

- 🐛 fix: address tunnel review issues
  ([`507fda4`](https://github.com/thiesgerken/carapace/commit/507fda4afdab4fe2aef2da4ffd12c3749b25c1dd))

## v0.87.0 (2026-04-18)


### ✨ Features


- ✨Merge pull request #67 from thiesgerken/feat/skill-activation-providers
  ([`d459314`](https://github.com/thiesgerken/carapace/commit/d459314ffb7a0fd47e8972c53f574bd54925bb73))

- ✨ feat: add provider-based skill activation
  ([`d459314`](https://github.com/thiesgerken/carapace/commit/d459314ffb7a0fd47e8972c53f574bd54925bb73))

- ✨ feat: add provider-based skill activation
  ([`0441d7b`](https://github.com/thiesgerken/carapace/commit/0441d7ba91591e653c0bda37f104a51ec3dbe367))

### Other


- 📝 docs: clarify setup.sh proxy bypass
  ([`2ed8453`](https://github.com/thiesgerken/carapace/commit/2ed8453bb9ae1d468e344d69e09110c934da9150))

- 🔥 remove dead code
  ([`63f8907`](https://github.com/thiesgerken/carapace/commit/63f89072b450e2e351310082b2ee8b70f0c2b7d4))

- Revert "🐛 fix: keep usage shape estimation offline"
  ([`54f77aa`](https://github.com/thiesgerken/carapace/commit/54f77aa2628ef0f96ec51dcce6c5b15c2333e3e1))

  This reverts commit 88d39316ce14d940ac6c9023b9c9112b15c7c1ca.

- 📝 docs: extend example skill providers
  ([`5991089`](https://github.com/thiesgerken/carapace/commit/5991089c4b31538ce0fc155bb47b9a1f69cff1cf))

- 📝 docs: document skill activation providers
  ([`bba1f5d`](https://github.com/thiesgerken/carapace/commit/bba1f5da129893690f0566a10d8eb4e0beecf115))

### ♻️ Refactoring


- ♻️ refactor: clean legacy skill setup paths
  ([`b477e01`](https://github.com/thiesgerken/carapace/commit/b477e013d8cac0b46ab9387c5817fd468f1cb4ed))

- ♻️ refactor: simplify node skill activation selection
  ([`96afdc5`](https://github.com/thiesgerken/carapace/commit/96afdc539d77b82483b489c5a16c333981806c60))

- ♻️ refactor: update asyncio usage in SandboxManager
  ([`cf5d55a`](https://github.com/thiesgerken/carapace/commit/cf5d55abfbacbbd0c6cd6a659057625a45eafb7f))

- ♻️ refactor: simplify activation providers
  ([`e5b6066`](https://github.com/thiesgerken/carapace/commit/e5b6066c1435fdf0adfa2aa0f4da0febd553b646))

- ♻️ refactor: split sandbox manager internals
  ([`20f13e5`](https://github.com/thiesgerken/carapace/commit/20f13e5e3b9ecccd62c35a5f6c2a1d867e046780))

### 🐛 Bug Fixes


- 🐛 fix: harden skill activation restore
  ([`aa54ce8`](https://github.com/thiesgerken/carapace/commit/aa54ce89c7972c482b292d7d9b5213824ea863dc))

- 🐛 fix: keep usage shape estimation offline
  ([`88d3931`](https://github.com/thiesgerken/carapace/commit/88d39316ce14d940ac6c9023b9c9112b15c7c1ca))

## v0.86.0 (2026-04-18)


### ✨ Features


- ✨Merge pull request #66 from thiesgerken/feat/session-budgets
  ([`a87a26e`](https://github.com/thiesgerken/carapace/commit/a87a26e1e98d7ff7ecf41bb579d53ca20b611a3a))

- ✨ feat: Add session budgets and budget gauges
  ([`a87a26e`](https://github.com/thiesgerken/carapace/commit/a87a26e1e98d7ff7ecf41bb579d53ca20b611a3a))

- ✨ feat: add session budgets and gauges
  ([`33d059f`](https://github.com/thiesgerken/carapace/commit/33d059f1067f72c908266611316f1633f1c31426))

### 🐛 Bug Fixes


- 🐛 fix: address budget review comments
  ([`6063faf`](https://github.com/thiesgerken/carapace/commit/6063fafc9dbbee24acfa7427050aa183c914db38))

- 🐛 fix: refresh usage after title generation
  ([`87c514e`](https://github.com/thiesgerken/carapace/commit/87c514ec8b33072be201288aa0ee8690787d344e))

- 🐛 fix: use cost_usd for session budgets
  ([`6386a64`](https://github.com/thiesgerken/carapace/commit/6386a646582ee72c7b90038de777d8527cc7177b))

### Other


- remove item from roadmap
  ([`de6011b`](https://github.com/thiesgerken/carapace/commit/de6011bd2ddc8dcf75a67bc3dc4c92a3ba9c1a3a))

- ✅ test: configure matrix budget mock
  ([`16baedc`](https://github.com/thiesgerken/carapace/commit/16baedc91422d9f35b0b2e751508d7fd82ac507f))

## v0.85.0 (2026-04-17)


### ✨ Features


- ✨Merge pull request #65 from thiesgerken/feat/approval-denial-messages
  ([`3800e31`](https://github.com/thiesgerken/carapace/commit/3800e31c7adbcb71c8401f5d01f82406313b9405))

- ✨ Add denial messages to approval flows
  ([`3800e31`](https://github.com/thiesgerken/carapace/commit/3800e31c7adbcb71c8401f5d01f82406313b9405))

- ✨ improve system prompt for testing
  ([`d047028`](https://github.com/thiesgerken/carapace/commit/d04702840f3a7019420f98bda162f5d54230acb1))

- ✨ feat: add approval denial messages
  ([`b509cf8`](https://github.com/thiesgerken/carapace/commit/b509cf8fd0496ec2d57097b66325a16941199e08))

### 🐛 Bug Fixes


- 🐛 fix: preserve credential denial attribution
  ([`1609be2`](https://github.com/thiesgerken/carapace/commit/1609be26c4544b51dfd53c4beb8422d66a1a55ba))

### Other


- 🧹 chore: remove unused approval message field
  ([`20ca63e`](https://github.com/thiesgerken/carapace/commit/20ca63ef35cea68310d7f4d7602fc6c7166f9ab4))

### ♻️ Refactoring


- ♻️ refactor: unify approval note handling
  ([`b290672`](https://github.com/thiesgerken/carapace/commit/b290672cfb030625082b99a0efb918e6e561843d))

### 💄 UI/UX


- 💄 polish: refine denial approval UI
  ([`4487d72`](https://github.com/thiesgerken/carapace/commit/4487d7239303471f939789604fafd06762fc6903))

### 🩹 Patches


- 🩹 fix: restore pytest suite
  ([`b75cd93`](https://github.com/thiesgerken/carapace/commit/b75cd9386c594415a0deb01204630019bda2d4c9))

## v0.84.3 (2026-04-16)


### ⬆️ Dependencies


- ⬆️ chore: relock backend
  ([`839d3a7`](https://github.com/thiesgerken/carapace/commit/839d3a772ca0903914fa8bbe78622326a9cda167))

## v0.84.2 (2026-04-15)


### 🐛 Bug Fixes


- 🐛 fix: re-fetch skill credentials from vault on cache miss
  ([`78079f9`](https://github.com/thiesgerken/carapace/commit/78079f959a368a5dd29c8a9308f3194547d360c6))

  After a backend restart the in-memory credential cache is empty, causing exec with skill contexts to skip credential injection. Instead of warning and giving up, re-fetch from the vault and repopulate the cache on the spot.

### Other


- 📝 docs: update carapace.yaml section in SKILL.md for clarity and optionality
  ([`a137257`](https://github.com/thiesgerken/carapace/commit/a1372570eb522f6a7b228533e296f0043e412af7))

## v0.84.1 (2026-04-14)


### 🐛 Bug Fixes


- 🐛 fix: add missing tool_id/parent_tool_id to frontend HistoryMessage type
  ([`ae617dd`](https://github.com/thiesgerken/carapace/commit/ae617dd6a4c5479fb39b23f2c5f722fc733f815c))

## v0.84.0 (2026-04-14)


### ✨ Features


- ✨ feat: nest auxiliary tool calls under parent tool in UI
  ([`ecb9048`](https://github.com/thiesgerken/carapace/commit/ecb9048a0e1bcf66192fd4f97a060b9233f53b06))

  - Add tool_id/parent_tool_id to ToolCallInfo and HistoryMessage
  - Track current_parent_tool_id in SessionSecurity context
  - Generate UUIDs per tool call, thread parent ID to credential/domain/push callbacks
  - Frontend groups child events under parent in both history and real-time
  - Render nested auxiliary badges (credential_access, proxy_domain, git_push) inside parent
  - Add max-height constraint to exec terminal output block
  - Update ROADMAP (credential access entry completed)

## v0.83.0 (2026-04-13)


### Other


- more small improvements to tool call badge
  ([`b62f1ed`](https://github.com/thiesgerken/carapace/commit/b62f1ed8e88bf4b5f4f1460924e8867ef8c47629))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`138a9f5`](https://github.com/thiesgerken/carapace/commit/138a9f5d1b83d7beccd523cf8ad569cbeba936dc))

### ✨ Features


- ✨ feat: improve skill activation display
  ([`731ca74`](https://github.com/thiesgerken/carapace/commit/731ca746635a32015a96319acf370fc750c9f977))

- ✨ feat: support yaml secret files
  ([`cfed72c`](https://github.com/thiesgerken/carapace/commit/cfed72cd429d9f7d1dcc8935529a904a2e854bfd))

- ✨ feat: show credential names in UI
  ([`b9d6191`](https://github.com/thiesgerken/carapace/commit/b9d619151b39ca865fe6cc2532ea3bebd3cd358d))

## v0.82.1 (2026-04-12)


### Other


- todo
  ([`ace8b98`](https://github.com/thiesgerken/carapace/commit/ace8b9803f963ffea472a70b96f5af4b58ddbe35))

### 🐛 Bug Fixes


- 🐛 fix: proxy auth for git clone in sandbox
  ([`a066115`](https://github.com/thiesgerken/carapace/commit/a0661159eb151967980e23589734d581124fc8ac))

  - Return 407 with Proxy-Authenticate header when no credentials are
    provided, so curl/git retries with embedded proxy credentials
  - Replace invalid https.proxy git config with http.proxyAuthMethod=basic
    to send Proxy-Authorization immediately without anyauth negotiation

## v0.82.0 (2026-04-12)


### ✨ Features


- ✨ feat: base64 decoding for skill credential injection
  ([`ad492e9`](https://github.com/thiesgerken/carapace/commit/ad492e9c2e688a42cbac9af0f329246e100fa66b))

  - Add `base64` field to SkillCredentialDecl (default: false)
  - Decode base64-encoded vault values before env_var and file injection
  - Pass decoded value directly in context_file_creds tuple instead of
    re-fetching from cache, ensuring single decode per exec
  - Document field in model, docs/skills.md, docs/credentials.md,
    and create-skill SKILL.md
  - Add tests for base64 flag serialization roundtrip

## v0.81.0 (2026-04-12)


### ✨ Features


- ✨ add kubectl to sandbox image, use trixie image directly
  ([`391172b`](https://github.com/thiesgerken/carapace/commit/391172b99ec2e8b08451578b1ae2308754edfb60))

## v0.80.0 (2026-04-12)


### ✨ Features


- ✨ feat: stream LLM thinking/reasoning content to web UI
  ([`3418e12`](https://github.com/thiesgerken/carapace/commit/3418e125561cfa6af3a9e953537f22f3c55a6b13))

  - Add ThinkingChunk WS message type and Done.thinking field
  - Capture ThinkingPart/ThinkingPartDelta events in agent loop
  - Broadcast thinking tokens via SessionSubscriber protocol
  - Persist thinking as separate history event per turn
  - Render thinking as collapsible badge in frontend (auto-collapse on finish)
  - Make thinking capability configurable per model (default: enabled)
  - No-op for Matrix/CLI channels

## v0.79.1 (2026-04-12)


### ⚡ Performance


- ⚡ perf: use granular HTTP timeouts for LLM requests
  ([`c4a41f4`](https://github.com/thiesgerken/carapace/commit/c4a41f40f531a2830e72074439b3581e2e4b9bff))

  Set connect=15s, read=300s, write=15s, pool=60s instead of a blanket 60s timeout. This avoids premature read timeouts on slow reasoning models while detecting dead hosts faster.

## v0.79.0 (2026-04-12)


### ✨ Features


- ✨ feat: clarify skill credential/domain grants in sentinel prompt
  ([`7273a8e`](https://github.com/thiesgerken/carapace/commit/7273a8e9648c7756dc1665e27630ce4f3d2e9693))

  - Add paragraph to sentinel system prompt explaining that use_skill
    declared_domains and declared_creds come from the skill's carapace.yaml
    manifest, not from the agent itself
  - Rename requested_creds/requested_domains → declared_creds/declared_domains
    in use_skill gate args for clearer sentinel presentation

### 🐛 Bug Fixes


- 🐛 fix: clear loading spinner for credential_access tool calls
  ([`f309326`](https://github.com/thiesgerken/carapace/commit/f30932655a54060ea32bdff17c01a5e320592d5a))

## v0.78.0 (2026-04-12)


### 🐛 Bug Fixes


- 🐛 Include weekday in agent session date.
  ([`442f448`](https://github.com/thiesgerken/carapace/commit/442f448f5b8f70fa1c9e2e50e48e8a75783bcf33))

  Session Info now shows the locale weekday with the ISO calendar date. Tests assert the formatted date string appears in the built prompt.

  Made-with: Cursor

### ✨ Features


- ✨ feat: configurable limit for tool outputs
  ([`898942c`](https://github.com/thiesgerken/carapace/commit/898942c66d4dbbf1f0479cde17864abe5187f8bf))

  Add agent.tool_output_max_chars (default 16_000; 0 disables). Truncate before returning to the model and mirroring to tool_result_callback.

  Made-with: Cursor

- ✨ Include today's date in the agent system prompt.
  ([`e0c3f54`](https://github.com/thiesgerken/carapace/commit/e0c3f5434c5b6d921f446adf13c269d5200e18e4))

  Session Info now lists the server-local calendar date (ISO YYYY-MM-DD) so the model can reason about recency without a time component. Tests assert the current date appears in the built prompt.

  Made-with: Cursor

## v0.77.0 (2026-04-12)


### ✨ Features


- ✨ feat: bundle web and wikipedia skills as built-in assets
  ([`fd49b5a`](https://github.com/thiesgerken/carapace/commit/fd49b5af1f8d74f82c6a12023a3b101e48c1c489))

### Other


- 📝 docs: clarify context parameter usage in create_agent function
  ([`df1e0b2`](https://github.com/thiesgerken/carapace/commit/df1e0b2f01fcf85bda007243ab042bf0b215a251))

## v0.76.1 (2026-04-12)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`4a8441f`](https://github.com/thiesgerken/carapace/commit/4a8441f28acce8084a4ede693c48d4c409a273c0))

## v0.76.0 (2026-04-12)


### 🐛 Bug Fixes


- 🐛 fix: mock mark_credential_notified in sandbox credentials audit test
  ([`425b342`](https://github.com/thiesgerken/carapace/commit/425b342195da7b7b97bb5e2fbf49c7b17ab547d9))

  The MagicMock default (truthy) caused the credential notify suppress callback to skip logging, making the test always fail.

- 🐛 fix: serialize sentinel evaluations and gate title generation behind LLM semaphore
  ([`1d9a2e6`](https://github.com/thiesgerken/carapace/commit/1d9a2e61f248704718811be3680f8188b2998aae))

  Add asyncio.Lock to Sentinel so concurrent tool calls are evaluated one at a time, preventing LLM flooding and _message_history races.

  Gate _generate_title behind _llm_semaphore so fire-and-forget title generation doesn't overlap with agent turns.

### ✨ Features


- ✨ feat: update bundled skills to package layout with entrypoints
  ([`7c01eb3`](https://github.com/thiesgerken/carapace/commit/7c01eb3c7ca537aa75c46661490f3484041a5f6f))

  - create-skill: add carapace.yaml schema docs, teach src-layout with
    [project.scripts] entrypoints instead of scripts/ flat files
  - example: convert from scripts/hello.py to src/example_skill/ package
    with CLI entrypoint, update pyproject.toml with build config

### Other


- scale to 0 again
  ([`9dd16ac`](https://github.com/thiesgerken/carapace/commit/9dd16ac2ec3e64f69fb9686542bc8817ec96ae60))

- 📋 docs: plan image handling
  ([`1e0b777`](https://github.com/thiesgerken/carapace/commit/1e0b7772837402966cabc9d9e99528d7019ba524))

- 📋 docs: dev docker compose changes
  ([`27236e5`](https://github.com/thiesgerken/carapace/commit/27236e53f5e7546e12f99e8dfc975be72f183582))

## v0.75.2 (2026-04-11)


### 🐛 Bug Fixes


- 🐛 fix: copy assets using shutil to make binaries work as well
  ([`51dcb4a`](https://github.com/thiesgerken/carapace/commit/51dcb4a13c259b86b4c77bdc1f0aef4cf973443c))

## v0.75.1 (2026-04-11)


### Other


- chore: update package versions in uv.lock
  ([`6e4fc37`](https://github.com/thiesgerken/carapace/commit/6e4fc37a729173a6b9a7eba91782669afee46468))

  - Updated anthropic from 0.88.0 to 0.94.0
  - Updated boto3 from 1.42.82 to 1.42.88
  - Updated botocore from 1.42.82 to 1.42.88
  - Updated click from 8.3.1 to 8.3.2
  - Updated cohere from 5.21.1 to 6.1.0
  - Updated cryptography from 46.0.6 to 46.0.7

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`babb304`](https://github.com/thiesgerken/carapace/commit/babb3045b27e298cf359c81dbe48e092b0ef0fc7))

## v0.75.0 (2026-04-11)


### 🐛 Bug Fixes


- 🐛 fix: tool_call_callback invocation
  ([`9d94aa6`](https://github.com/thiesgerken/carapace/commit/9d94aa6b4a533ed001358974a1b5b36a438547a2))

- 🐛 fix: keep skill credential cache on sandbox create rollback
  ([`8ab4fc6`](https://github.com/thiesgerken/carapace/commit/8ab4fc6b70ea86fd1ba444527a7172320f1c3b8c))

  _cleanup_tracking must not drop _credential_cache: values come from use_skill and survive transient ensure_session failures. destroy_session still purges the cache.

  Made-with: Cursor

- 🐛 fix: clean up session data on sandbox manager teardown
  ([`eb46b33`](https://github.com/thiesgerken/carapace/commit/eb46b334f7641c42faa2fa33be0f08fa6c43812e))

  Removed credential cache and current contexts from session cleanup to ensure proper resource management.

- 🐛 fix: hide credential approval card for auto-approved credentials in history
  ([`09c8fca`](https://github.com/thiesgerken/carapace/commit/09c8fca5621ebc24ef442ae233d27aeb61fa71d6))

- 🐛 fix: notify credential injection at exec time, not use_skill
  ([`5f1dbda`](https://github.com/thiesgerken/carapace/commit/5f1dbdae9904d99b666acf76b69b125329198812))

  Credential UI entries (with "skill" badge) now appear when credentials are actually injected into an exec via contexts, rather than when they are cached during use_skill. The sentinel action-log entries from use_skill are preserved so the security agent stays aware of skill-declared credentials.

### Other


- add ruff to dev deps
  ([`756c5be`](https://github.com/thiesgerken/carapace/commit/756c5bec86a74e0114730630c3304bc03a2b78f8))

- fix: align credential dedupe with action log and audit
  ([`c9bfea1`](https://github.com/thiesgerken/carapace/commit/c9bfea1cc337e719744e28865cfbac87986cc159))

  Apply per-exec mark_credential_notified via SessionSecurity before record_credential_access writes the action log or audit file, and before notify_credential_decision emits UI. Remove duplicate check from the engine credential callback so the vault path is consumed once per notification.

  Made-with: Cursor

- fix: dedupe skill credential UI notify with sandbox API access
  ([`45d8e81`](https://github.com/thiesgerken/carapace/commit/45d8e818ae630715adb582ee6e91f0fb6b361d13))

  Run context-scoped credential injection notifications inside _exec via after_exec_credential_notify, before _exec_notified_credentials is cleared, so mark_credential_notified still suppresses duplicates when ccred ran during the same exec. Add regression tests.

  Made-with: Cursor

- fix(web): pair escalation requests with decisions across interleaved history
  ([`18bcc22`](https://github.com/thiesgerken/carapace/commit/18bcc22d4f3198dacbe9d7a5f8a68729a3145b33))

  Scan forward by request_id instead of only history[i+1] so resolved domain/git/credential approvals do not render as pending or allow duplicate escalation responses when other events appear between request and decision.

  Made-with: Cursor

- fix(agent): bullet-prefix every line of use_skill status output
  ([`17e2565`](https://github.com/thiesgerken/carapace/commit/17e25658876fece7ce0ed4ba133d779377094b26))

  Multi-line cred_msg from _cache_skill_credentials was a single status_lines entry, so only the first line received the "- " prefix. Split sandbox_msg and cred_msg with splitlines() so each line is its own bullet.

  Made-with: Cursor

- refactor: share context_grants /session payload builder
  ([`467b625`](https://github.com/thiesgerken/carapace/commit/467b625e25dfe62cdd6ff2cff3afcda8d4f3cd56))

  Extract context_grants_session_summary() in models.py and use it from SessionEngine and Matrix slash commands. Add a unit test for the helper and align credential-cache test with _cleanup_tracking clearing the cache.

  Made-with: Cursor

- fix: persist contexts on history tool_call events
  ([`c0ccbd5`](https://github.com/thiesgerken/carapace/commit/c0ccbd594f15e2acf58132559fb0f128c97cfb94))

  Add contexts to HistoryMessage so the REST history API matches WebSocket tool_call payloads. Session events now store top-level contexts when present in args; a model validator backfills from args for legacy rows. History fallback from model messages copies contexts from ToolCallPart args.

  Made-with: Cursor

- fix(web): show escalation cards only while pending
  ([`c8c502f`](https://github.com/thiesgerken/carapace/commit/c8c502f86ab87840a895562fa8ef2300f54b81e4))

  - Reconstruct history without domain, git push, or credential approval
    cards once a matching decision exists; tool rows carry the outcome.
  - On live response, remove those cards instead of a dimmed resolved state.
  - Add optional contexts to HistoryMessage for tool_call history parsing.

  Made-with: Cursor

- 📋 docs: better frontend readme
  ([`c05b3b4`](https://github.com/thiesgerken/carapace/commit/c05b3b4dd09be9f3b7a48261faf616dcbe8f4b7b))

- fix(sandbox): update domain notify callback to include approval context
  ([`244871d`](https://github.com/thiesgerken/carapace/commit/244871d4ce3b95bdec47170512ece301cadc37e7))

- fix(tools): improve formatting of credential and skill activation messages
  ([`ab24529`](https://github.com/thiesgerken/carapace/commit/ab24529431a065a6100ec5d23cc7ce0d63ca1a31))

- fix(server): improve context grant handling in credential fetch
  ([`4c0ed01`](https://github.com/thiesgerken/carapace/commit/4c0ed01e11b0cf5761cd0162c8a97b3178516db1))

  - Refactor credential fetching logic to directly access context grants by name, enhancing clarity and performance.
  - Ensure that only valid grants are checked against vault paths, preventing unnecessary iterations.

  Made-with: Cursor

- fix(sandbox): broaden exception handling for credential file deletion
  ([`e8b55c4`](https://github.com/thiesgerken/carapace/commit/e8b55c4b938c2138ba4e9d8ef38337bc44f340ab))

  - Change exception handling in SandboxManager to catch all exceptions during credential file deletion, ensuring that cleanup failures do not obscure the original execution errors.
  - Log a warning when deletion fails, maintaining clarity in error reporting.

  Made-with: Cursor

- fix(sandbox): deny skill-context credential fetch when security is unset
  ([`3f4d97c`](https://github.com/thiesgerken/carapace/commit/3f4d97c606e8ea631463c64d9f04cf18871f18c6))

  The skill fast path previously returned vault values without recording when active.security was None. Align with list/sentinel paths: return 403 Session not initialized and always record after security is confirmed.

  Made-with: Cursor

- fix(session): reinject skill file creds via context_grants
  ([`0bde194`](https://github.com/thiesgerken/carapace/commit/0bde1947d7aed8b788000cedba41491fb1e9dab1))

  Gate credential re-injection on the skill's ContextGrant vault paths instead of removed approved_credentials, and scope paths per skill.

  Add regression test for active and disk-loaded session state.

  Made-with: Cursor

- 🔇 fix: dedupe domain and credential UI notifications per exec
  ([`72200aa`](https://github.com/thiesgerken/carapace/commit/72200aa94712183b4499329bd32fe5a6b73e3177))

- add a test for reinjection
  ([`9a473d6`](https://github.com/thiesgerken/carapace/commit/9a473d609a2e36fc3d25a925ca7250ef3498cba5))

- 🔥 refactor: remove approved_credentials from session surface
  ([`0f75b26`](https://github.com/thiesgerken/carapace/commit/0f75b268dc45d7135695cfb37ab1eff505b82c78))

  Replace approved_credentials on SessionState with context_grants summary in /session command. The new output shows per-skill domains, vault_paths (metadata only), and cached credential count.

  - Remove approved_credentials field from SessionState and now()
  - Rewrite _get_approved_credential_paths to derive from context_grants
  - Update /session in engine.py, CLI, and Matrix channel
  - Remove unused _format_credentials and _credential_name helpers
  - Update tests and docs

- update docs
  ([`b9e690d`](https://github.com/thiesgerken/carapace/commit/b9e690d47063994c69d163cd5a4bb70008d7148d))

- 📋 docs: websocket messages
  ([`fd5da2e`](https://github.com/thiesgerken/carapace/commit/fd5da2e21078081d3887993751551eac8a3959bd))

### ✨ Features


- ✨Merge pull request #64 from thiesgerken/feat/context-scoped-skill-allowlists
  ([`c258670`](https://github.com/thiesgerken/carapace/commit/c258670bfa5169e68b6e3955615729067c95920f))

- ✨ Context-scoped skill allowlists
  ([`c258670`](https://github.com/thiesgerken/carapace/commit/c258670bfa5169e68b6e3955615729067c95920f))

- ✨ feat: show skill domains and credentials in expanded use_skill card, clean up summary
  ([`0a34122`](https://github.com/thiesgerken/carapace/commit/0a341222b2d19e88f7df0c79ab392f8e5358f3cd))

- ✨ feat: add per-tool Lucide icons to tool-call badges and approval cards
  ([`20d1e6f`](https://github.com/thiesgerken/carapace/commit/20d1e6f077597f624a485b48b9eb875920c8f237))

- ✨ feat: show active contexts in tool call expanded card
  ([`26037c2`](https://github.com/thiesgerken/carapace/commit/26037c22f169475c339ef5c6e123436e357bd4c8))

- ✨ feat: live WS notification for skill credential cache + dedupe tests
  ([`5caf1b0`](https://github.com/thiesgerken/carapace/commit/5caf1b059461f40e6e9c0813628fcf33e99760b6))

- ✨ feat: add record_credential_access helper, always register context_grant
  ([`e0529c2`](https://github.com/thiesgerken/carapace/commit/e0529c2b5a69b41a12acb19c10feb0faec96b540))

  - Add SessionSecurity.record_credential_access() that combines action log,
    audit log, and UI notification in a single call
  - Use the helper in server.py skill fast path (was missing action log entry),
    list_credentials endpoint, and evaluate_credential_with
  - Move context_grant creation outside the domains/creds guard in use_skill
    so every activated skill gets a grant registered

- ✨ feat: context-scoped skill allowlists
  ([`ebb8146`](https://github.com/thiesgerken/carapace/commit/ebb81465c322376e12a88db24c88ae28a2987418))

  Replace session-wide domain/credential approvals with context-scoped grants keyed by skill name. Every credential access goes through the sentinel except when covered by an activated skill under matching contexts. Emit proxy and credential events to the UI for full visibility, including denied requests.

  Changes:
  - Add ContextGrant model and context_grants field on SessionState
  - Extend ApprovalSource with 'skill' and 'bypass' literals
  - Rewrite use_skill to register context grants (not session-wide injection)
  - Add credential value cache to SandboxManager (per-exec, not permanent)
  - Thread contexts parameter through exec tool and sandbox stack
  - Per-exec file credential write/delete lifecycle
  - Domain auth fast path with skill/bypass origin tracking
  - Remove session-wide credential short-circuit; sentinel evaluates every access
  - Context fast path in fetch_credential for skill-declared vault paths
  - Frontend: skill (teal), bypass (gray), and deny (red) badge variants
  - 20 new tests for context grants, credential cache, and context tracking
  - Update docs: skills.md, credentials.md, websocket-session.md

### ♻️ Refactoring


- ♻️ refactor: replace inline SVGs with Lucide icons in approval cards
  ([`907a2fa`](https://github.com/thiesgerken/carapace/commit/907a2fa71c02af0aa513dec973779932d7fe3b5c))

- ♻️ refactor: extract _delete_context_file_credentials, widen ContainerGoneError catch
  ([`3d3332f`](https://github.com/thiesgerken/carapace/commit/3d3332f7c313e1839305857a711c1439043f4171))

  - Add _delete_context_file_credentials helper (mirrors _write_context_file_credentials)
  - Move ContainerGoneError catch to wrap both credential file write and exec,
    so a container dying between ensure_session and the credential write is
    handled the same way as one dying during exec
  - Inline delete loop in finally block replaced with helper call

- ♻️ refactor: extract _file_delete_in_container and _write_context_file_credentials helpers
  ([`7bc429a`](https://github.com/thiesgerken/carapace/commit/7bc429a6248a328da9a46b77c8012d2d715f5082))

- ♻️ refactor: derive ContextGrant.vault_paths from credential_decls
  ([`5fea999`](https://github.com/thiesgerken/carapace/commit/5fea999a7a26154635b56d04ceae177ebdf06968))

- ♻️ refactor: extract ApprovalSource alias, fix meta_errors parsing, improve context error message
  ([`687a90c`](https://github.com/thiesgerken/carapace/commit/687a90cc2b534f1bb61c1caa686c669d97fd1b69))

  - Replace 18 inline Literal[...] repetitions with ApprovalSource/ApprovalVerdict
    imports from security.context across engine.py, server.py, ws_models.py
  - Add failed_vault_paths set instead of fragile string splitting on meta_errors
  - Improve unknown contexts error: guide the user to activate skills first

### 💄 UI/UX


- 💄 polish: context grant sentinel format, exec cache warning, cred delete
  ([`02e1ad2`](https://github.com/thiesgerken/carapace/commit/02e1ad29d4cda75087736b0220f2b620bc445e00))

  - Format ContextGrantEntry in sentinel action log (no more [unknown])
  - Prefix exec output when skill credentials are missing from sandbox cache
  - Log rm failures and catch ContainerGoneError only after credential exec
  - Add test for _format_entry(ContextGrantEntry)

  Made-with: Cursor

## v0.74.0 (2026-04-09)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`cea60ea`](https://github.com/thiesgerken/carapace/commit/cea60eab785623c86cc640a52916bfc24cf20380))

## v0.73.0 (2026-04-09)


### ✨ Features


- ✨ feat: add unified diff viewer to str_replace tool details
  ([`14b8112`](https://github.com/thiesgerken/carapace/commit/14b8112386bedd3bcf86059c7c91c007779b2447))

- ✨ feat: add optional title param to exec tool
  ([`4de1f5a`](https://github.com/thiesgerken/carapace/commit/4de1f5a83eb25eebaa23322f25c75c958896506f))

## v0.72.0 (2026-04-09)


### ✨ Features


- ✨ feat: git identity via git config + commit-msg session trailer
  ([`2bcf331`](https://github.com/thiesgerken/carapace/commit/2bcf3318b66eb66ebdee9cedc6f1cb2c27c8bb5d))

  Replace GIT_AUTHOR/COMMITTER env vars with git config inside sandbox containers so %h (hostname) resolves at runtime. Install a commit-msg hook that appends a Carapace-Session trailer to every sandbox commit.

  Default author changed to 'Carapace <carapace@%h>'.

- ✨ feat: titler skips slash lines, truncates user text; add /retitle
  ([`b86402c`](https://github.com/thiesgerken/carapace/commit/b86402c7ed64a92f502fd26f0d3626e47a0c3959))

  Made-with: Cursor

### ⚡ Performance


- ⚡ perf: skip title LLM when using /model bulk switch
  ([`3a42d3b`](https://github.com/thiesgerken/carapace/commit/3a42d3bf4079ff67b2062e3443ba462ae048c813))

  Remove _regenerate_title from /model and /model reset; make _handle_model_all_command synchronous. Drop the test mock that only existed to stub that call.

  Made-with: Cursor

## v0.71.0 (2026-04-08)


### ✨ Features


- ✨ feat: rename /model to /model-agent; /model sets all three roles
  ([`7a5e172`](https://github.com/thiesgerken/carapace/commit/7a5e1723a8aaf323516dd744eee92fb1a7370222))

  /model now shows or updates agent, sentinel, and title together; /model-agent replaces per-session agent-only switching. CLI, Matrix, and web UI handle the new command names and combined /model payload shape.

  Made-with: Cursor

## v0.70.2 (2026-04-08)


### 🐛 Bug Fixes


- 🐛 fix: include ModelRequest instructions in usage input-shape ratios
  ([`043ba5d`](https://github.com/thiesgerken/carapace/commit/043ba5d1f45d5a2e4d1917bdc2d930635ca1af96))

  Agent prompts use pydantic-ai instructions= on ModelRequest, not SystemPromptPart; tiktoken breakdown left system at 0. Append instructions once when the system bucket is still empty after parts.

  Made-with: Cursor

## v0.70.1 (2026-04-08)


### 🐛 Bug Fixes


- 🐛 fix: add retries+output retries to all agents
  ([`9d9f817`](https://github.com/thiesgerken/carapace/commit/9d9f81742cd5b51bf7c0952c2e4e4d3949727a89))

## v0.70.0 (2026-04-08)


### Other


- 📋 docs: add ideas to roadmap
  ([`2d680a9`](https://github.com/thiesgerken/carapace/commit/2d680a9963dce69f0ed5614e3aeb5a2f684a9bf5))

### ✨ Features


- ✨ feat: OpenAI-compatible models, llm module, catalog-only available_models
  ([`d43490c`](https://github.com/thiesgerken/carapace/commit/d43490c3e0f6d2b26381d4da8bbba855f4d5ea6a))

  - Extend AvailableModelEntry with optional id, base_url, api_key; validate OpenAI-only overrides
  - Add carapace.llm (retry client, infer_model_with_retry_transport, make_model_factory)
  - Register-only model ids in factory; resolve infer_model via provider:name not custom id
  - agent.available_models is sole catalog (defaults + validator for model/sentinel/title)
  - Deps.agent_model_id for usage tracking and LLM log labels; fix ModelMessage isinstance
  - Wire model_factory through Sentinel and title generation

  Made-with: Cursor

## v0.69.2 (2026-04-07)


### Other


- docs: adjust roadmap
  ([`6b59c36`](https://github.com/thiesgerken/carapace/commit/6b59c36cadf7f957e4cbbac0d6c14f5cb6d77919))

### 🐛 Bug Fixes


- 🐛 fix: blank line before Matrix /usage context table for HTML render
  ([`476a996`](https://github.com/thiesgerken/carapace/commit/476a996e9519f23df64935051bbb081c317df233))

  Made-with: Cursor

## v0.69.1 (2026-04-07)


### 🐛 Bug Fixes


- 🐛 fix(usage): fix wrong counting of instructions
  ([`d02a144`](https://github.com/thiesgerken/carapace/commit/d02a144fdc81b469483339f985b02d371236fd37))

## v0.69.0 (2026-04-07)


### ✨ Features


- ✨ feat(session): persist resumable partial history on cancellation
  ([`c981c10`](https://github.com/thiesgerken/carapace/commit/c981c10ea3b00aca2022047803f94ef15cca90d8))

  Store message snapshots during turns and trim unresolved tool-call tails before persisting, keeping model and UI histories consistent after cancel or failure.

  Made-with: Cursor

## v0.68.9 (2026-04-07)


### 🐛 Bug Fixes


- 🐛 fix(sandbox): run env-injected commands via bash shell
  ([`3cd2d1e`](https://github.com/thiesgerken/carapace/commit/3cd2d1e7deaa5247a557cfb2ca9ba7a24e35f0ed))

  Wrap env-prefixed Kubernetes exec commands with bash -lc and quote workdir/env values so shell builtins like cd work reliably with credential-injected variables.

  Made-with: Cursor

## v0.68.8 (2026-04-07)


### ♻️ Refactoring


- ♻️Merge pull request #62 from thiesgerken/refactor/structured-tool-approval-metadata
  ([`081cb57`](https://github.com/thiesgerken/carapace/commit/081cb57fe0d1c90a3c826c70e3d84f33c1d3d3df))

- ♻️ refactor: use structured tool approval metadata
  ([`081cb57`](https://github.com/thiesgerken/carapace/commit/081cb57fe0d1c90a3c826c70e3d84f33c1d3d3df))

- ♻️ refactor(frontend): resolve remaining eslint warnings
  ([`b3627bf`](https://github.com/thiesgerken/carapace/commit/b3627bff14924126e21ed86f72c53bd822a3c8e6))

  Stabilize callback dependencies and remove unused values in chat and code-rendering components so frontend lint passes cleanly without suppressing rules.

  Made-with: Cursor

- ♻️ refactor(ui): use structured tool approval metadata
  ([`c1e449b`](https://github.com/thiesgerken/carapace/commit/c1e449b4e427f1c2e6720254135afc97c3b96d53))

  Pass approval source/verdict/explanation as typed fields from security evaluation through websocket/history into the UI, and render badges strictly from structured metadata instead of parsing detail strings.

  Made-with: Cursor

### 💄 UI/UX


- 💄 style(frontend): right-align tool approval badges
  ([`dab4d56`](https://github.com/thiesgerken/carapace/commit/dab4d56d19c7719353ff492a0cbc5d0ea4f3f153))

  Pin the badge/loading container to the right edge of tool call rows so approval badges stay consistently aligned when argument summaries are short or absent.

  Made-with: Cursor

### 🐛 Bug Fixes


- 🐛 fix(server): include approval metadata for credential listing events
  ([`b9ac674`](https://github.com/thiesgerken/carapace/commit/b9ac674b68b4e1b4e63d1b6f8d6cea40279d3c15))

  Emit structured approval_source/verdict/explanation for sandbox credential list notifications so the UI can render the approval badge for listed credentials.

  Made-with: Cursor

- 🐛 fix(frontend): avoid infinite loading without verdict metadata
  ([`4538b9b`](https://github.com/thiesgerken/carapace/commit/4538b9b7a0f83a63203363aa3163471bd9dccf72))

  Only show tool-call loading state when approval_verdict is explicitly allow, so missing metadata does not leave legacy events spinning forever.

  Made-with: Cursor

- 🐛 fix: address PR review feedback on approval metadata
  ([`e2ef222`](https://github.com/thiesgerken/carapace/commit/e2ef222a74fc21ce35ad7dd372867f8a33548981))

  Tighten callback typing and align docs/UI behavior with structured approval metadata so review comments are resolved without relying on fragile detail parsing.

  Made-with: Cursor

- 🐛 fix(frontend): restore lint compatibility and standardize caret ranges
  ([`80a8a76`](https://github.com/thiesgerken/carapace/commit/80a8a76bcdf0c9d2b9e1fe4f035bd0cfb04267c2))

  Pin ESLint to v9 to avoid the eslint-plugin-react crash in lint runs, and scope lint targets/ignores to prevent config and declaration files from triggering rule execution. Also standardize frontend dependency specifiers to caret ranges and set the local pnpm save-prefix for future consistency.

  Made-with: Cursor

### Other


- relock
  ([`d5cd24d`](https://github.com/thiesgerken/carapace/commit/d5cd24dc6924c4992f583f80ebf15093147b43dc))

- ✅ ci: run frontend lint on pull requests
  ([`f337154`](https://github.com/thiesgerken/carapace/commit/f337154060ee6a95e37a64824b52b1ff58050dfd))

  Add a dedicated frontend lint job in CI that installs frontend dependencies with pnpm and executes the lint script to catch UI lint regressions in PRs.

  Made-with: Cursor

- Merge branch 'main' into refactor/structured-tool-approval-metadata
  ([`66fb6fb`](https://github.com/thiesgerken/carapace/commit/66fb6fb8d965633a47a49e888a12f487e47a426f))

## v0.68.7 (2026-04-07)


### 🐛 Bug Fixes


- 🐛 fix(session): sanitize event payloads for safe YAML replay
  ([`cce41c8`](https://github.com/thiesgerken/carapace/commit/cce41c8d6810ac67f400ef15eff8b4ce97db757c))

  Avoid persisting Python object tags in session events by serializing skill credential gate args as JSON-safe data and sanitizing appended events. Add resilient event loading that skips malformed legacy docs instead of crashing turns.

  Made-with: Cursor

## v0.68.6 (2026-04-07)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`4843128`](https://github.com/thiesgerken/carapace/commit/48431280a64283ae56786a1082467176d53e87f8))

## v0.68.5 (2026-04-07)


### 💄 UI/UX


- 💄 polish(frontend): improve tool call phrasing and reload state
  ([`a6e2cf1`](https://github.com/thiesgerken/carapace/commit/a6e2cf170aaf21c7f6399d3e03378192c3fb5ca3))

  Refine tool-call one-liners with clearer action wording/tenses and preserve auxiliary styling, and make history hydration match interleaved tool results so completed calls render correctly after reload.

  Made-with: Cursor

### 🐛 Bug Fixes


- 🐛 fix(session): persist proxy and credential info tool calls
  ([`117058b`](https://github.com/thiesgerken/carapace/commit/117058b519e4d10edda39eae51c27b2a68eae4ce))

  Store `proxy_domain` and `credential_access` info callbacks as tool_call events so they survive session history reloads instead of only appearing in live websocket updates.

  Made-with: Cursor

## v0.68.4 (2026-04-07)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`8ea5f66`](https://github.com/thiesgerken/carapace/commit/8ea5f66243d792183461aee044ac33743676ad8e))

## v0.68.3 (2026-04-07)


### 🐛 Bug Fixes


- 🐛 fix(agent): align done usage with last LLM request
  ([`9297e33`](https://github.com/thiesgerken/carapace/commit/9297e3359475067da1572d4a3da5186cd9059e51))

  Use the last agent request record for done usage tokens so the UI matches the breakdown source, and remove the now-unused token tuple returned by run_agent_turn.

  Made-with: Cursor

- 🐛 fix(frontend): improve date formatting in sidebar component
  ([`6c2412a`](https://github.com/thiesgerken/carapace/commit/6c2412affc3a404b3a3daa3672b89875796577c0))

  Update the date formatting in the sidebar to use German locale settings, ensuring consistent display of day, month, and year. Additionally, clean up the JSX structure for better readability.

## v0.68.2 (2026-04-07)


### 🐛 Bug Fixes


- 🐛 fix(frontend): wrap markdown code lines without horizontal scrolling
  ([`dd7421a`](https://github.com/thiesgerken/carapace/commit/dd7421aa72b96d2b6aa43329e39f788d9629bc85))

  Ensure numbered markdown code lines soft-wrap and disable horizontal scrolling in the markdown code block renderer so long lines remain readable in place.

  Made-with: Cursor

## v0.68.1 (2026-04-07)


### 🐛 Bug Fixes


- 🐛 fix(frontend): stabilize token gauge context cap source
  ([`f8d1990`](https://github.com/thiesgerken/carapace/commit/f8d1990f7ff18156c10c526e69fa4befed8776bc))

  Use the backend-resolved context cap in turn usage payloads so the UI gauge no longer jumps to the 200k fallback when model metadata is temporarily unavailable after reconnects or backend restarts.

  Made-with: Cursor

- 🐛 fix(agent): require skill activation before reading existing skill files
  ([`48a64d3`](https://github.com/thiesgerken/carapace/commit/48a64d31aad5a11f2a6bd3789827cbee9860151f))

  Block `read` access to backend-existing files under `skills/<name>/` until the skill is activated, while still allowing sandbox-only files for skill creation. Also update the roadmap item now covered by this behavior.

  Made-with: Cursor

## v0.68.0 (2026-04-07)


### ✨ Features


- ✨ feat(frontend): refine tool one-liners for natural read/write/replace phrasing
  ([`b516b11`](https://github.com/thiesgerken/carapace/commit/b516b11cafee978d507ccd4562cecfadbf69d115))

  - Derive read summaries from separator-split output and emitted line count.
  - Collapse full-file reads to path-only summary to avoid duplicated 'read'.
  - Keep inclusive read ranges and cleaner write/replace wording in compact rows.

  Made-with: Cursor

## v0.67.1 (2026-04-07)


### Other


- 📋 docs: update roadmap
  ([`55d2f49`](https://github.com/thiesgerken/carapace/commit/55d2f49cb7e29a893989aa961c8a5a7a8ff694e4))

### ♻️ Refactoring


- ♻️ refactor(agent): disable unfinished read_memory tool
  ([`4bdfd2b`](https://github.com/thiesgerken/carapace/commit/4bdfd2b88ee7ee573bcfdb9b9a4d6b8ec84d9153))

  Remove the read_memory tool from the agent and safe-list so memory access only happens via sandbox workspace files for now. Update docs to stop advertising host-side memory reads until the feature is fully fleshed out.

  Made-with: Cursor

## v0.67.0 (2026-04-07)


### ✨ Features


- ✨ feat(frontend): humanize tool one-liners and polish write/replace panels
  ([`b4cd7c9`](https://github.com/thiesgerken/carapace/commit/b4cd7c9826ef57de69502ac0afb153e805ac9b27))

  - Make read/write/replace one-liners more natural-language and less key-value style.
  - Show label instead of and avoid duplicated wording.
  - Use line-based summaries (including equal-line compact form) and inclusive read ranges.
  - Keep highlighted write/replace payload views with tool output blocks where useful.

  Made-with: Cursor

## v0.66.0 (2026-04-07)


### ✨ Features


- ✨ feat(frontend): improve write/str_replace tool result UX
  ([`78b209a`](https://github.com/thiesgerken/carapace/commit/78b209a404ea84929a7670c404e00d20ec60de06))

  - Show write content and str_replace source/replacement as highlighted code.
  - Render str_replace source/replacement side-by-side on wider screens.
  - Streamline expanded panels by removing redundant metadata blocks.
  - Keep concise one-liners with line-count summaries and conditional replace_all.

  Made-with: Cursor

### 🐛 Bug Fixes


- 🐛 fix(sandbox): improve file_write result messaging
  ([`e30bb53`](https://github.com/thiesgerken/carapace/commit/e30bb532f7316dcfa4718113d1f18243ec4703eb))

  Return concise period-terminated success output with written line count for sandbox file writes, and include exit code details in fallback write errors.

  Made-with: Cursor

### ♻️ Refactoring


- ♻️ refactor(security): stop truncating tool call args in audit/events
  ([`e218cc6`](https://github.com/thiesgerken/carapace/commit/e218cc69c7dd576135c667a4efa465d248ed480a))

  Remove _truncate_args usage so tool call args are preserved in session and audit entries, including escalation metadata summaries.

  Made-with: Cursor

## v0.65.0 (2026-04-07)


### ✨ Features


- ✨ feat: replace edit/apply_patch with str_replace
  ([`a4f7898`](https://github.com/thiesgerken/carapace/commit/a4f7898e6f2e156a7416d0f057488552f2e640d9))

  Consolidate sandbox file editing around a single str_replace tool and remove diff-heavy edit outputs to keep agent context compact. Add replace_all semantics with original match line numbers in status messages, update safelist/docs/skill guidance, and cover the new script behavior with dedicated tests.

  Made-with: Cursor

## v0.64.1 (2026-04-06)


### 💄 UI/UX


- 💄 ui(frontend): split read tool metadata and code into separate cards
  ([`caa6c14`](https://github.com/thiesgerken/carapace/commit/caa6c148001bcfa48975d1b420a0c1527d99d734))

  Avoid nested borders on the code block; style error state on header and shell only.

  Made-with: Cursor

## v0.64.0 (2026-04-06)


### ✨ Features


- ✨ feat(frontend): split read tool result into metadata and highlighted body
  ([`9173efb`](https://github.com/thiesgerken/carapace/commit/9173efbe48c11a058f12a71a4378b7dfdd48440f))

  - Parse 24-dash separator to match sandbox read output; fence body with language from path.
  - Style read metadata like sentinel text; omit duplicate args block when split layout is used.

  Made-with: Cursor

- ✨ feat(sandbox): harden read tool with paging, caps, and binary handling
  ([`b2b9fae`](https://github.com/thiesgerken/carapace/commit/b2b9fae741de65f839774d8b37835ba5304fd58b))

  - Replace cat-based read with an inline Python script: line window (offset/limit),
    64Ki body char cap with truthful headers and partial-line truncation metadata.
  - Binary files return size and file(1) description only; NUL probe in first 64KiB.
  - Directory listing keeps ::DIR:: prefix; sandbox image installs the file package.
  - Add dashed separator between read metadata and body for UI/agent parsing.
  - Move sandbox exec script sources to container_scripts.py; gate read with offset/limit.
  - Add subprocess tests for the read script.

  Made-with: Cursor

## v0.63.0 (2026-04-06)


### ✨ Features


- ✨ feat: improve pull and slash-command result UX
  ([`932f184`](https://github.com/thiesgerken/carapace/commit/932f184c8ad41cc22ef4df71ce980c74b21cf92d))

  - Render message-only command_result payloads as prose in the web UI
  - Fix repeated /pull summary when merge is a no-op (compare HEAD before/after)
  - Human-readable pull text: revision line and bullet list of commit subjects

  Made-with: Cursor

## v0.62.0 (2026-04-06)


### ✨ Features


- ✨ feat(frontend): add copy Markdown control for assistant messages
  ([`b614480`](https://github.com/thiesgerken/carapace/commit/b6144804a65dccb56687cd3bbb595bb3f431a0f4))

  Made-with: Cursor

## v0.61.3 (2026-04-06)


### 🐛 Bug Fixes


- 🐛 force colored logging
  ([`5127fde`](https://github.com/thiesgerken/carapace/commit/5127fde124a26b928cf62ba019449875535fc5bb))

- 🐛 fix: pass explicit kr8s plural for Sandboxes (avoid sandboxess URL)
  ([`60881cc`](https://github.com/thiesgerken/carapace/commit/60881cc33d104e8a76a729351eecb1b0b0a93215))

  Made-with: Cursor

## v0.61.2 (2026-04-06)


### 🐛 Bug Fixes


- 🐛 fix: log Sandboxes owner lookup failures (403 RBAC vs 404 name)
  ([`968abd9`](https://github.com/thiesgerken/carapace/commit/968abd928224425f273f86de282da036123b0ff4))

  Made-with: Cursor

## v0.61.1 (2026-04-06)


### 🐛 Bug Fixes


- 🐛 fix: Sandboxes CRD schema must not mix properties with additionalProperties
  ([`b566274`](https://github.com/thiesgerken/carapace/commit/b566274f42c4178382996f8ae165e4ff8e731936))

  Made-with: Cursor

## v0.61.0 (2026-04-06)


### ✨ Features


- ✨Merge pull request #61 from thiesgerken/feat/sandbox-collection-owner
  ([`859774f`](https://github.com/thiesgerken/carapace/commit/859774fff972eca2c367631f17e8748aa4deca1b))

- ✨ feat: prefer SandboxCollection owner for sandbox StatefulSets
  ([`859774f`](https://github.com/thiesgerken/carapace/commit/859774fff972eca2c367631f17e8748aa4deca1b))

- ✨ feat: prefer SandboxCollection owner for sandbox StatefulSets
  ([`f9ffb84`](https://github.com/thiesgerken/carapace/commit/f9ffb84d442691d78290efc4a6ccec12774930c7))

  Introduce a SandboxCollection CRD as the preferred ownerReference anchor for runtime sandboxes while preserving Deployment fallback for safe rollout, and remove Argo Application owner lookup. Update Helm, RBAC, tests, and docs to reflect ownership-only CRD usage with no operator yet.

  Made-with: Cursor

### ♻️ Refactoring


- ♻️ refactor: rename SandboxCollection CRD to Sandboxes
  ([`3ef624a`](https://github.com/thiesgerken/carapace/commit/3ef624a3e61137a0833512da8cb357802dff0819))

  Made-with: Cursor

### Other


- Merge branch 'main' into feat/sandbox-collection-owner
  ([`90c2690`](https://github.com/thiesgerken/carapace/commit/90c2690a10ad517906cfe909c30802f3a5b5ff91))

- Merge remote-tracking branch 'origin/main' into feat/sandbox-collection-owner
  ([`bb395d4`](https://github.com/thiesgerken/carapace/commit/bb395d43f0759390520bd13989cf52573ec4a306))

### 🐛 Bug Fixes


- 🐛 fix: add unified as explicit dependency
  ([`13043c7`](https://github.com/thiesgerken/carapace/commit/13043c73a847f87ea888506083f9f4bd08ce317d))

## v0.60.1 (2026-04-06)


### 🐛 Bug Fixes


- 🐛 fix: add unified as explicit dependency
  ([`621aa1f`](https://github.com/thiesgerken/carapace/commit/621aa1feefb7494e73702460a8bda0797248d34c))

## v0.60.0 (2026-04-06)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`81a4173`](https://github.com/thiesgerken/carapace/commit/81a41738ebf00fc7dd2cfc358242cc95d76c799f))

## v0.59.1 (2026-04-06)


### ✨ Features


- ✨ feat: send full tool results to UI callbacks.
  ([`52f7435`](https://github.com/thiesgerken/carapace/commit/52f74354af78ab26c09220253ee01ab557b6b68a))

  Stop truncating tool_result callback output so UI rendering receives complete tool results; future command-length limits can be handled separately at execution time.

  Made-with: Cursor

- ✨ feat: simplify skill activation card rendering.
  ([`1e4e0d4`](https://github.com/thiesgerken/carapace/commit/1e4e0d4381f45e2ab5ad1c96a51b3ac687dedf16))

  Show a concise skill activation intent line and render use_skill output as markdown with YAML front matter highlighted for better readability.

  Made-with: Cursor

### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`2b54c69`](https://github.com/thiesgerken/carapace/commit/2b54c69b84a477e5a07e0677cec1a368e1f291f5))

## v0.59.0 (2026-04-06)


### 💄 UI/UX


- 💄 style: update body font size in globals.css
  ([`d19baac`](https://github.com/thiesgerken/carapace/commit/d19baac5165915ab0ee6e6f63d0c65a70316676b))

  Increase font size from 0.85em to 0.9em for improved readability in body styles across the application.

### ✨ Features


- ✨ feat: render exec details as shell transcript markdown.
  ([`148d18d`](https://github.com/thiesgerken/carapace/commit/148d18d4844226d75c1805024a1dc5fae1612e8d))

  Use markdown-based shell transcript rendering for expanded exec calls with a cleaner single-block UI, improved prompt styling, and tuned sizing/trimming for readable output.

  Made-with: Cursor

## v0.58.0 (2026-04-06)


### ✨ Features


- ✨ feat: add LaTeX math rendering in chat markdown.
  ([`aaff202`](https://github.com/thiesgerken/carapace/commit/aaff20209610dfe2302148939edbfa50eb9ca5c6))

  Enable inline and block formula rendering with remark-math + rehype-katex while preserving Shiki async highlighting, and update response guidance so math is emitted in supported delimiters.

  Made-with: Cursor

## v0.57.0 (2026-04-06)


### ✨ Features


- ✨ feat: chat markdown highlighting and code block UX
  ([`5ba01c3`](https://github.com/thiesgerken/carapace/commit/5ba01c3c4b5413741f8287753662c3c671638cf6))

  Add Shiki via rehype-pretty-code with MarkdownHooks, theme-aware CSS, copy button and language label, line numbers, and a 35-line scroll cap. Plain-fence fallback gets the same line numbers. Extend the agent system prompt for Markdown replies and fenced-code language tags. Ignore .pnpm-store in .gitignore.

  Made-with: Cursor

## v0.56.0 (2026-04-06)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`9ad9f90`](https://github.com/thiesgerken/carapace/commit/9ad9f9082d07b0ce9c9e6ef4099cc5b9960e6910))

- dev: add more ports to cors
  ([`802a352`](https://github.com/thiesgerken/carapace/commit/802a35248eeab0d548b25dff0da4f220a5ff72bd))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`daebdc0`](https://github.com/thiesgerken/carapace/commit/daebdc0316680a18fb490404ca81a383a39a022d))

### ✨ Features


- ✨ feat: show context cap percentage in /usage display
  ([`513cce2`](https://github.com/thiesgerken/carapace/commit/513cce2ef41d40d8c48d024da33f8586a366f0b4))

  - Enrich last_llm rows with context_cap_tokens and context_used_pct (config max_input_tokens or 200k default)
  - Web UsageView Tokens column: show pct next to token count; CLI Context table matches

  Made-with: Cursor

### 💄 UI/UX


- 💄 polish: improve tool call row layout and argument summary
  ([`ac88c27`](https://github.com/thiesgerken/carapace/commit/ac88c277b54a6fdeaa9c7dc4c3bd5dfd7a3ae9d0))

  Omit redundant key prefixes for exec/read/use_skill, use full-width flex truncation for arguments, and improve argument text contrast.

  Made-with: Cursor

## v0.55.0 (2026-04-06)


### Other


- 📋 docs: add todos to roadmap
  ([`c38c220`](https://github.com/thiesgerken/carapace/commit/c38c2208718508405dd809e90489810adaa17318))

### ✨ Features


- ✨ feat: structured available_models and context gauge from max_input_tokens
  ([`ef097b4`](https://github.com/thiesgerken/carapace/commit/ef097b4f689bb7addac8fa1233a53a21512845fb))

  - Add AvailableModelEntry (shorthand provider:name or mapping with optional max_input_tokens)
  - Merge/dedupe entries in SessionEngine; GET /api/models and /models return objects with id alias
  - TurnUsage includes canonical agent model id for WebSocket done/status
  - Frontend: fetch model descriptors, TokenGauge cap from config with 200k fallback
  - CLI /models prints structured available list; tests for parsing and merge last-wins

  Made-with: Cursor

## v0.54.2 (2026-04-06)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`da513a1`](https://github.com/thiesgerken/carapace/commit/da513a134636b000cdfa2b760424b1991d4dae30))

## v0.54.1 (2026-04-06)


### 💄 UI/UX


- 💄 typos and lints
  ([`d890665`](https://github.com/thiesgerken/carapace/commit/d890665c87d2190206eb2979e55f00b6fa5e1c26))

### ♻️ Refactoring


- ♻️ refactor: reorganize usage stuff into one file
  ([`70a87ed`](https://github.com/thiesgerken/carapace/commit/70a87edfed59a4a6baca738c8187e9089b85e237))

## v0.54.0 (2026-04-06)


### ✨ Features


- ✨Merge pull request #60 from thiesgerken/feature/context-breakdown
  ([`74e5ca8`](https://github.com/thiesgerken/carapace/commit/74e5ca85b1c64a7ab2d35ab1d8a14674ae1bfde2))

- ✨ feat: LLM request log with tiktoken context breakdown
  ([`74e5ca8`](https://github.com/thiesgerken/carapace/commit/74e5ca85b1c64a7ab2d35ab1d8a14674ae1bfde2))

- ✨ feat: LLM request log with tiktoken context breakdown
  ([`1e0d90f`](https://github.com/thiesgerken/carapace/commit/1e0d90f6bc80a2cd532951c25b9ba29a48aa7be9))

  Persist per-request API token counts and prompt-bucket percentages (system/user/assistant/tool calls/tool outputs) via LlmRequestLog; show Context section in web, CLI, and Matrix /usage; remove context_tokens; add tiktoken dependency.

  Made-with: Cursor

### Other


- show breakdown in the context gauge
  ([`d171b14`](https://github.com/thiesgerken/carapace/commit/d171b1473cc8d43816fb6bf928619ef6fe5480a9))

- styling
  ([`64a24f1`](https://github.com/thiesgerken/carapace/commit/64a24f1e5b81431bf29a6b2d3546c5716ccdec53))

## v0.53.0 (2026-04-05)


### ✨ Features


- ✨ feat: prefer Argo CD Application as sandbox owner on Kubernetes
  ([`89f24ba`](https://github.com/thiesgerken/carapace/commit/89f24ba882db8e2f3c815e21fe648c2ab5f12c9f))

  When owner refs are enabled and ownerTarget is auto (default), resolve an argoproj.io Application in the workload namespace before falling back to the server Deployment. Same-namespace owner refs are required by K8s.

  Helm sets server deployment name from the release and grants get/list on applications. Add sandbox.ownerTarget and optional argocdApplication overrides in values.

  Made-with: Cursor

### 🐛 Bug Fixes


- 🐛 fix: model title not running when first message was a slash command
  ([`ef4c3de`](https://github.com/thiesgerken/carapace/commit/ef4c3de1633427f7bf7eaaa908319c8edeef13d8))

## v0.52.2 (2026-04-05)


### 🐛 Bug Fixes


- 🐛 make it clear in the example skills and create skill skill how carapace.yaml works
  ([`7922bb8`](https://github.com/thiesgerken/carapace/commit/7922bb8f63a463cc5fecdc70715f77ab9c59a675))

- 🐛 swawp colors for shields in ui, safe-list -> auto
  ([`aca08e4`](https://github.com/thiesgerken/carapace/commit/aca08e41e0679831cd0806212766aad49074f861))

### Other


- 📝 docs: update security policy documentation
  ([`b378a14`](https://github.com/thiesgerken/carapace/commit/b378a14afbbf062283b27290fd7fabd82b8811d2))

  - Expanded the safe-list check to include additional tool names.
  - Revised the default security policy to clarify principles and threats.
  - Enhanced descriptions of the sentinel's role and decision-making criteria.
  - Streamlined guidance on handling network requests and skill activations.

  These changes improve clarity and comprehensiveness of the security measures in place.

## v0.52.1 (2026-04-03)


### 🐛 Bug Fixes


- 🐛 fix: probe Bitwarden sidecar via curl on 127.0.0.1
  ([`1103491`](https://github.com/thiesgerken/carapace/commit/1103491e80f6a3b5b0b78affced60e5bd8f164fe))

  tcpSocket probes target the pod IP while bw serve binds localhost only. Install curl in the sidecar image; use exec probes for startup, readiness, and POST /sync liveness.

  Made-with: Cursor

### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`5b4cab0`](https://github.com/thiesgerken/carapace/commit/5b4cab0af576720b3b78d5e4411f38fc9b80b504))

## v0.52.0 (2026-04-03)


### Other


- scale down bw-cli on dev
  ([`3f69588`](https://github.com/thiesgerken/carapace/commit/3f69588cf6f98c0f1ade5f9e8649454b2bc1eb45))

### ✨ Features


- ✨ feat: persist Bitwarden CLI data across restarts
  ([`0d42d7b`](https://github.com/thiesgerken/carapace/commit/0d42d7b452776516384c48553c92ebf069c2d837))

  - Set BITWARDENCLI_APPDATA_DIR under BW_DATA_DIR; cache server URL in carapace-state
  - Helm: optional PVC per sidecar (bitwarden.persistence, default enabled)
  - Docker Compose: named volume on /var/lib/bitwarden-cli
  - Document in chart README, bitwarden-cli README, quickstart, credentials

  Made-with: Cursor

## v0.51.0 (2026-04-03)


### Other


- comment
  ([`329a4f0`](https://github.com/thiesgerken/carapace/commit/329a4f0254212182fd4bd30aaafd914b60affe2e))

### ✨ Features


- ✨ feat: load Bitwarden creds from mounted secret files
  ([`2fefbf4`](https://github.com/thiesgerken/carapace/commit/2fefbf401d07bd01f406d30cca5adcf9c1e7bdaa))

  - Sidecar entrypoint reads BW_* from BW_SECRET_DIR (default /run/secrets/bitwarden)
    when env is unset, then unsets sensitive vars before bw serve
  - Helm: mount existingSecret at /run/secrets/bitwarden instead of envFrom
  - Document in bitwarden-cli/README.md and charts/carapace README/values

  Made-with: Cursor

## v0.50.0 (2026-04-03)


### ✨ Features


- ✨ Merge pull request #59 from thiesgerken/feature/credentials
  ([`360155d`](https://github.com/thiesgerken/carapace/commit/360155de7648d46d6aadc02d888648ae73afcaa5))

- ✨ feat: credential management system
  ([`360155d`](https://github.com/thiesgerken/carapace/commit/360155de7648d46d6aadc02d888648ae73afcaa5))

- ✨ feat: log sandbox tool exceptions for better error tracking
  ([`fe91b2e`](https://github.com/thiesgerken/carapace/commit/fe91b2e4964ccf53ccc87c0b24b7fc90b4bc5e68))

  - Introduced a new function `_log_sandbox_tool_exception` to log full tracebacks for sandbox tool failures.
  - Integrated this logging function into the error handling of file read, write, edit, apply patch, and exec operations to enhance debugging capabilities.

  Made-with: Cursor

- ✨ feat: context_tokens for usage bar and breakdown
  ([`4d8fd9d`](https://github.com/thiesgerken/carapace/commit/4d8fd9d9bae5d05e82df28b539cac8a88e38bb9e))

  Track last-LLM slice on ModelUsage; expose TurnUsage.context_tokens over WS. Web gauge uses it; /usage shows a Context column for categories only. CLI and Matrix usage tables match.

  Made-with: Cursor

- ✨ feat: show per-category usage cost
  ([`0da2b45`](https://github.com/thiesgerken/carapace/commit/0da2b45c465a0763fd2fdf7109abffe13adc1357))

  Track tokens per category and model for pricing, expose category_costs in /usage payload, and render Cost in By Category (web, CLI, Matrix).

  Made-with: Cursor

- ✨ feat: enhance skill management and asset synchronization
  ([`92d6072`](https://github.com/thiesgerken/carapace/commit/92d607236eaf668fec6bb2c6738e85a0ea419d33))

  Introduced a new function to recursively gather file paths from bundled skills and updated the knowledge directory synchronization process to copy these skills into the target directory when missing. Removed the previous seeding logic for skills in favor of this more dynamic approach.

  Made-with: Cursor

- ✨ feat: Matrix channel support for credential approvals
  ([`692fdb5`](https://github.com/thiesgerken/carapace/commit/692fdb5756b163defb175ad85f526556646cdab3))

  Phase 8 of credential management.

  - PendingCredentialApproval class in approval.py
  - MatrixSubscriber.on_credential_approval_request sends formatted
    credential request message (key icon, names, descriptions)
  - _on_reaction handles credential approval via emoji reactions
  - _resolve_pending handles /allow and /deny commands for credentials
  - CredentialApprovalResponse wired through submit_approval

  Made-with: Cursor

- ✨ feat: Vaultwarden backend and bw serve process management
  ([`9aef3a4`](https://github.com/thiesgerken/carapace/commit/9aef3a42199da1dd5c29eb6371b9a6e42d26957c))

  Phase 7 of credential management.

  - BwServeManager: handles bw login, unlock, serve lifecycle, periodic
    vault sync, and auto-restart; managed as a child process
  - VaultwardenBackend: talks to bw serve via httpx — fetch password by
    UUID, fetch item metadata, list/search items with exposure filtering
  - build_credential_registry is now async to support bw serve startup
  - Server lifespan calls shutdown_credential_registry on exit
  - Added bw_serve_port config field to CredentialBackendConfig

  Made-with: Cursor

- ✨ feat: ccred CLI helper and built-in credentials skill
  ([`fb5b623`](https://github.com/thiesgerken/carapace/commit/fb5b623d6954ec7d4aac1cfdc4ac3d1d527bcc63))

  Phase 6 of credential management.

  - ccred: stdlib-only Python CLI baked into sandbox image
    - `ccred list [-q query]`: list credential metadata
    - `ccred get <vault_path> [-o file]`: fetch value (blocks until approved)
    - Uses CARAPACE_API_URL for auth, no extra dependencies
  - Built-in credentials skill (SKILL.md) teaches the agent:
    - Auto-injection via carapace.yaml (env_var + file)
    - On-demand fetch with ccred
    - Security rules (never echo/log/return values)
  - Updated sandbox Dockerfile to include ccred

  Made-with: Cursor

- ✨ feat: credential approval card in frontend
  ([`2b9d253`](https://github.com/thiesgerken/carapace/commit/2b9d253ea6c3168edca406cb613104e31f33b835))

  Phase 5 of credential management: frontend UI integration.

  - CredentialApprovalRequest/Response types in types.ts
  - CredentialApprovalCard component (key icon, name/description list,
    approve/deny buttons — follows existing escalation card pattern)
  - chat-view.tsx handles credential_approval_request WS messages,
    sends credential_approval_response on user action
  - History loading supports credential approval events
  - Message component renders credential_approval chat messages

  Made-with: Cursor

- ✨ feat: wire credential auto-injection into use_skill tool
  ([`4733d55`](https://github.com/thiesgerken/carapace/commit/4733d55849ba42c5294615a6d7ac0bb531824815))

  Phase 4 of credential management: skill activation credential gating.

  - use_skill includes credential vault_paths in sentinel gate args
  - After approval, credentials are fetched from vault and injected:
    - env_var entries → session_env (persists across exec calls)
    - file entries → written to sandbox with mode 0400
  - CredentialRegistry added to Deps and wired through SessionEngine
  - Approved credentials recorded in session state and action log
  - Agent never sees credential values — only injection summary

  Made-with: Cursor

- ✨ feat: add credential REST endpoints, approval flow, and WS messages
  ([`34f5347`](https://github.com/thiesgerken/carapace/commit/34f5347bf100f9203c84de2cde92ec072236f6fc))

  Phase 3 of credential management: server endpoints and approval wiring.

  - GET /credentials (list/search) and GET /credentials/{vault_path} (fetch)
    on sandbox API with blocking approval flow
  - CredentialApprovalRequest/Response WebSocket messages
  - CredentialAccessEntry in security action log
  - SessionEngine.request_credential_approval() with queue-based blocking
  - on_credential_approval_request added to SessionSubscriber protocol
  - WebSocketSubscriber wired for credential approval + reconnect re-send
  - CredentialRegistry built in server lifespan

  Made-with: Cursor

- ✨ feat: add file vault backend, exposure filter, and credential registry
  ([`ab29fb1`](https://github.com/thiesgerken/carapace/commit/ab29fb198183b02cceccd4d39aa1c26ca302dee2))

  Phase 2 of credential management: vault backend implementation.

  - FileVaultBackend reads .env-format files, caches in memory
  - Exposure filter (expose allowlist / hide blocklist) per backend
  - CredentialRegistry dispatches vault_path prefixes to backends
  - build_credential_registry() factory from config
  - CredentialBackendConfig + CredentialsConfig added to Config model
  - Comprehensive tests for file backend, exposure, and registry

  Made-with: Cursor

- ✨ feat: add credential models, vault protocol, and session_env plumbing
  ([`12e6bcc`](https://github.com/thiesgerken/carapace/commit/12e6bcc8ef16293279016bf7d49502d81ba215a5))

  Phase 1 of credential management: models and wiring.

  - Add CredentialMetadata and SkillCredentialDecl models
  - Upgrade SessionState.approved_credentials to list[CredentialMetadata]
  - Replace MockCredentialBroker with VaultBackend protocol
  - Add session_env to SessionContainer, wired into every _exec() call
  - Inject CARAPACE_API_URL into sandbox environment
  - Update all callers and tests for the new types

  Made-with: Cursor

### 🐛 Bug Fixes


- 🐛 fix: survive vault HTTP errors during skill credential injection
  ([`2426f7f`](https://github.com/thiesgerken/carapace/commit/2426f7f8c3346f4840a8fc659e17350300b040db))

  Catch httpx transport and status errors around fetch_metadata and fetch; log warnings, report to the agent, and only approve/inject paths that succeeded so use_skill still completes after activate_skill.

  Made-with: Cursor

- 🐛 fix: count credentials once when both env and file inject
  ([`efc0a3f`](https://github.com/thiesgerken/carapace/commit/efc0a3f96d7a3ec114843e63aed923e4dca85a4f))

  _do_inject previously summed env and file placements, so one decl with both targets reported two credentials.

  Made-with: Cursor

- 🐛 fix: record vault_paths on credential approval response events
  ([`b2064ed`](https://github.com/thiesgerken/carapace/commit/b2064edbdec035e9db43b5291603a9d10a812c41))

  Stop reusing domain/command from domain-access escalation shape; keeps history and audits from misclassifying vault paths as network domains.

  Made-with: Cursor

- 🐛 fix: resolve sandbox Docker network from server container attachments
  ([`e782dd6`](https://github.com/thiesgerken/carapace/commit/e782dd606a8b60834923dbe7c37ba37c779f4f57))

  Prefer the network the Carapace container is already on (exact or *_{logical}) before listing by short name, so Compose-prefixed bridges are not missed and a duplicate carapace-sandbox network is not created.

  Made-with: Cursor

- 🐛 fix: handle relative paths for file credentials in registry
  ([`f2298a6`](https://github.com/thiesgerken/carapace/commit/f2298a632d35d6a592ece3a397917a4cd33ff93b))

  Updated the `build_credential_registry` function to correctly resolve relative paths for file credentials, ensuring they are properly combined with the data directory. Added a new test to verify the functionality of relative paths under the data directory.

  Made-with: Cursor

- 🐛 fix: safely re-inject file credentials after sandbox recreation
  ([`034441d`](https://github.com/thiesgerken/carapace/commit/034441d2fc5b55ddb762d5bbe642cc7601f7c795))

  Restore approved file credentials during skill sync after container recreation, including skills without a venv. Avoid lock re-entry by performing rebuild-time exec and file writes on the active container without nested _exec calls.

  Made-with: Cursor

- 🐛 fix: preserve session_env across container recreation
  ([`4fecda3`](https://github.com/thiesgerken/carapace/commit/4fecda35204441eca45a2dd850d0f0b90b137db9))

  _prepare_session_recreate discarded the SessionContainer including its session_env, so credential variables injected via set_session_env were silently lost when a sandbox was recreated after a ContainerGoneError. Stash the env before popping and restore it onto the replacement container.

  Made-with: Cursor

- 🐛 fix: accept credential approval events in history
  ([`ae6116a`](https://github.com/thiesgerken/carapace/commit/ae6116afcccd47becd9a7a5e5e9f69ae50dfd14c))

  Include credential approval role and payload fields in history API validation so persisted approval events are returned instead of being dropped during reconnect.

  Made-with: Cursor

- 🐛 fix: preserve ~ expansion in quoted file_write paths
  ([`f759e9f`](https://github.com/thiesgerken/carapace/commit/f759e9f159c6b48f98f7672df01ebcb6dfca6166))

  Keep `$HOME` unquoted for `~/` inputs when `quote=True` so shell expansion still works while path suffixes remain safely quoted.

  Made-with: Cursor

- 🐛 fix: render approved credential names in Matrix session output
  ([`b2db35c`](https://github.com/thiesgerken/carapace/commit/b2db35c3a0227cb2ac94113cf19e789f81ea6fba))

  Handle CredentialMetadata model instances in Matrix command formatting so /session shows clean credential names instead of Pydantic repr strings.

  Made-with: Cursor

- 🐛 fix: persist explanation in credential approval and drain queue on cancel
  ([`dc98158`](https://github.com/thiesgerken/carapace/commit/dc9815844f0c61a2fb1d274215490927112a886c))

  Explanation was passed to broadcast but not stored in pending_credential_approvals, so reconnecting clients lost context. credential_approval_queue was also never drained on new turns or signaled on cancel, risking stale decisions and hung waiters.

  Made-with: Cursor

- 🐛 fix: build credential registry before SessionEngine uses it
  ([`0acc510`](https://github.com/thiesgerken/carapace/commit/0acc510bfcc2fedff3d21bdaedf3daec2e07fc75))

  The engine was constructed with the uninitialized _credential_registry reference. Move registry construction before engine creation and inject it via set_credential_registry().

  Made-with: Cursor

- 🐛 fix: skip lines without '=' in file credential backend
  ([`9a4c22d`](https://github.com/thiesgerken/carapace/commit/9a4c22d898cb26f2be5427a87dde1ab84e85e308))

  str.partition() never returns None for the separator, so the old `value is not None` check always passed. Check the separator instead and log a warning for malformed lines.

  Made-with: Cursor

- 🐛 fix: send Basic Auth header in ccred requests
  ([`b215b86`](https://github.com/thiesgerken/carapace/commit/b215b86ef4b7dc7a996b121d1ae179c1409b61c5))

  urllib doesn't extract credentials from user:pass@host URLs automatically. Parse CARAPACE_API_URL, extract embedded credentials, and attach them as an Authorization header on every request.

  Made-with: Cursor

- 🐛 fix: use HTTPException for 401 in credential endpoints
  ([`cff109a`](https://github.com/thiesgerken/carapace/commit/cff109a7f2241137b3ea9efd9dd8d97635b52554))

  Replace Response(401) with HTTPException so the return type annotation is accurate and the OpenAPI schema stays consistent.

  Made-with: Cursor

### ♻️ Refactoring


- ♻️ refactor: pass credential registry into SessionEngine
  ([`e4f8f2a`](https://github.com/thiesgerken/carapace/commit/e4f8f2a9452cbc287dd29851253153052fb71797))

  Require CredentialRegistryProtocol on engine construction and Deps; build the registry before creating the engine in server lifespan. Remove set_credential_registry and the None registry code path in skill injection.

  Made-with: Cursor

- ♻️ refactor: return ExecResult from sandbox file ops
  ([`448f1ba`](https://github.com/thiesgerken/carapace/commit/448f1ba15b689c118995da1add28fc6106e6b547))

  file_write, file_edit, and file_apply_patch now expose exit_code and output like exec_command. Call sites use exit_code for failures instead of parsing message prefixes.

  Made-with: Cursor

- ♻️ refactor: dedupe sandbox exec and file-write paths
  ([`dd1a815`](https://github.com/thiesgerken/carapace/commit/dd1a815a88a4c48ddfddec41ee8e1d8cd25fb3c5))

  - Add _exec_in_container and route _exec through it (keep lock, bypass, retry)
  - Share _file_write_shell_command and _file_write_in_container
  - Unify skill venv build in _build_skill_venv_in_session

  Made-with: Cursor

- ♻️ refactor: unify credential backend shutdown interface
  ([`ed77c5b`](https://github.com/thiesgerken/carapace/commit/ed77c5b988e0bba4e5d00dcaafffc1f24638e7b4))

  Make registry shutdown backend-agnostic by requiring a close() method on all credential backends. This removes backend type checks and keeps lifecycle handling consistent as backends evolve.

  Made-with: Cursor

- ♻️ refactor: credential module cleanups
  ([`0604902`](https://github.com/thiesgerken/carapace/commit/06049024eb39895baa31c88302d9607a4c7abd96))

  - Remove dead HTTP 202 retry loop in ccred (server blocks until resolved)
  - Extract require_exposed() helper to DRY up is_exposed guard in backends
  - Validate that backend names don't contain '/' (vault_path separator)

  Made-with: Cursor

- ♻️ refactor: credential registry type safety and encapsulation
  ([`e1d3bbf`](https://github.com/thiesgerken/carapace/commit/e1d3bbf4420c833bc7aa1a44844ba499bd336015))

  - Add CredentialRegistryProtocol to replace Any typing in Deps and engine
  - Use CredentialBackendConfig discriminated union in CredentialsConfig.backends
  - Add assert_never exhaustiveness branch in build_credential_registry
  - Move shutdown logic into CredentialRegistry.close(), drop standalone function

  Made-with: Cursor

- ♻️ refactor: externalize bw serve, discriminated union config, bw-serve image
  ([`bc883de`](https://github.com/thiesgerken/carapace/commit/bc883de69c041927e220eccfdfc1e57fc0cd5b27))

  - Remove BwServeManager — Carapace no longer spawns bw serve; it expects
    an external sidecar (Docker Compose network_mode or K8s sidecar).
  - Rename VaultwardenBackend → BitwardenBackend, vaultwarden.py → bitwarden.py.
  - Replace flat CredentialBackendConfig with discriminated union
    (FileCredentialBackendConfig | BitwardenCredentialBackendConfig).
  - Replace bw_serve_port with full url field (default http://127.0.0.1:8087).
  - Add bw-serve/ Dockerfile + entrypoint (Bitwarden CLI sidecar image).
  - Add CI + release jobs for the bw-serve image.
  - Add bw sidecar to docker-compose (scale: 0 by default).
  - Add bitwarden.instances sidecar support to Helm chart with startup,
    readiness, and liveness probes (liveness doubles as periodic vault sync).
  - Update credentials plan, Helm README, and chart values.

  Made-with: Cursor

- ♻️ refactor: split credentials module into subpackage
  ([`5f690e3`](https://github.com/thiesgerken/carapace/commit/5f690e3a0f70656df8154fa564adeb65dac988b4))

  Extract credentials.py into credentials/ with separate files for the protocol, file backend, vaultwarden backend, and registry. Public API unchanged via __init__.py re-exports.

  Made-with: Cursor

- ♻️ refactor: drop CredentialAccessEntry action field and list logging
  ([`11ddfb4`](https://github.com/thiesgerken/carapace/commit/11ddfb4cebe8f050774ef3f0ac0e9dc8345aa6a0))

  Credential list/search is gated purely at the tool level by the sentinel; no separate audit entry needed. Keep CredentialAccessEntry for fetch only.

  Made-with: Cursor

- ♻️ refactor: improve file_write with ~ expansion, mode, and workdir
  ([`0240ece`](https://github.com/thiesgerken/carapace/commit/0240ece35423713ff08284f8fc039f9a67393d54))

  - Add _expand_home() to replace ~/ with $HOME/ for bash double-quoting
  - Add optional mode and workdir params to file_write
  - Credential file injection now uses file_write instead of hand-rolled
    shell commands, with workdir set to the skill directory for relative paths
  - Remove lazy imports from tools.py

  Made-with: Cursor

- ♻️ refactor: remove approval timeout from ccred get
  ([`8f61a4d`](https://github.com/thiesgerken/carapace/commit/8f61a4d71923b1f113d6e787b7a41044671ecace))

  The command now polls indefinitely until the user approves or denies, rather than giving up after 300 seconds.

  Made-with: Cursor

- ♻️ refactor: rename ccred `list -q` to `search`, update examples and wording
  ([`8e37077`](https://github.com/thiesgerken/carapace/commit/8e37077856b6a52da22baf18b0844a2a63377660))

  - Split `list -q QUERY` into a standalone `search QUERY` subcommand
  - Use `<backend>/<id>` instead of `personal/<uuid>` in examples
  - Note that `-o` is subject to approval like stdout fetch
  - Reword guidance: only request needed credentials, never echo secrets;
    agent does not need to coordinate the approval UI flow

  Made-with: Cursor

- ♻️ refactor: remove request_id from CredentialApprovalRequest
  ([`d77a0a7`](https://github.com/thiesgerken/carapace/commit/d77a0a705f2220183bcea8932000ab56048031ac))

  vault_paths already serves as a natural key — duplicate in-flight requests with the same paths cannot occur within a session, so request_id was unnecessary overhead.

  Made-with: Cursor

### 🔧 Configuration


- 🔧 refactor: remove unused _make_credential_eval_cb method
  ([`c839ae6`](https://github.com/thiesgerken/carapace/commit/c839ae6548faf073d94e61e19ec44d8f5d5923ff))

  - Deleted the _make_credential_eval_cb method from SessionEngine as it was no longer needed, streamlining the codebase and improving maintainability.

- 🔧 refactor: update Bitwarden service context and image references
  ([`1ecabe8`](https://github.com/thiesgerken/carapace/commit/1ecabe86de7583644818f300dc170a9c163d0dce))

  - Changed the build context from `bw-serve` to `bitwarden-cli` in `docker-compose.yml`, `ci.yml`, and `release.yml`.
  - Updated documentation to reflect the new image tag for the Bitwarden sidecar in `README.md` and `quickstart.md`.

  This refactor aligns the service configuration with the new directory structure and improves clarity in the setup process.

### Other


- forgot to move
  ([`243cbf8`](https://github.com/thiesgerken/carapace/commit/243cbf8baca06fafc9d24fce76647cc8f67e9255))

- fix bitwarden problems
  ([`5b6e896`](https://github.com/thiesgerken/carapace/commit/5b6e89658fed9a118e6e5c6a1f7224bffd4ef93d))

- 📝 docs: update security and skill activation documentation
  ([`e79068e`](https://github.com/thiesgerken/carapace/commit/e79068ee17fd30d06e745b7af93975a331260402))

  Clarified the evaluation process for the `use_skill` tool, emphasizing that it is not safe-listed and requires sentinel evaluation. Updated the security documentation to reflect the new skill activation guidelines and added a new section on skill creation. Introduced new skills for managing credentials and provided a template for creating skills, including dependency management with `pyproject.toml`.

  Made-with: Cursor

- 📝 docs: migrate credentials docs from plan
  ([`7a54418`](https://github.com/thiesgerken/carapace/commit/7a544182aab66ec347ee7ec281fed373d2be1818))

  Document the implemented credential flow across README, architecture, security, quickstart, and skills docs; add a dedicated credentials guide and remove the obsolete credentials plan.

  Made-with: Cursor

- ✅ test: add unit coverage for Bitwarden credential backend
  ([`d735fcb`](https://github.com/thiesgerken/carapace/commit/d735fcba048d7674d682c8d7be7274848cf44df9))

  Add focused async tests for Bitwarden fetch, metadata, list filtering, and registry wiring using a fake HTTP client so the suite runs without a live bw serve dependency.

  Made-with: Cursor

- 📝 docs: add quickstart guide and .env.example
  ([`da5869e`](https://github.com/thiesgerken/carapace/commit/da5869edf80408b48e063b5614a64a5abfa14ca9))

  Step-by-step Docker Compose setup covering configuration, Matrix integration, credential backends (file + Bitwarden), and personalisation. Condense the README getting-started section to link to the new guide.

  Made-with: Cursor

- add a comment
  ([`95a113b`](https://github.com/thiesgerken/carapace/commit/95a113bee356ee41b2fbc007b9cd8532c0ca2950))

- 📝 docs: tighten credentials SKILL.md wording
  ([`7a9bacd`](https://github.com/thiesgerken/carapace/commit/7a9bacd91201d01ac02c7208439e1e4f699d5d08))

  - Distinguish auto-injected vs on-demand credential flows
  - Remove bare ccred get example that would echo the secret
  - Replace /reset mention with session-scoped approvals

  Made-with: Cursor

- Merge remote-tracking branch 'origin/main' into feature/credentials
  ([`6946114`](https://github.com/thiesgerken/carapace/commit/6946114fb7faa83879aab31bb73de17739b59f92))

- Merge branch 'main' into feature/credentials
  ([`77433bc`](https://github.com/thiesgerken/carapace/commit/77433bc21aa9c2c73d6fc44d98e5e0a5e4b1f941))

### 🔒 Security


- 🔒 feat: enhance Bitwarden backend error handling and request management
  ([`095e68d`](https://github.com/thiesgerken/carapace/commit/095e68d883608277cc819b908cefa44272aa021f))

  - Introduced a new private method `_get` to centralize HTTP GET requests and improve error logging with detailed messages.
  - Updated existing methods to utilize `_get` for fetching passwords, item metadata, and listing items, enhancing code clarity and maintainability.

  Made-with: Cursor

- 🔒 refactor: update credential decision handling in evaluate_credential_with
  ([`69e77d7`](https://github.com/thiesgerken/carapace/commit/69e77d7f2aaa106d1b74c643a44a2c085d61ad8b))

  - Introduced a new variable `cred_decision` to streamline the decision logic for credential access.
  - Replaced the direct assignment of `decision` with `cred_decision` in the CredentialAccessEntry to enhance clarity and maintainability.

  Made-with: Cursor

- 🔒 feat: credential audit entries and approval UI events
  ([`761da61`](https://github.com/thiesgerken/carapace/commit/761da6100083b3e4d28156bd3bbdb8e497d4c0f3))

  - Return CredentialAccessEvaluation from evaluate_credential_with
  - Audit and notify on sandbox credential list; append approval events on
    auto-allowed fetch when the user was not prompted
  - Emit credential_approval events when skills get implicit credential access
  - Wire append_session_events into agent Deps from SessionEngine

  Made-with: Cursor

- 🔒 feat: gate sandbox credential HTTP access through sentinel
  ([`7999717`](https://github.com/thiesgerken/carapace/commit/79997178d153f10e88c1c8f516d0f58ba8439e61))

  Sandbox GET /credentials now runs evaluate_credential_with: sentinel allow/deny with UI detail lines, escalate via shared escalation queue and EscalationResponse (Web, CLI, Matrix). Skill credential injection remains covered by use_skill gating. Removes credential_approval_queue and CredentialApprovalResponse; CredentialApprovalRequest gains request_id.

  Made-with: Cursor

- 🔒 fix: shell-quote paths in file_write and restore carapace.yaml from git
  ([`a84a2e3`](https://github.com/thiesgerken/carapace/commit/a84a2e3b82b425f476d9312ec1b649bf27711bf4))

  file_write now uses shlex.quote by default, preventing shell injection from LLM-provided paths. A quote=False escape hatch preserves $HOME expansion for trusted carapace.yaml file declarations.

  _sync_skill_venv restores carapace.yaml alongside pyproject.toml and uv.lock, preventing the sandbox from tampering with credential or network declarations.

  Made-with: Cursor

## v0.49.1 (2026-04-02)


### 🔧 Configuration


- 🔧 chore: exclude CHANGELOG.md from markdownlint
  ([`8f3b1b0`](https://github.com/thiesgerken/carapace/commit/8f3b1b05a6a69e1e1a4563e148a3c4d8b32eecad))

  - Add .markdownlintignore and pass -p from prek markdownlint-fix hook

  Made-with: Cursor

## v0.49.0 (2026-04-02)


### 🔧 Configuration


- 🔧 chore: update package versions in uv.lock
  ([`549abed`](https://github.com/thiesgerken/carapace/commit/549abed71f50b6e50ccf4ac0b7a1750474fb20e6))

  - Bump ag-ui-protocol from 0.1.14 to 0.1.15
  - Bump aiohttp from 3.13.4 to 3.13.5

  This update includes new source distributions and wheel files for both packages.

### ✨ Features


- ✨ feat: add markdownlint-fix via prek
  ([`50c0ec6`](https://github.com/thiesgerken/carapace/commit/50c0ec670febfaf828d426795cdb2bfa8a517c6e))

  - Configure relaxed .markdownlint.json (focus on auto-fixable issues)
  - Wire igorshubovych/markdownlint-cli v0.48.0 in prek.toml
  - Apply markdownlint autofixes to existing docs

  Made-with: Cursor

## v0.48.4 (2026-04-02)


### 🔧 Configuration


- 🔧 chore: migrate from pre-commit to prek
  ([`3ff7de8`](https://github.com/thiesgerken/carapace/commit/3ff7de8cfcb6b0bf8812886f97af020fce3ce499))

  - Add prek.toml with repo: builtin hooks and ruff-pre-commit
  - Run prek in CI via j178/prek-action
  - Document prek in AGENTS.md; enable Ruff T100 for debugger checks

  Made-with: Cursor

### Other


- work on credential plan
  ([`456e639`](https://github.com/thiesgerken/carapace/commit/456e639d2feaf6a932e6cb428e9551e546930b48))

- 📋 docs: add plan for persistent shell implementation in the agent
  ([`6edd112`](https://github.com/thiesgerken/carapace/commit/6edd1129d2fc0d13b2c8d442e31fb1e3763b62e5))

- 📝 docs: rewrite credential management plan + update skill persistence refs
  ([`b912fe3`](https://github.com/thiesgerken/carapace/commit/b912fe3839b3e272aee0c5e1c57142c390876ae2))

  - Replace push-based CredentialBroker design with pull-based REST endpoint
    (GET /credentials/{vault_path}) that sandbox scripts fetch from on demand
  - Add built-in credentials skill with ccred CLI helper
  - Support auto-injection via carapace.yaml (env_var + file) on skill activation
  - Bundled approval for multiple credentials in one prompt
  - Credential list/search endpoint with tiered gating (list-all vs search)
  - Exposure control (allowlist/blocklist) in vault config
  - Blocking approval flow (no 403 retry loops)
  - UI: session credential visibility + CredentialApprovalCard component
  - Update docs/skills.md and SKILL.md assets: replace save_skill with git push

- 📋 docs: update roadmap with UI improvements and restructured authentication plans; remove Kubernetes enhancements section
  ([`efdb391`](https://github.com/thiesgerken/carapace/commit/efdb391aaed1cf7cdeda2d5c4216a18d1100dc92))

- 📋 docs: add roadmap for planned features and improvements; remove outdated TODO list
  ([`2ebb2c5`](https://github.com/thiesgerken/carapace/commit/2ebb2c5c7a1243e47e137b3d06abf61f6624a689))

## v0.48.3 (2026-03-29)


### 🐛 Bug Fixes


- 🐛 fix: git fetch hangs and unrelated-history merge failures
  ([`0be2168`](https://github.com/thiesgerken/carapace/commit/0be2168cf4be23734f1d8aa457ab50091d8e8e66))

  - Set GIT_TERMINAL_PROMPT=0 on all git subprocess calls so git fails
    immediately instead of blocking on credential prompts.
  - Return combined stdout+stderr from _run() so callers see error
    messages in the output string.
  - Allow unrelated histories when merging from the remote — the local
    bootstrap commit and the remote history may have no common ancestor.

## v0.48.2 (2026-03-29)


### ♻️ Refactoring


- ♻️ refactor: local knowledge repo always uses main branch
  ([`8e2b44e`](https://github.com/thiesgerken/carapace/commit/8e2b44e585dabfc7fbaa5e34160c70180be43301))

  The git.branch config now only controls the remote branch to fetch from and push to. Locally the knowledge repo is always initialised as 'main', and push uses a main:<remote_branch> refspec. Sandboxes see 'main' as the default branch regardless of the remote config.

  Rename GitStore.branch → GitStore.remote_branch to make the distinction explicit. Update docs/git.md accordingly.

## v0.48.1 (2026-03-29)


### 🐛 Bug Fixes


- 🐛 fix: always pull from remote on startup, log git stderr
  ([`0bab482`](https://github.com/thiesgerken/carapace/commit/0bab482bf1e4868a19dbbd6ae9e35230c1ee0292))

  - pull_from_remote() now handles empty local repos by resetting to the
    remote branch instead of skipping the pull entirely.
  - ensure_repo() sets safe.directory so bind-mounted host dirs don't
    trigger git's dubious-ownership check.
  - _run() captures stderr separately and logs it (warning on failure,
    debug on success) instead of merging it into stdout.

### Other


- 🔥 remove: legacy env-var fallbacks for Secret fields
  ([`f96022f`](https://github.com/thiesgerken/carapace/commit/f96022f0023e24628890d527e0bb7a6717a2c449))

  Drop CARAPACE_GIT_TOKEN, CARAPACE_MATRIX_TOKEN, and CARAPACE_MATRIX_PASSWORD environment-variable fallbacks. If no Secret is configured the feature is simply unavailable.

  Add docs/git.md documenting upstream remote setup, branch requirements, first-start behaviour, and sandbox Git workflow.

- 🔥 remove: dead CredentialsConfig class
  ([`b6e7a5e`](https://github.com/thiesgerken/carapace/commit/b6e7a5ea283205ab681c806f4d275cea1f270bda))

  The class and its Config field were never read by application code.

- 📝 docs: document Secret config model and git remote setup
  ([`751823e`](https://github.com/thiesgerken/carapace/commit/751823eb8d3ab6ddbacbdc0f92782694caadea3b))

## v0.48.0 (2026-03-29)


### ✨ Features


- ✨ feat: add Secret model for flexible credential sourcing
  ([`c6fa9b4`](https://github.com/thiesgerken/carapace/commit/c6fa9b4ac65fcc662f0a7c826cf5e03576aded8c))

  Introduce a Secret BaseModel that resolves credentials from a raw value, an environment variable, or a file path. Accepts plain strings as shorthand for raw values. resolve() returns SecretStr and raises ValueError when the configured source is missing.

  Config fields (MatrixChannelConfig.password/token, GitConfig.token) are Secret | None — existing env-var fallbacks are preserved when no Secret is configured.

## v0.47.2 (2026-03-29)


### Other


- another small typing fix
  ([`c048894`](https://github.com/thiesgerken/carapace/commit/c04889455faebe5e0fd6c8cef26d0aa27c3a8631))

### ♻️ Refactoring


- ♻️ refactor: use StatefulSet.list() for typed sandbox listing
  ([`a41ed6d`](https://github.com/thiesgerken/carapace/commit/a41ed6d2ac2f4c14d5f89df360244d1e3b5ecf0f))

  Replace kr8s.asyncio.get() with StatefulSet.list() for proper typing.

## v0.47.1 (2026-03-29)


### 🐛 Bug Fixes


- 🐛 fix: iterate kr8s async generator in list_sandboxes
  ([`ff09539`](https://github.com/thiesgerken/carapace/commit/ff095393b7f3794cc911cec93215c04c6ef92437))

  kr8s.asyncio.get() returns an async generator, not an awaitable list.

### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`9cca306`](https://github.com/thiesgerken/carapace/commit/9cca3063274e8bb32f57053dbdbfd3fd1ec8a0e6))

## v0.47.0 (2026-03-29)


### Other


- 🔥 refactor: remove unused MemoryConfig / MemorySearchConfig
  ([`75db61d`](https://github.com/thiesgerken/carapace/commit/75db61d16796fd2e3bd198645b63fb0794a65175))

  These models were placeholders for a planned vector-search feature that was never implemented. No code reads the config values.

### ✨ Features


- ✨ feat: clean up orphaned sandboxes on server startup
  ([`fe644ff`](https://github.com/thiesgerken/carapace/commit/fe644ff46b4c646b87714c3331a5e3e62a030eb5))

  Add list_sandboxes() to the ContainerRuntime protocol. Docker lists containers by the carapace.managed label; Kubernetes lists StatefulSets by app.kubernetes.io/managed-by=carapace-server.

  At startup the SandboxManager diffs live sandbox resources against sessions on disk and destroys anything that no longer has a matching session directory. Controlled by the new cleanup_orphans_on_startup config flag (default: true, env: CARAPACE_SANDBOX_CLEANUP_ORPHANS_ON_STARTUP).

## v0.46.1 (2026-03-29)


### 🐛 Bug Fixes


- 🐛 fix: destroy sandbox on session delete even after idle suspend
  ([`7fa2678`](https://github.com/thiesgerken/carapace/commit/7fa2678fa7de511599bd1901fd4744d7da0efb7c))

  destroy_session and reset_session only called the runtime when the session had an in-memory entry. After idle downscaling pops the entry, deleting from the UI silently skipped StatefulSet deletion, leaving orphaned resources in Kubernetes.

  Fall back to sandbox_exists() runtime probe when no in-memory state is found, matching the pattern already used by ensure_session.

## v0.46.0 (2026-03-29)


### ✨ Features


- ✨ feat: allow separate priorityClassName for sandbox pods
  ([`92ab9c1`](https://github.com/thiesgerken/carapace/commit/92ab9c1d9b18ce71e070e76ab487bb6dc361a408))

  Add sandbox.priorityClassName to the Helm chart values. When set it overrides the global priorityClassName for sandbox StatefulSets/Pods, letting operators assign a lower priority to sandboxes than to the server and frontend.

## v0.45.0 (2026-03-29)


### ✨ Features


- ✨ feat: add resource limits for sandbox, frontend and backend containers
  ([`9065878`](https://github.com/thiesgerken/carapace/commit/9065878c872ff977a4ea5562cf338be57153f6d6))

  The Helm chart was missing a way to specify CPU/memory requests and limits for sandbox containers. Frontend and backend already had resources blocks in values.yaml and their templates.

  Add sandbox.resources to values.yaml with sensible defaults, pass them as CARAPACE_SANDBOX_K8S_RESOURCE_* env vars to the server, and wire them through SandboxConfig → KubernetesRuntime into both Pod and StatefulSet container specs.

## v0.44.3 (2026-03-29)


### 🐛 Bug Fixes


- 🐛 fix: grant list verb on deployments for kr8s owner-ref lookup
  ([`906d2d4`](https://github.com/thiesgerken/carapace/commit/906d2d4eb8c221ac7bf1ba34381341d287942c67))

  kr8s uses LIST with fieldSelector instead of a direct GET, so the RBAC role needs the list verb in addition to get.

## v0.44.2 (2026-03-29)


### 🐛 Bug Fixes


- 🐛 fix: use subPath for K8s workspace mount and fail on clone error
  ([`53f0361`](https://github.com/thiesgerken/carapace/commit/53f0361f7d547b518bf4d37e38ba100fa63e2a62))

  - Mount PVC at subPath 'workspace' to avoid lost+found polluting /workspace
  - Raise RuntimeError on git clone failure instead of silently continuing

## v0.44.1 (2026-03-29)


### ♻️ Refactoring


- ♻️Merge pull request #58 from thiesgerken/refactor/migrate-to-kr8s
  ([`7f7be5b`](https://github.com/thiesgerken/carapace/commit/7f7be5b971ae4092afd06d91a801699f4cc45db5))

- ♻️ refactor: migrate Kubernetes runtime from official client to kr8s
  ([`7f7be5b`](https://github.com/thiesgerken/carapace/commit/7f7be5b971ae4092afd06d91a801699f4cc45db5))

- ♻️ refactor: migrate Kubernetes runtime from official client to kr8s
  ([`f1550e6`](https://github.com/thiesgerken/carapace/commit/f1550e6d1271ff0395bced6b9e12523a6c36c141))

  Replace the kubernetes Python client with kr8s, a modern async-native typed Kubernetes client. Key changes:

  - All K8s operations are now natively async (no asyncio.to_thread wrappers)
  - Pod/StatefulSet specs built as plain dicts instead of V1* model objects
  - API client lazily initialized via kr8s.asyncio.api()
  - Owner references via dict instead of V1OwnerReference
  - Exceptions: kr8s.NotFoundError/ServerError/ExecError replace ApiException
  - exec uses kr8s CompletedExec (subprocess.run-like API)
  - Tests simplified: no more sys.modules hacking to mock kubernetes package

### 🐛 Bug Fixes


- 🐛 fix: catch ServerError in _get_owner_deployment for resilient owner ref lookup
  ([`5b1eb82`](https://github.com/thiesgerken/carapace/commit/5b1eb820b49ef3bcc1162a54dcda1f13dfba5a8e))

  Applied via @cursor push command

- 🐛 fix: correct return type of _ensure_api to match kr8s.asyncio.api()
  ([`b01eea2`](https://github.com/thiesgerken/carapace/commit/b01eea2a39400153984111f985b71555d982fa95))

- 🐛 fix: eliminate TOCTOU race in delete helpers
  ([`fa565b5`](https://github.com/thiesgerken/carapace/commit/fa565b55f17a05786c0e0ddd192d73c1c4bf951f))

  Use try/except around the delete call instead of check-then-act (exists + delete). The resource could be deleted between the two calls by GC, an operator, or another process.

### Other


- Merge remote-tracking branch 'origin/main' into refactor/migrate-to-kr8s
  ([`b5b0963`](https://github.com/thiesgerken/carapace/commit/b5b0963c2505c4cd03c5715aecc67971c2d253e4))

## v0.44.0 (2026-03-29)


### ✨ Features


- ✨ Merge pull request #57 from thiesgerken/feat/tool-result-exit-code
  ([`1c14b43`](https://github.com/thiesgerken/carapace/commit/1c14b437985abf0aef1caf470e1c2419e2d367b4))

- ✨ Structured tool results with exit codes
  ([`1c14b43`](https://github.com/thiesgerken/carapace/commit/1c14b437985abf0aef1caf470e1c2419e2d367b4))

- ✨ feat: structured tool results with exit codes
  ([`870bdd0`](https://github.com/thiesgerken/carapace/commit/870bdd008222d24250a094f1f9efcad51cd0cfda))

  Introduce ToolResult dataclass (tool, output, exit_code) replacing loose (str, str, int) callback args throughout the tool result pipeline.

  Backend:
  - exec tool passes actual exit code from ExecResult; other sandbox
    tools pass 0 for success, -1 for infrastructure exceptions
  - Catch sandbox exceptions in all tool functions (exec, read, write,
    edit, apply_patch) so errors become tool results instead of crashing
    the agent turn
  - exec_command returns ExecResult instead of plain str
  - ToolResultInfo WS model gains exit_code field
  - Subscriber protocol, engine, server, Matrix channel updated

  Frontend:
  - Tool call badge renders result with red destructive styling when
    exit_code != 0
  - Clear stale tool-call spinners on error, cancel, and WS disconnect
  - exit_code persisted in session events and restored on reload

### 🐛 Bug Fixes


- 🐛 fix: update tests for exec_command and on_tool_result signature changes
  ([`f99e66f`](https://github.com/thiesgerken/carapace/commit/f99e66f862577f383dd49046f57211a1b7e1f369))

  - Fix test_exec_recreate_preserves_domains to check output.output instead of comparing ExecResult to string
  - Update _FakeSubscriber.on_tool_result signature to match SessionSubscriber protocol (accepts ToolResult instead of tool, result)

  Applied via @cursor push command

## v0.43.4 (2026-03-29)


### 🐛 Bug Fixes


- 🐛 fix: clear tool-call spinners on error, cancel, and disconnect
  ([`31ae55a`](https://github.com/thiesgerken/carapace/commit/31ae55a8945ef75e89dd8bd9121e17e168b25e84))

  When an agent turn ends with an error or cancellation, or the WebSocket disconnects, any tool_call messages still showing a loading spinner are now cleared. Previously the global waiting indicator stopped but individual tool badges kept spinning.

## v0.43.3 (2026-03-29)


### 🐛 Bug Fixes


- 🐛 fix: handle 404 in _wait_for_running when pod not yet created
  ([`2c7e633`](https://github.com/thiesgerken/carapace/commit/2c7e633e77da19e928e741a868bc00305b60d046))

  After creating a StatefulSet, the controller may not have created the pod yet when _wait_for_running starts polling. Treat a 404 ApiException as Pending instead of crashing, so the loop retries until the pod appears.

## v0.43.2 (2026-03-29)


### ⬆️ Dependencies


- ⬆️ update python deps
  ([`e269f03`](https://github.com/thiesgerken/carapace/commit/e269f03aac49d76c2fdd0e3eb3e5f4e71ebbd6bc))

## v0.43.1 (2026-03-29)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`ce7a45e`](https://github.com/thiesgerken/carapace/commit/ce7a45e6dd2ee42327fd2784fdcc165839c96850))

## v0.43.0 (2026-03-29)


### ⬆️ Dependencies


- ⬆️ chore: upgrade frontend to Node 24, pnpm, TS 6
  ([`47a5029`](https://github.com/thiesgerken/carapace/commit/47a5029ec2234555943283f595bc2ccd88ab9345))

  Switch package manager from npm to pnpm (via corepack). Upgrade Node base image from 22 to 24, TypeScript to 6.0, ESLint to 10, lucide-react to 1.x, and bump other dev deps.

  Add globals.css.d.ts for TS 6 strict CSS import checking. Update Dockerfile, README, AGENTS.md to reference pnpm.

### ✨ Features


- ✨Merge pull request #56 from thiesgerken/feature/sts
  ([`4624b58`](https://github.com/thiesgerken/carapace/commit/4624b58ca7a441baaef22c65d953d5c1c4e9b54b))

- ✨ Separate RWO PVCs for sessions, use StatefulSets
  ([`4624b58`](https://github.com/thiesgerken/carapace/commit/4624b58ca7a441baaef22c65d953d5c1c4e9b54b))

- ✨ feat: StatefulSet sandboxes with unified runtime abstraction
  ([`272a777`](https://github.com/thiesgerken/carapace/commit/272a777658dfadb57dd9fb25c45c1841ec919856))

  Migrate Kubernetes sandboxes from bare Pods to StatefulSets with per-session PVCs (volumeClaimTemplates, RWO). Idle sessions scale to 0 (PVC retained), resume scales back to 1. PVC cleanup via persistentVolumeClaimRetentionPolicy (K8s 1.27+).

  Introduce a clean sandbox lifecycle protocol on ContainerRuntime (create_sandbox / resume_sandbox / suspend_sandbox / destroy_sandbox) so the SandboxManager no longer branches on Docker vs Kubernetes. Mount-building, host-path rewriting, and workspace dir creation move into DockerRuntime; PVC size, storage class, service account and priority class move into KubernetesRuntime.

  Add /reload slash command for full sandbox reset (delete + fresh clone).

  Helm chart: RBAC for StatefulSets + PVCs, RWX to RWO on shared PVC, new sessionPvc values, env vars for PVC config.

### 🐛 Bug Fixes


- 🐛 fix: stop repeated suspend calls on already-suspended sandboxes
  ([`26b975c`](https://github.com/thiesgerken/carapace/commit/26b975c07138d2e175a445582055c6465e49303a))

  Restore the self._sessions.pop() in cleanup_session so cleanup_idle no longer rediscovers the same idle entries every cycle. Resume after suspend now relies on the sandbox_exists() runtime probe added in the previous commit.

- 🐛 fix: preserve session tracking on suspend and re-attach after restart
  ([`6c6c241`](https://github.com/thiesgerken/carapace/commit/6c6c2414fd899c0c5df7ab4a59de8acad87e5d3b))

  cleanup_session no longer pops the SessionContainer from self._sessions after suspending. This lets ensure_session find the entry and call resume_sandbox instead of create_sandbox (which deletes the existing StatefulSet and its PVC).

  Add sandbox_exists() to the ContainerRuntime protocol so ensure_session can detect orphaned sandboxes after a server restart (self._sessions is empty but the StatefulSet/container still exists in the runtime). When found, the sandbox is re-attached or resumed rather than destroyed and recreated.

## v0.42.6 (2026-03-28)


### 🐛 Bug Fixes


- 🐛 add revisionHistoryLimit to frontend and server deployments
  ([`1c73b40`](https://github.com/thiesgerken/carapace/commit/1c73b40b532f149a608596b86e710674fd60fdd7))

## v0.42.5 (2026-03-28)


### 🐛 Bug Fixes


- 🐛 fix: add safe.directory for /workspace in sandbox image
  ([`299e504`](https://github.com/thiesgerken/carapace/commit/299e504ad2a5d6fbbeca0c985275f231e7717acc))

  Git 2.35.2+ rejects operations when the repo owner differs from the current user. The sandbox runs as root while the PVC workspace dir is owned by UID 999 (server fsGroup), triggering the dubious-ownership error on every git command.

## v0.42.4 (2026-03-27)


### 🐛 Bug Fixes


- 🐛 fix: run sandbox containers as root for package installs
  ([`b75b837`](https://github.com/thiesgerken/carapace/commit/b75b837d49db87ace67c3a98882921d89bd42381))

  Remove run_as_non_root / run_as_user=1000 from the K8s sandbox pod security context so the container can write to /etc/apt, /etc/pip and run apt-get install. Privilege escalation and all capabilities remain blocked. Revert setup-proxy.sh to the simpler root-level config writes.

## v0.42.3 (2026-03-27)


### Other


- Revert "♻️ refactor: defer version commit until after Docker builds succeed"
  ([`5030c00`](https://github.com/thiesgerken/carapace/commit/5030c00d16ff068790af1ee6fbe58186c8ca56ec))

  This reverts commit 2bbc75f069436678dbf3d5d0d34b6ec8f44d8e1c.

- Revert "🐛 fix: disable semantic-release build to avoid dist/ permission error"
  ([`57f2a1e`](https://github.com/thiesgerken/carapace/commit/57f2a1e1654b48e5d11e018fd5287328cad99e31))

  This reverts commit 4cd229b266c73d7e957ee460ab6421a22f07ad48.

- Revert "🐛 fix: stamp version into pyproject.toml before backend Docker build"
  ([`1a7141a`](https://github.com/thiesgerken/carapace/commit/1a7141a17d4d4955fc471e1c89f7e61ddcd1666b))

  This reverts commit 0cc7f973370826938d4f4a7aff003d93d86383e0.

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`53e6959`](https://github.com/thiesgerken/carapace/commit/53e6959274274b447591a43452870f3e0c349554))

## v0.42.2 (2026-03-26)


### 🐛 Bug Fixes


- 🐛 fix: stamp version into pyproject.toml before backend Docker build
  ([`0cc7f97`](https://github.com/thiesgerken/carapace/commit/0cc7f973370826938d4f4a7aff003d93d86383e0))

- 🐛 fix: disable semantic-release build to avoid dist/ permission error
  ([`4cd229b`](https://github.com/thiesgerken/carapace/commit/4cd229b266c73d7e957ee460ab6421a22f07ad48))

  semantic-release's default build writes to dist/ before uv build, causing a PermissionError on overwrite. Disable it since we build explicitly with uv build.

## v0.42.1 (2026-03-26)


### 🐛 Bug Fixes


- 🐛 fix: set fsGroup in server pod for PVC write access
  ([`68244d2`](https://github.com/thiesgerken/carapace/commit/68244d24b230a806b50056eabbfd5a040e2e4851))

  The nonroot user (UID/GID 999) cannot create directories on a freshly mounted PVC owned by root. Adding fsGroup: 999 to the pod security context lets Kubernetes chown mounted volumes to the correct group.

### ♻️ Refactoring


- ♻️ refactor: defer version commit until after Docker builds succeed
  ([`2bbc75f`](https://github.com/thiesgerken/carapace/commit/2bbc75f069436678dbf3d5d0d34b6ec8f44d8e1c))

  Move semantic-release version commit + tag from the first job to the publish step so that if any Docker build fails, no version commit is created. The version job now only computes the next version.

## v0.42.0 (2026-03-26)


### ✨ Features


- ✨Merge pull request #52 from thiesgerken/feat/git-knowledge-store
  ([`086ba39`](https://github.com/thiesgerken/carapace/commit/086ba39cc4301b87b8fbaf1cb2193b6a56c8b301))

- ✨ feat: git-backed knowledge store
  ([`086ba39`](https://github.com/thiesgerken/carapace/commit/086ba39cc4301b87b8fbaf1cb2193b6a56c8b301))

- ✨ feat: dedicated GitPushApprovalRequest with changed files and sentinel explanation
  ([`c8f7d6c`](https://github.com/thiesgerken/carapace/commit/c8f7d6c53233d584b3d3a3295563819aa1dc3343))

  - Split git push escalation out of ProxyApprovalRequest into its own
    GitPushApprovalRequest WS model (ref, explanation, changed_files)
  - New GitPushApprovalCard frontend component with collapsible file list
  - Rename ProxyApprovalResponse → EscalationResponse (shared escalation
    response for both proxy domain and git push)
  - Rename proxy_approval_queue → escalation_queue,
    pending_proxy_approvals → pending_escalations,
    _make_domain_escalation_cb → _make_escalation_cb
  - Extract changed file names from unified diff in evaluate_push_with

- ✨ feat: sentinel push evaluation with UI notifications and escalation
  ([`8062d71`](https://github.com/thiesgerken/carapace/commit/8062d717df3681243d0408170bceb3330e1c1f6b))

  - Add GitPushEntry to action log and 'git_push' kind to audit log.
  - Add evaluate_push_with() security gate (allow/deny/escalate) for
    git pushes, analogous to evaluate_domain_with().
  - Broadcast push decisions to all session subscribers via
    on_git_push_info callback.
  - Add 'kind' field to ProxyApprovalRequest so escalated git pushes
    render as 'Git Push Request' in frontend, CLI, and Matrix.
  - Update docs/security.md and docs/sessions-and-channels.md.

- ✨ feat: auto-push to remote after sandbox push & /push slash command
  ([`060b3b4`](https://github.com/thiesgerken/carapace/commit/060b3b484c1ad5dd84ed96787558caacf0192f3e))

  - Make on_push_success callback async and wire git_store.push_to_remote
    when an external remote is configured.
  - Add /push slash command to manually trigger a push to the remote.

- ✨ feat: set git identity in sandbox containers
  ([`d2cff63`](https://github.com/thiesgerken/carapace/commit/d2cff631f4f03d095de13b74b2383886e9b7edd0))

  Pass GIT_AUTHOR_NAME, GIT_COMMITTER_NAME, GIT_AUTHOR_EMAIL and GIT_COMMITTER_EMAIL env vars so the agent can commit and push without first running git config. The identity is derived from the configurable git.author template (default: 'Carapace Session %s <%s@carapace.local>').

- ✨ feat: add workdir parameter to ContainerRuntime.exec
  ([`e46d1fc`](https://github.com/thiesgerken/carapace/commit/e46d1fc03154826ba7d9615c663d8abf929d6dcd))

  Docker passes it natively to exec_run(); Kubernetes prepends 'cd <dir> &&' since its exec API has no workdir support.

  exec_command and skill venv sync now use workdir=/workspace/knowledge so the agent's cwd is the knowledge repo clone.

- ✨ feat: log container tail on sandbox recreation for troubleshooting
  ([`fd18303`](https://github.com/thiesgerken/carapace/commit/fd183039f66f8a8fe455a7f445b40d22a4d9dda0))

  When a sandbox container is detected as stopped or gone, fetch and log the last 40 lines of its output before spinning up a replacement. Adds a logs() method to the ContainerRuntime protocol with Docker and Kubernetes implementations.

- ✨ feat: git-backed knowledge store
  ([`f76a1be`](https://github.com/thiesgerken/carapace/commit/f76a1bec837b5023a1ced7449cfe3cc3fd7848b0))

  Split data directory into persistent data/ (config, sessions) and knowledge/ (memory, skills, SOUL.md, USER.md, SECURITY.md) backed by a Git repository.

  New modules:
  - git_store.py: async Git CLI wrapper (init, commit, push, pull)
  - git_http.py: Git HTTP handler via git-http-backend CGI on proxy port

  Key changes:
  - Config: CARAPACE_CONFIG env var, data_dir/knowledge_dir/git fields
  - Bootstrap: split into ensure_data_dir() and ensure_knowledge_dir()
  - Agent: removed write tools (write_memory, save_skill, save_workspace_file),
    sandbox uses git commit/push instead
  - Sentinel: added evaluate_push() for pre-receive hook security gating
  - Sandbox: mount knowledge repo as /workspace, git HTTP on proxy port
  - Server: full lifespan rewrite with GitStore init, remote pull, bootstrap
  - Helm: two PVCs (data RWX, knowledge RWO)
  - Dockerfile: added git, jq, curl

### 🐛 Bug Fixes


- 🐛 fix: display ref instead of '?' for git push approvals in CLI
  ([`541f0cc`](https://github.com/thiesgerken/carapace/commit/541f0cc65a34add020baa603d1645787a813cb39))

  Rename _render_proxy_approval_request → _render_escalation_request and read the 'ref' key for git push escalations instead of 'domain'.

- 🐛 fix: auto-deny stale escalations when a duplicate arrives
  ([`a27b6e2`](https://github.com/thiesgerken/carapace/commit/a27b6e2f4e7010acd9b36e5d8eecb79dd5bf73cd))

  When a new escalation for the same kind+ref/domain is created (e.g. agent retries git push after a timeout), the old pending escalation is automatically denied so its approval card resolves in the frontend.

- 🐛 fix: increase exec timeout to 1h and remove agent control
  ([`4d9dbc7`](https://github.com/thiesgerken/carapace/commit/4d9dbc76d2bddbc357810ccde27ec508c8d6d970))

  git push can block indefinitely when the sentinel escalates for user approval. Raise the default exec timeout to 3600s, support timeout=0 (no limit) in both runtimes, and remove the timeout parameter from the agent-facing exec tool.

- 🐛 fix: remove curl response timeout for user approval flow
  ([`7c83003`](https://github.com/thiesgerken/carapace/commit/7c830037a170c873b3eeefa4faff36e8bbb70993))

  The sentinel may escalate pushes for user approval, which can block indefinitely. Replace --max-time with --connect-timeout to still detect a down server without timing out on long approval waits.

- 🐛 fix: persist git push decisions and clear loading indicator
  ([`004d53b`](https://github.com/thiesgerken/carapace/commit/004d53b06918d3a2702c7d074a6c9c65b3d4e9b0))

- 🐛 fix: handle missing session in evaluate-push endpoint
  ([`0a77af9`](https://github.com/thiesgerken/carapace/commit/0a77af982850d65ab460e804ee6f49e029d97ff4))

- 🐛 fix: purge all tracking state on permanent session deletion
  ([`ad22de3`](https://github.com/thiesgerken/carapace/commit/ad22de309c2865a76dd3f5fe77e85b4139acd1cf))

- 🐛 fix: harden pre-receive hook against missing deps and empty stdin
  ([`8c6c9b8`](https://github.com/thiesgerken/carapace/commit/8c6c9b8554b0ab62c01af2ca09bee403bdf81f44))

- 🐛 fix: promote git auth failure logs from debug to warning
  ([`57dc7a5`](https://github.com/thiesgerken/carapace/commit/57dc7a583338a9583b118caa81e96b6d29e980b3))

- 🐛 fix: persist sandbox session tokens across server restarts
  ([`1ee86e0`](https://github.com/thiesgerken/carapace/commit/1ee86e0efe72a1679579af904e8aa2c031287652))

  Save session_id→token mapping to sandbox_tokens.json in the data dir. Tokens are reloaded on startup so existing sandbox containers (with credentials embedded in the git remote URL) can still authenticate.

- 🐛 fix: add debug logging for git auth failures
  ([`61ce299`](https://github.com/thiesgerken/carapace/commit/61ce299150a9ee09449939d53ca3148ddd3d74e8))

  Log specific reason (no header, malformed creds, invalid token) when sandbox git requests return 401.

- 🐛 fix: use TestModel in session tests to avoid requiring API keys in CI
  ([`5e3dc3f`](https://github.com/thiesgerken/carapace/commit/5e3dc3f56b5f9ddb9ec551a0859499c255057a08))

- 🐛 fix: address security and configuration bugs
  ([`c55d421`](https://github.com/thiesgerken/carapace/commit/c55d42128ce667234d0756b645f861a9750a5179))

  - Fix shell error suppression in _sync_skill_venv that masked pyproject.toml restore failures
  - Change default api_port in GitHttpHandler from 8321 (public API) to 8320 (internal API)

  Applied via @cursor push command

- 🐛 fix: address security and configuration bugs
  ([`6ee6347`](https://github.com/thiesgerken/carapace/commit/6ee6347a15417a180accffc5a30390a3e6882ac1))

  - Fix shell error suppression in _sync_skill_venv that masked pyproject.toml restore failures
  - Change default api_port in GitHttpHandler from 8321 (public API) to 8320 (internal API)

- 🐛 fix: handle null SHA on initial branch push in pre-receive hook
  ([`14c18ef`](https://github.com/thiesgerken/carapace/commit/14c18ef17c23eca610ec146ad4692d9b576d5b2f))

- 🐛 fix: remove unused volume mapping for knowledge directory in docker-compose.yml
  ([`75e7277`](https://github.com/thiesgerken/carapace/commit/75e72778ed8bb463e62a7b80ea529ac5c90b6e7f))

- 🐛 fix: use 127.0.0.1 and --fail in pre-receive hook curl call
  ([`8aba398`](https://github.com/thiesgerken/carapace/commit/8aba398ab50dc3bc9816110c660cc682a8355983))

  Co-authored-by: thiesgerken <7550099+thiesgerken@users.noreply.github.com>

  Agent-Logs-Url: https://github.com/thiesgerken/carapace/sessions/db6aa13c-6f79-4a79-8dce-9144ceaaba75

- 🐛 fix: resolve knowledge_dir relative to config file, not CWD
  ([`2a61a07`](https://github.com/thiesgerken/carapace/commit/2a61a078384f3f62cc0eb5e96807328f7b7e9b80))

  Resolving relative to CWD made container deployments fragile — e.g. Docker mounts knowledge at /knowledge but ./knowledge resolved to /app/knowledge. Now uses the same strategy as data_dir: relative to the config file's parent directory.

- 🐛 fix: load SOUL.md, USER.md, AGENTS.md from knowledge_dir
  ([`1dbefab`](https://github.com/thiesgerken/carapace/commit/1dbefabc1213ec7455d8285f015041e08e0f318a))

  These files were moved to the knowledge repo but build_system_prompt() still loaded them from data_dir, which now only holds config.yaml and sessions.

### ♻️ Refactoring


- ♻️ refactor: clone knowledge repo directly into /workspace
  ([`c8e40ba`](https://github.com/thiesgerken/carapace/commit/c8e40ba181e714263b18ac8ef0136ec7b9a2cc3c))

  Instead of /workspace/knowledge/, the git repo is now cloned into /workspace/ (the container workdir). Simplifies paths throughout the agent system prompt, sandbox manager, example skill, and docs.

- ♻️ refactor: clean up naming inconsistencies across escalation pipeline
  ([`0ac7e7e`](https://github.com/thiesgerken/carapace/commit/0ac7e7e0bacdb5156b68854fcda6210e32e1439b))

  - DomainDecision → EscalationDecision (used for both domain and git push)
  - ProxyApprovalRequest → DomainAccessApprovalRequest (names the action, not the mechanism)
  - escalate_to_user(domain, ...) → escalate_to_user(subject, ...)
  - evaluate_domain() → evaluate_domain_access(), prompt label proxy_domain_request → domain_access_request
  - Explicit kind='domain_access' in evaluate_domain_with context dict (was implicit default)
  - proxy_approval event role → domain_access_approval (back-compat for reading old sessions)
  - on_proxy_approval_request → on_domain_access_approval_request subscriber method
  - Renamed proxy-approval-card.tsx → domain-access-approval-card.tsx
  - Added missing on_git_push_approval_request and on_git_push_info to Matrix subscriber
  - Simplified format_domain_escalation (removed kind param, git pushes use dedicated method)

- ♻️ refactor: per-session token files with lazy loading
  ([`53de96c`](https://github.com/thiesgerken/carapace/commit/53de96c3bed3e6811fefc1cfb888ae7f9794c70c))

  - Store sandbox tokens in sessions/{sid}/token instead of a single
    sandbox_tokens.json.
  - Load tokens lazily in _get_or_create_token(): memory → disk → new.
    No bulk scan at startup.
  - cleanup_session only removes the container reference, keeping
    tokens and domain state so the sandbox can be re-created on
    next use.
  - _cleanup_tracking is now only the ensure_session error-path
    rollback.
  - Add 'no silent failures' guideline to AGENTS.md.

- ♻️ refactor: wait for log readiness then exec git clone
  ([`f43388b`](https://github.com/thiesgerken/carapace/commit/f43388b62fc0ce076e7e769c600869c46ec8df07))

  Instead of running git clone inside the container entrypoint and polling for /workspace/knowledge/.git, the container now starts with only setup-proxy.sh + sleep infinity. After 'carapace sandbox ready' appears in the container logs, an exec runs the git clone.

  This gives direct visibility into clone errors (exit code + output) and cleanly separates container readiness from repo setup.

- ♻️ refactor: mount whole workspace dir, clone knowledge repo into subdirectory
  ([`5c8eb1c`](https://github.com/thiesgerken/carapace/commit/5c8eb1c118ccd9285abb12ce6572467cc2e9033e))

  Replace the /workspace/tmp bind mount with a full /workspace/ mount (host: sessions/{sid}/workspace/, k8s: PVC subPath). The knowledge repo is now cloned into /workspace/knowledge/ on first container start; existing clones are left untouched on restart.

  This fixes 'destination path already exists' from git clone (the previous tmp sub-mount caused Docker to pre-create /workspace/) and gives the agent a persistent scratch area outside the git tree.

- ♻️ refactor: make Deps.agent_model required, add ModelType literal
  ([`c5f2729`](https://github.com/thiesgerken/carapace/commit/c5f2729effb009b360865f4a6183055717fd0070))

  - Deps.agent_model is now Model (required, no None)
  - _build_deps resolves fallback eagerly via _resolve_model()
  - create_agent and loop.py use deps.agent_model directly
  - ModelType = Literal['agent', 'sentinel', 'title'] for model commands
  - _apply_model_override model_obj is Model | None (only used for agent)

- ♻️ refactor: replace Any types in Deps with concrete annotations
  ([`d46105e`](https://github.com/thiesgerken/carapace/commit/d46105e59379b28ed005bc65f994e8b97d9b5fac))

  - Deps.sentinel: Sentinel, git_store: GitStore, agent_model: Model | None
  - SessionEngine: git_store typed as GitStore, agent_model as Model | None
  - ActiveSession.agent_model typed as Model | None
  - tests use MagicMock(spec=...) for proper isinstance checks
  - _patch_sentinel() helper for test_session Sentinel class patching

- ♻️ refactor: remove host-side file ops from skill activation
  ([`a1284d4`](https://github.com/thiesgerken/carapace/commit/a1284d409b0c3ca16354f47f6159c50d919a3210))

  - activate_skill no longer copies skill files from knowledge_dir to
    session workspace (git clone already provides them at /workspace)
  - _sync_skill_venv restores trusted pyproject.toml/uv.lock via
    git checkout inside the container instead of shutil.copy2
  - rebuild_skill_venvs checks master knowledge_dir for pyproject.toml
    instead of unmounted session workspace path
  - removed unused shutil import

- ♻️ refactor: reorganize modules into sub-packages
  ([`69cbc0c`](https://github.com/thiesgerken/carapace/commit/69cbc0c6ac51b4cd766dbdd09aa3b2f06d47a187))

  - agent.py + agent_loop.py → agent/{__init__, tools, loop}.py
  - git_http.py + git_store.py → git/{__init__, http, store}.py
  - session.py + session_engine.py + session_manager.py + titler.py
    → session/{__init__, engine, manager, titler}.py
  - Each package re-exports public API from __init__.py
  - All external imports (carapace.session, carapace.agent) still work
  - Deferred titler import promoted to top-level in session/engine.py

- ♻️ refactor: standardise auth to session_id:token Basic Auth
  ([`1e79ce1`](https://github.com/thiesgerken/carapace/commit/1e79ce14c1a5eaf23851cff5c514351785784abf))

  - proxy extracts token from password field (was username)
  - proxy URL uses session_id:token@ format
  - git handler receives pre-authenticated session_id from proxy
  - removed _extract_basic_auth and get_session_by_token from GitHttpHandler
  - manager injects GIT_REPO_URL and clones during sandbox startup
  - git traffic now routes through proxy (removed host.docker.internal bypass)
  - updated tests for new auth contract

- ♻️ refactor: use single PVC for data and knowledge
  ([`bd838c3`](https://github.com/thiesgerken/carapace/commit/bd838c3c682deffd28c5b4cdd8d2f175764b13aa))

  Knowledge directory lives as a subdirectory of the data PVC (/var/lib/carapace/knowledge) — no need for a separate PVC.

### 🔒 Security


- 🔒 fix: escape ref names in pre-receive hook JSON payload
  ([`af672f6`](https://github.com/thiesgerken/carapace/commit/af672f62c35c85b451d726e1261fddc1bacb5b2e))

  Use jq -n with --arg to build the JSON payload instead of shell string interpolation, preventing injection via crafted ref names.

- 🔒 fix: use Path() to validate PATH_INFO against traversal in GitHttpHandler
  ([`54eaee4`](https://github.com/thiesgerken/carapace/commit/54eaee43e03b3dbbfabb758f16dc259d36c9bc73))

  Co-authored-by: thiesgerken <7550099+thiesgerken@users.noreply.github.com>

  Agent-Logs-Url: https://github.com/thiesgerken/carapace/sessions/cc5a4d5f-efd9-42ef-ade5-933dac6420af

- 🔒 refactor: split server into 3-port architecture
  ([`b006e6f`](https://github.com/thiesgerken/carapace/commit/b006e6f21bdab60b40b25919caa1fae7ecb2d011))

  - Public API (8321): REST + WebSocket, Bearer token auth
  - Sandbox API (8322): Git HTTP backend, Basic Auth (session_id:token)
  - Internal API (8320): sentinel callback, loopback only (127.0.0.1)
  - SandboxManager uses sandbox_port for GIT_REPO_URL (was api_port)
  - Pre-receive hook default port updated to 8320
  - Helm chart: add sandboxPort to values, deployment, service, networkpolicy
  - Updated architecture and kubernetes docs for 3-port model

- 🔒 fix: validate PATH_INFO in GitHttpHandler to prevent repo traversal
  ([`8f4f423`](https://github.com/thiesgerken/carapace/commit/8f4f423eb4923835f0d190fbd3a45503d995fe49))

  GIT_PROJECT_ROOT is knowledge_dir.parent, which could be / if knowledge lives at /knowledge. Without validation, git http-backend could serve any git repo on the filesystem.

  Now rejects requests whose PATH_INFO doesn't start with the intended repo name (knowledge_dir.name or knowledge_dir.name.git) with 403.

  Also adds tests for the path validation (forbidden path returns 403, allowed path without .git suffix passes through).

- 🔒 fix: don't bind-mount knowledge repo into sandbox
  ([`0e314ff`](https://github.com/thiesgerken/carapace/commit/0e314ff57e7966f2fbfc594ecec2095b39f15845))

  The sandbox should obtain the knowledge repo via git clone through the Git HTTP handler (port 3128), which enforces the pre-receive hook security gate. Mounting the host repo directly would bypass the sentinel evaluation entirely.

  Also fixes master skill paths to use knowledge_dir instead of data_dir.

### 🔧 Configuration


- 🔧 fix: improve log retrieval error handling with warning level
  ([`e483de1`](https://github.com/thiesgerken/carapace/commit/e483de188762135d0fb921ead895482f72e6fd86))

- 🔧 fix: sync server ports via env vars between Helm and app
  ([`fcce47d`](https://github.com/thiesgerken/carapace/commit/fcce47dc25d1d2778de7b21037b0ce34b02dd77f))

  - ServerConfig now uses BaseSettings with CARAPACE_SERVER_ env prefix,
    supporting CARAPACE_SERVER_PORT, CARAPACE_SERVER_SANDBOX_PORT, etc.
  - Helm deployment template injects port values as env vars so changing
    server.apiPort / sandboxPort / proxyPort in values.yaml automatically
    configures the application without manual config.yaml edits

- 🔧 fix: make API port configurable for pre-receive hook and Helm chart
  ([`a358ade`](https://github.com/thiesgerken/carapace/commit/a358aded04dda7cea245cb5f3480005fd778118d))

  - pre-receive hook uses ${CARAPACE_API_PORT:-8321} instead of hard-coded 8321
  - GitHttpHandler passes CARAPACE_API_PORT in CGI env to git http-backend
  - Helm chart: new server.apiPort / server.proxyPort values
  - all templates reference values instead of hard-coded port numbers

### Other


- enhance post-push success handling with HTTP status and response validation
  ([`a653015`](https://github.com/thiesgerken/carapace/commit/a6530150c5d30e5727e3ea5a8da7b142db8b68a6))

- improve logging
  ([`e274767`](https://github.com/thiesgerken/carapace/commit/e274767d2ea9563d16932b57185cbbef4fe59191))

- 📝 docs: add pre-commit workflow note to AGENTS.md
  ([`116be57`](https://github.com/thiesgerken/carapace/commit/116be57126733efd45e6e31d2e9f3f8572afcf2e))

- Merge remote-tracking branch 'refs/remotes/origin/feat/git-knowledge-store' into feat/git-knowledge-store
  ([`522ed4e`](https://github.com/thiesgerken/carapace/commit/522ed4e9c049e9fba4e81235463ab4eab9a0b757))

- 🔥 refactor: remove config.yaml bootstrapping
  ([`87c99d7`](https://github.com/thiesgerken/carapace/commit/87c99d79bc5d349e781822e89c802b8421addf4b))

  Config() defaults match the bundled asset exactly, so seeding config.yaml on first start adds no value and creates a subtle ordering issue (load_config runs before ensure_data_dir).

- 📝 docs: align architecture.md and memory.md with git-backed knowledge store
  ([`10eb22a`](https://github.com/thiesgerken/carapace/commit/10eb22a1f9a48c4b4769f7f7e8bcb7e3388dea62))

- Merge pull request #53 from thiesgerken/copilot/sub-pr-52
  ([`82d5ebd`](https://github.com/thiesgerken/carapace/commit/82d5ebd8d5a4684602751147599375d0e59b421f))

  Fix PATH_INFO path traversal in GitHttpHandler

- Initial plan
  ([`02f9300`](https://github.com/thiesgerken/carapace/commit/02f93003a04fabc4fe818c5b64ca595d3698cf64))

- Merge pull request #54 from thiesgerken/copilot/sub-pr-52-again
  ([`d6e2944`](https://github.com/thiesgerken/carapace/commit/d6e2944ae9ed254b3f3f866e87424ccc025d0fe0))

  fix: use 127.0.0.1 and --fail in pre-receive hook curl call

- Initial plan
  ([`7922c55`](https://github.com/thiesgerken/carapace/commit/7922c55d5a7d43d8a0f61c6388fb12652220d1b7))

- ignore tmp in .gitignore for workspace
  ([`5c32ce1`](https://github.com/thiesgerken/carapace/commit/5c32ce10e5a72487a1ae90cefc08e727411ff313))

  Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>

- mdlint
  ([`bac496c`](https://github.com/thiesgerken/carapace/commit/bac496c10232dbffc0be535cfae23c23cda7d303))

- ✅ test: add unit tests for GitStore and GitHttpHandler
  ([`e0a57a4`](https://github.com/thiesgerken/carapace/commit/e0a57a40215edd98f8307c903a871854b7d2b2d2))

  35 tests covering:
  - GitStore: author template parsing, repo init, hook install,
    commit (new file, empty, idempotent), remote management, pull/push
  - GitHttpHandler: Basic Auth extraction (valid, missing, wrong scheme,
    empty password, case-insensitive), CGI-to-HTTP conversion, header
    lookup, 401 on unauthenticated/invalid token requests

- 📝 chore: add comment to except ValueError in _host_path
  ([`61a0114`](https://github.com/thiesgerken/carapace/commit/61a011454d39fccbd0188397290b1af444970125))

## v0.41.1 (2026-03-21)


### 🔧 Configuration


- 🔧 config: add custom changelog template with descriptive section headings
  ([`2c237e7`](https://github.com/thiesgerken/carapace/commit/2c237e70b1fe6862859f3b979dc0cf90b825d9e4))

  Map gitmoji to labeled headings (e.g. '### 🐛 Bug Fixes' instead of '### 🐛'). Uses template_dir with a custom CHANGELOG.md.j2 Jinja2 template.

## v0.41.0 (2026-03-21)


### ✨ Features


- ✨Merge pull request #51 from thiesgerken/feature/model-switching
  ([`8239715`](https://github.com/thiesgerken/carapace/commit/823971555ea1275e272953f62c2e1de588503afb))

- ✨ feat: add /model slash command for per-session model switching
  ([`8239715`](https://github.com/thiesgerken/carapace/commit/823971555ea1275e272953f62c2e1de588503afb))

- ✨ feat: add available models list
  ([`39bf195`](https://github.com/thiesgerken/carapace/commit/39bf1958a963613aebdd0fc6da81e499cfcbc5ae))

- ✨ feat: add /model slash command for per-session model switching
  ([`1129d4f`](https://github.com/thiesgerken/carapace/commit/1129d4fd2d2125b4c4e828e1d131ac6dd2392877))

  Support switching agent, sentinel, and title models on the fly within a session via /model [--type agent|sentinel|title] [model | reset]. No args shows all three models in a table. Usage tracking correctly buckets tokens under the actual model used.

### 🐛 Bug Fixes


- 🐛 fix: prevent showing model suggestions if the argument matches an available model
  ([`5e792bd`](https://github.com/thiesgerken/carapace/commit/5e792bd1e5b23452c937d96397520ff2aaab07f0))

- 🐛 fix: add timeout to AsyncClient to make gemini work
  ([`6c0a1c7`](https://github.com/thiesgerken/carapace/commit/6c0a1c77b1f6a8091c0560b5b23f44ee7c97fbb2))

### ♻️ Refactoring


- ♻️ refactor: split /model into /models, /model, /model-sentinel, /model-title
  ([`ccda12b`](https://github.com/thiesgerken/carapace/commit/ccda12b07ead82b903f9abe3638673630ace639b))

  - /models: overview table of all model types with available models
  - /model, /model-sentinel, /model-title: view/set individual models
  - Changing title model triggers automatic title regeneration
  - handle_slash_command is now async to support title regeneration
  - Simplified frontend autocomplete (no more --type flag parsing)

### Other


- Merge remote-tracking branch 'origin/main' into feature/model-switching
  ([`796a358`](https://github.com/thiesgerken/carapace/commit/796a35887a1c7310d0e6ac31095aab99e5671294))

- fix to model autocomplete
  ([`5c80563`](https://github.com/thiesgerken/carapace/commit/5c805634e4f1224c76ef9feb3d749df302d47231))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`a46cfa9`](https://github.com/thiesgerken/carapace/commit/a46cfa93cdadc3d74478096996f92d470ef11e24))

## v0.40.2 (2026-03-21)


### Other


- 📝 docs: convert README architecture diagram to mermaid
  ([`911ad49`](https://github.com/thiesgerken/carapace/commit/911ad49551503ac015d32a4ad145385eb4e1344c))

- 📝 docs: rewrite docs to match actual implementation
  ([`93938cf`](https://github.com/thiesgerken/carapace/commit/93938cf7f5b11d9d7507a0170c5f4f4f8f19f8a9))

  - Rewrite architecture.md, sandbox.md, memory.md, sessions-and-channels.md, skills.md to reflect current codebase
  - Move credentials.md to docs/plans/ (credential broker is mock-only)
  - Create docs/plans/ for future features: memory (vector search, daily logs), channels (cron/heartbeat, E2EE), kubernetes (per-session PVCs, StatefulSets, git-backed storage)
  - Update security.md (audit format JSONL→YAML, fix descriptions)
  - Update kubernetes.md (ASCII→mermaid diagram, add plans link)
  - Update README.md: fix architecture description, remove aspirational features, update status and tech stack

### 🐛 Bug Fixes


- 🐛 fix: resolve ESLint errors in use-websocket hook
  ([`762a216`](https://github.com/thiesgerken/carapace/commit/762a21670d6ac2f6fe407363d53f388a613fb7a5))

## v0.40.1 (2026-03-21)


### ⬆️ Dependencies


- ⬆️ upgrade ruff-pre-commit to v0.15.7
  ([`e765c54`](https://github.com/thiesgerken/carapace/commit/e765c543ce87a6fcd18405516ce4759d9463fcb0))

- ⬆️ upgrade deps and fix a small linter issue
  ([`075cee7`](https://github.com/thiesgerken/carapace/commit/075cee7685ba12d6dbbe48b3664421948ed11ac6))

### 🐛 Bug Fixes


- 🐛 fix: skip autofocus on mobile to prevent hidden input
  ([`381766d`](https://github.com/thiesgerken/carapace/commit/381766de632ede1faed08da2602526874aae8654))

## v0.40.0 (2026-03-20)


### ✨ Features


- ✨ support other model providers as well
  ([`15a61ad`](https://github.com/thiesgerken/carapace/commit/15a61ad9e2f351bc8bd140dc716e06d2519af891))

### Other


- 💚 hardcode package name
  ([`87d6730`](https://github.com/thiesgerken/carapace/commit/87d67303bb3c05574a02e0f21145f540afb38b20))

- 💚 skip release on main if not needed
  ([`9b2e31a`](https://github.com/thiesgerken/carapace/commit/9b2e31ab71423abdd0209ac85fa432784c623a24))

## v0.39.1 (2026-03-18)


### 💄 UI/UX


- 💄 fix: improve mobile UX (viewport, touch targets, safe areas, input zoom)
  ([`5021676`](https://github.com/thiesgerken/carapace/commit/50216766b6afea81e8ce0e025df39bb056809dca))

### Other


- relock
  ([`93855bd`](https://github.com/thiesgerken/carapace/commit/93855bd5a8061e4515ed7a08f950b83d159467b6))

## v0.39.0 (2026-03-18)


### 🐛 Bug Fixes


- 🐛 fix: ensure uv is installed in build command
  ([`250f607`](https://github.com/thiesgerken/carapace/commit/250f60775d62fb62863d932a48399554e49d239e))

- 🐛 fix: show usage bar immediately on session load
  ([`67234c3`](https://github.com/thiesgerken/carapace/commit/67234c389f9fb99389c02ff603ad3a15cbfda167))

- 🐛 fix: only auto-scroll chat when already at bottom
  ([`fd73fa6`](https://github.com/thiesgerken/carapace/commit/fd73fa6da232db99608270ceb54a30e860b86170))

### ✨ Features


- ✨ feat: swipe to open/close sidebar drawer on mobile
  ([`e6e00de`](https://github.com/thiesgerken/carapace/commit/e6e00de80738d0af0a8a98124901a150c33c8c47))

- ✨ revamp Dockerfile for backend as non-root
  ([`4fe876f`](https://github.com/thiesgerken/carapace/commit/4fe876f7335e1971ea054c5f0a2be2910164242f))

### 👷 CI/Build


- 👷 ci: sync uv.lock in build_command & expand patch_tags
  ([`106308c`](https://github.com/thiesgerken/carapace/commit/106308ce061df8b18ef6bdb689f7149ccd01c637))

## v0.38.5 (2026-03-16)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`8d2c3b7`](https://github.com/thiesgerken/carapace/commit/8d2c3b76a1c6efd360d3a7988894cfd7484631f4))

## v0.38.4 (2026-03-16)


### 🐛 Bug Fixes


- 🐛 fix: remove dead code in DockerRuntime
  ([`bef59a2`](https://github.com/thiesgerken/carapace/commit/bef59a20768e2f340556644269979911a32f0dc9))

  - Remove unused build_image() method (never called)
  - Rename get_network_gateway → _get_network_gateway (internal helper)
  - Remove unused 'import io'

- 🐛 update ignore patterns to exclude node_modules during skill save
  ([`d5dd419`](https://github.com/thiesgerken/carapace/commit/d5dd41925eae71d8961c77f17abb4145615be638))

### 💄 UI/UX


- 💄 improve exception formatting in UI
  ([`377fd85`](https://github.com/thiesgerken/carapace/commit/377fd85611d92a2197ef855a4640eecd1c2c2428))

## v0.38.3 (2026-03-16)


### 🐛 Bug Fixes


- 🐛 fix tool call arg type assertion
  ([`e6f2778`](https://github.com/thiesgerken/carapace/commit/e6f27789aa1859f1413afa60399ded003c83b57a))

## v0.38.2 (2026-03-16)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`78ddea0`](https://github.com/thiesgerken/carapace/commit/78ddea0947bf8433748493f2434ecc721c052d66))

## v0.38.1 (2026-03-16)


### Other


- 📋 less asking for git commit
  ([`0584fd2`](https://github.com/thiesgerken/carapace/commit/0584fd24e76c943f0213798de9aaca9274fab002))

### 🐛 Bug Fixes


- 🐛 fix: persist user message to history on failed agent turns
  ([`107abfe`](https://github.com/thiesgerken/carapace/commit/107abfefd6d7993721ee000b9e0e50c0354a21ab))

  When run_agent_turn raises an exception (e.g. failed tool call), the message history was never saved. The next turn loaded stale history, losing both the user message and any context from the failed turn.

  Add _save_user_message_on_failure() which appends the user's ModelRequest to the persisted history in both CancelledError and Exception handlers so the agent retains context across failures.

- 🐛 improve error handling for crashing sandbox
  ([`7e8bcf4`](https://github.com/thiesgerken/carapace/commit/7e8bcf456b7fd40ebf81cfc26b73e9122dfa8800))

## v0.38.0 (2026-03-16)


### ✨ Features


- ✨ feat: make workspace files editable copies with save_workspace_file tool
  ([`267c021`](https://github.com/thiesgerken/carapace/commit/267c021d34f9f88c3794ab0c767afd14a1fcaba5))

  Replace read-only bind mounts of AGENTS.md, SOUL.md, USER.md, and SECURITY.md with writable copies in the session workspace. The agent can now edit these files in the sandbox and persist changes back to the main data directory via the new save_workspace_file tool.

  - Sentinel reads SECURITY.md from disk on every evaluation (dynamic
    instructions callable) so policy changes take effect immediately
  - SessionEngine no longer threads security_md through the stack
  - save_workspace_file is security-gated and restricted to the four
    known workspace files
  - SECURITY.md updated to instruct sentinel to always escalate saves

## v0.37.0 (2026-03-16)


### ✨ Features


- ✨ improve handling of SECURITY.md (reload often) + add approvals to events + remove load_security_md
  ([`e94fd40`](https://github.com/thiesgerken/carapace/commit/e94fd4061aebacb5eff8dad34755189051e55344))

- ✨ feat: add CARAPACE_RESET_ASSETS flag to overwrite bundled assets on startup
  ([`65adde5`](https://github.com/thiesgerken/carapace/commit/65adde5f7a234f68877daf0de89e2988f8fc4caf))

  When set to a truthy value (1/true/yes), ensure_data_dir() overwrites SECURITY.md, CORE.md, and bundled skills with the versions shipped in the container image. User-owned files (SOUL.md, USER.md, config.yaml) are never overwritten — only seeded when missing.

  - bootstrap.py: respect CARAPACE_RESET_ASSETS env var
  - docker-compose.yml: pass through the new env var
  - Helm chart: new resetAssets value (default false)

## v0.36.0 (2026-03-16)


### ✨ Features


- ✨ improve proxy setup
  ([`dde455a`](https://github.com/thiesgerken/carapace/commit/dde455a701cba5a94fd464d6ef7237e44ce58a2c))

### 🐛 Bug Fixes


- 🐛 improve uv documentation for agent
  ([`01a3fd1`](https://github.com/thiesgerken/carapace/commit/01a3fd17deb5f258a77f3e854964961c2295da59))

## v0.35.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛remove dead code
  ([`53543fe`](https://github.com/thiesgerken/carapace/commit/53543fe8be48ecf8567c3c1d3356c0d23c161f1a))

## v0.35.0 (2026-03-15)


### ✨ Features


- ✨ feat: stream LLM responses to CLI, web UI, and Matrix
  ([`e00f979`](https://github.com/thiesgerken/carapace/commit/e00f979afe6bb4f286f3353ca254cd2b916d823e))

  Use Pydantic AI's event_stream_handler to emit token chunks during agent.run() without changing the existing approval/deferred-tools loop. Chunks are broadcast via the subscriber protocol and replaced by the authoritative Done message on completion.

  - CLI: progressive Markdown rendering via rich.Live
  - Web UI: streaming message kind replaced atomically on done
  - Matrix: single notice edited in-place every 200 chars, then
    replaced with final m.text on done

## v0.34.1 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`18ff1cf`](https://github.com/thiesgerken/carapace/commit/18ff1cf74ca91cad072cb9f5bf0d59fb76e84bd1))

## v0.34.0 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: remove unnecessary packages from Dockerfile
  ([`7ea00f3`](https://github.com/thiesgerken/carapace/commit/7ea00f33ac6cc849a69b32676c3417faa551cda1))

### ✨ Features


- ✨ feat: switch sandbox image to python:3.14-slim-trixie
  ([`031837a`](https://github.com/thiesgerken/carapace/commit/031837aed52d59504c41a5cec5d469e60cf3c641))

  Share the base image with the server container so layers are deduplicated on disk. Replace apk with apt-get, copy uv binary from the official image, and drop redundant python3/py3-pip/ ca-certificates packages.

## v0.33.4 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: chmod writable sandbox dirs instead of chown (K8s storage compat)
  ([`bf924de`](https://github.com/thiesgerken/carapace/commit/bf924deec7a6a25c08eaf4daa072e63849bcdb8e))

## v0.33.3 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`bfff432`](https://github.com/thiesgerken/carapace/commit/bfff432f5533d710c021b11870f41d447f011daf))

## v0.33.2 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: prevent mobile header from scrolling away in long conversations
  ([`71e155d`](https://github.com/thiesgerken/carapace/commit/71e155d12e062844f9b8e2770c0d594ae6e34583))

  Replace h-full with flex-1 min-h-0 on ChatView root so the messages area properly constrains to remaining viewport height after the mobile header, enabling overflow-y-auto instead of growing past the screen.

- 🐛 fix: add initContainer to chown writable PVC dirs in K8s sandbox pods
  ([`2452b4a`](https://github.com/thiesgerken/carapace/commit/2452b4a42cfc5e6b0b378eee649e0f5dc018df3c))

## v0.33.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 make sure to refetch matrix token if user_id changes + accept pending invites at startup
  ([`eb553c9`](https://github.com/thiesgerken/carapace/commit/eb553c979c02f94ac70e15a85f48950f19ca0e7e))

## v0.33.0 (2026-03-15)


### ✨ Features


- ✨ feat: log startup message in sandbox containers before sleep
  ([`3059171`](https://github.com/thiesgerken/carapace/commit/30591715528dff44b126a9a8a35399f7efb47110))

## v0.32.3 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: update k8s_owner_ref to True for sandbox pods
  ([`6c8c72d`](https://github.com/thiesgerken/carapace/commit/6c8c72dd84d0fe85aa39f9aee551c8fd9b0d42f6))

## v0.32.2 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: add ArgoCD tracking annotation to sandbox pods for app discovery
  ([`b158fd2`](https://github.com/thiesgerken/carapace/commit/b158fd2b9c560c4615fc1811f90f12b046688cc0))

## v0.32.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛💚 update pre-commit and actions
  ([`fd4a265`](https://github.com/thiesgerken/carapace/commit/fd4a2656728fd77106d437bfe44bbe4b954731ca))

## v0.32.0 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`0249cb0`](https://github.com/thiesgerken/carapace/commit/0249cb007d705636301b3cf1e858af6816936692))

## v0.31.0 (2026-03-15)


### ✨ Features


- ✨ feat: make sandbox pod ownerReference configurable (default off)
  ([`7219c8f`](https://github.com/thiesgerken/carapace/commit/7219c8f5f2885d1e6e60917b9bb2f1eb8efeda8f))

- ✨ better url guessing in ui
  ([`2bece2e`](https://github.com/thiesgerken/carapace/commit/2bece2e77749251d18309ed167b7a459ec3fdb2a))

## v0.30.2 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: use Always restart policy for sandbox pods and rename to carapace-sandbox-*
  ([`d0c3335`](https://github.com/thiesgerken/carapace/commit/d0c33351ae5746ff6fecc2f9ba6a71d12468d88c))

### Other


- 📝 docs: add NetworkPolicy security warnings to Kubernetes docs
  ([`373634b`](https://github.com/thiesgerken/carapace/commit/373634bab2010360efee5d4ce0c5bf1ba9025aac))

## v0.30.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: move kubernetes from optional to regular dependency
  ([`a0a8d94`](https://github.com/thiesgerken/carapace/commit/a0a8d942fbf8baf052ba13d6a0b770de04f58ecf))

## v0.30.0 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`97d9cb6`](https://github.com/thiesgerken/carapace/commit/97d9cb6dbbf7779613362eaafee95f8b93b08182))

## v0.29.0 (2026-03-15)


### ✨ Features


- ✨ feat(chart): support config.yaml via ConfigMap
  ([`6c19915`](https://github.com/thiesgerken/carapace/commit/6c19915f89ed9177dca024d41570af82f57fb574))

- ✨ feat: replace auto-generated token with CARAPACE_TOKEN env var
  ([`0f45c40`](https://github.com/thiesgerken/carapace/commit/0f45c40b5af2346a6b90a2f845e227a3b79fa7cd))

## v0.28.1 (2026-03-15)


### 🐛 Bug Fixes


- 🐛 fix: use version_pattern for Chart.yaml version bumping and override helm package version
  ([`df66025`](https://github.com/thiesgerken/carapace/commit/df6602514ae6578b81d846fe1e1efb95d1f29287))

### Other


- 📝 docs: add Helm chart install command to release notes
  ([`2cf0c30`](https://github.com/thiesgerken/carapace/commit/2cf0c304278727c437c3293c4d701f0c62efb967))

## v0.28.0 (2026-03-15)


### ✨ Features


- ✨ feat: Gateway API HTTPRoute, OCI chart publishing, PVC finalizers, default resources
  ([`7b4dba6`](https://github.com/thiesgerken/carapace/commit/7b4dba6f3a5984dfc6cba3a43dc7953f79472d1b))

## v0.27.0 (2026-03-15)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`9c3e094`](https://github.com/thiesgerken/carapace/commit/9c3e0941f6915cee642ea52c47ca953d3f22f42b))

## v0.26.0 (2026-03-15)


### ✨ Features


- ✨ feat: mount all API endpoints under /api prefix
  ([`d660c9b`](https://github.com/thiesgerken/carapace/commit/d660c9b71b4376355ceadf5b612e7562a6df00c7))

- ✨ feat: add Helm chart for Kubernetes deployment
  ([`b9ef7cd`](https://github.com/thiesgerken/carapace/commit/b9ef7cdc5bb146ba63bab2c34932673c24b0700f))

## v0.25.3 (2026-03-14)


### 🐛 Bug Fixes


- 🐛 no need to add that to soul.md
  ([`7fc25bb`](https://github.com/thiesgerken/carapace/commit/7fc25bb429442db6ba64b3fbd71ec5916b91e66c))

### Other


- 📝 docs: clarify that the agent has internet access (security-gated)
  ([`e4b550b`](https://github.com/thiesgerken/carapace/commit/e4b550b0456d14e2e51d9c82663a2f403cfe22a0))

## v0.25.2 (2026-03-14)


### 🐛 Bug Fixes


- 🐛 fix linter issues due to missing stuff in the protocol
  ([`1e8c1eb`](https://github.com/thiesgerken/carapace/commit/1e8c1eba6c2dabb7917df9524eaa33aa6d979d1c))

### Other


- runtime stuff
  ([`332a43d`](https://github.com/thiesgerken/carapace/commit/332a43d14aca93c2636fe0a01c1e02cd918876aa))

- no sandbox versioning automatically
  ([`fcc65ef`](https://github.com/thiesgerken/carapace/commit/fcc65efcd318cc7d1085f37cd57f0b8bf8ced15f))

## v0.25.1 (2026-03-14)


### 🐛 Bug Fixes


- 🐛 fix cors mounting
  ([`18af792`](https://github.com/thiesgerken/carapace/commit/18af792ec2d3f57fa5142283ce370c687cab55c5))

- 🐛 fix usagetracker import issues
  ([`07979a6`](https://github.com/thiesgerken/carapace/commit/07979a685d099106470fc1704b696f261afcfe90))

### Other


- lint
  ([`f4262a9`](https://github.com/thiesgerken/carapace/commit/f4262a91c59261825fffa6e2a53c8e046ec6c9d7))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`49694a9`](https://github.com/thiesgerken/carapace/commit/49694a98a7e5ced9e60f15f5d4ab8738e5e64f2c))

## v0.25.0 (2026-03-14)


### 💄 UI/UX


- 💄 lint issues
  ([`c3673b5`](https://github.com/thiesgerken/carapace/commit/c3673b5f7b76405b1664659be549757725513a0e))

### ✨ Features


- ✨ feat: add Kubernetes sandbox runtime and deployment manifests
  ([`547855b`](https://github.com/thiesgerken/carapace/commit/547855b50044745f98def3af38666d53be9a8983))

  - KubernetesRuntime implements ContainerRuntime protocol using k8s API
  - Sandbox pods use PVC subPaths, ownerReferences, NetworkPolicy isolation
  - Runtime selection via config.sandbox.runtime (docker|kubernetes)
  - Kustomize manifests in k8s/ (namespace, PVC, RBAC, deployments, ingress)
  - Full deployment guide at docs/kubernetes.md
  - 19 unit tests with mocked k8s API
  - Add pytest-asyncio with asyncio_mode=auto

### Other


- 📋 update TODO.md: refine Sandbox/Docker and Channels sections, remove outdated tasks
  ([`932c985`](https://github.com/thiesgerken/carapace/commit/932c9851c97bad80c7a22c2e7abdf8073417fe15))

## v0.24.0 (2026-03-14)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`d733ba2`](https://github.com/thiesgerken/carapace/commit/d733ba2f6206245e4a457ca2d6d39693bab36956))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`7959a5e`](https://github.com/thiesgerken/carapace/commit/7959a5e710c1839a01b4af71a11f29297127460b))

## v0.23.0 (2026-03-14)


### ✨ Features


- ✨ feat: build skill venvs inside session container
  ([`b6cab4f`](https://github.com/thiesgerken/carapace/commit/b6cab4f2a76f8b35c5d2fcb38de98cd01eaf22f8))

  Replace the ephemeral build container (_build_skill_venv with network=None) with uv sync executed inside the session's own sandbox container. A per-session exec lock serializes all container commands; the proxy bypass flag is set/cleared atomically under that lock so no concurrent command can exploit the window.

  - Add per-session asyncio.Lock for exec serialization
  - Proxy bypass (wildcard "*") scoped to locked _exec calls only
  - _sync_skill_venv copies trusted pyproject.toml/uv.lock from
    master before building, closing TOCTOU tampering
  - Persist activated_skills in SessionState (survives restarts)
  - Rebuild venvs automatically on container recreation
  - Re-sync venv after save_skill using trusted master deps
  - Remove ephemeral build container code (K8s-incompatible)

- ✨ feat: validate sandbox image at startup, restructure README quickstart
  ([`29cf9eb`](https://github.com/thiesgerken/carapace/commit/29cf9ebf7744e4aa0533a8d77e19b5bb1eeb8f74))

  - Add image_exists() to DockerRuntime
  - Server exits with clear error if sandbox image is missing
  - Split Getting Started into Docker Compose deployment and development setup
  - Add Docker to prerequisites, document 'docker compose build sandbox'

### Other


- 📋 update skills.md, remove mentions of skill dockerfiles
  ([`af9923a`](https://github.com/thiesgerken/carapace/commit/af9923a2ff71f1f9e307a44ff178f816f277fbf3))

- fix CI
  ([`5e26f54`](https://github.com/thiesgerken/carapace/commit/5e26f5438773957df27ff34023060ef479933b6d))

- 📝 docs: reorder README — demo first, dev setup last
  ([`908ce2f`](https://github.com/thiesgerken/carapace/commit/908ce2f979c0593b5235545e12b0bbb9668d7c13))

- 📝 docs: add commit-before-asking convention to AGENTS.md
  ([`3ce548e`](https://github.com/thiesgerken/carapace/commit/3ce548e0d3122781961961a17ecf11f0592ebc0c))

### 🐛 Bug Fixes


- 🐛💚 restructure release workflow to build images before creating release
  ([`f746f04`](https://github.com/thiesgerken/carapace/commit/f746f044b91e2a6fc432de3eecc13e95f038db1c))

  - Split into: version → docker builds (parallel) → publish
  - Version step uses --no-vcs-release to defer GitHub Release creation
  - Publish step creates release with wheels + docker pull commands in one shot
  - No more patching release notes after the fact

## v0.22.0 (2026-03-14)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`2966b0d`](https://github.com/thiesgerken/carapace/commit/2966b0de7d9cb61aae9e0622a1c555ebb2581ecc))

## v0.21.0 (2026-03-14)


### ✨ Features


- ✨ feat: add OCI labels, sandbox version tracking, and docker pull commands in release notes
  ([`cf6d200`](https://github.com/thiesgerken/carapace/commit/cf6d2001332efc6b44b1760f4c72a766bdecaec0))

  - Add docker/metadata-action to all image builds for proper GHCR linking
  - Add update-release job to append docker pull commands to release notes
  - Add _SANDBOX_IMAGE_VERSION to models.py, managed by semantic-release
  - Default sandbox base_image now includes version tag instead of :latest

- ✨move sandbox Dockerfile out of backend assets, remove on-demand build
  ([`a72d34e`](https://github.com/thiesgerken/carapace/commit/a72d34e601898acb07b6be3ab8f8772a4c963d1b))

  - Move src/carapace/assets/Dockerfile → sandbox/Dockerfile
  - Remove get_sandbox_dockerfile() from bootstrap.py
  - Remove build_image() call and _BUILTIN_SANDBOX_IMAGE from server.py
  - Change SandboxConfig.base_image default to 'carapace-sandbox:latest'
  - Add build-only sandbox service to docker-compose.yml (profiles: build)
  - Add docker-sandbox CI/release jobs to build and push the image

### Other


- igns plans
  ([`d0c8b30`](https://github.com/thiesgerken/carapace/commit/d0c8b307ab8b9d3f4e3e312b0efbd2a07f311e58))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`7ece752`](https://github.com/thiesgerken/carapace/commit/7ece752ec76ef05a1a248b2dc0da4351359001d3))

### ⚡ Performance


- ⚡ perf: switch append_events and write_audit to append-only YAML
  ([`95ee976`](https://github.com/thiesgerken/carapace/commit/95ee976dc79f39a0b7286895309499046d3133ad))

### ♻️ Refactoring


- ♻️ refactor: split shared approval queue into typed tool/proxy queues
  ([`f928781`](https://github.com/thiesgerken/carapace/commit/f92878180d551c8ca73991fe4e4f11e116897c45))

- ♻️ refactor: wire security callbacks at session activation, not per-turn
  ([`8523ce3`](https://github.com/thiesgerken/carapace/commit/8523ce39ce62ab553829d19ce7aff75a2e2aea2f))

- ♻️ refactor: replace global security dicts with dependency injection
  ([`74c5c90`](https://github.com/thiesgerken/carapace/commit/74c5c90547f87d2d086f33f22e3116d875f8cd9b))

- ♻️ refactor: split session.py into session_manager.py and session_engine.py
  ([`6c6a604`](https://github.com/thiesgerken/carapace/commit/6c6a604dbb09cae74c589b09d6a780e82b16319e))

  - session_manager.py: SessionManager (pure file I/O, no async)
  - session_engine.py: SessionSubscriber, ActiveSession, SessionEngine (lifecycle, orchestration)
  - session.py: backward-compatible re-export shim
  - Update test mock targets to carapace.session_engine.Sentinel

## v0.20.0 (2026-03-14)


### 🔒 Security


- 🔒 security: make CORS origins configurable, default to localhost:3000
  ([`23d5247`](https://github.com/thiesgerken/carapace/commit/23d5247e0007d3ecb9bc4137b20211c21fc8664f))

  - Add cors_origins field to ServerConfig (default: ["http://localhost:3000"])
  - Move CORS middleware setup into lifespan so it reads from config
  - Replaces previous allow_origins=["*"]

### ♻️ Refactoring


- ♻️ refactor: move SLASH_COMMANDS to ws_models, eliminate all deferred imports
  ([`8ad0990`](https://github.com/thiesgerken/carapace/commit/8ad09900515d03b798e0b57474910b28c890ed95))

  - Move _SLASH_COMMANDS from server.py to ws_models.py as SLASH_COMMANDS
  - Hoist deferred imports to module level in session.py (MemoryStore, run_agent_turn, SLASH_COMMANDS)
  - Hoist deferred imports to module level in commands.py (MemoryStore, UserVouchedEntry)
  - No circular dependencies existed — the deferred imports were unnecessary

- ♻️ refactor: DockerRuntime explicitly inherits ContainerRuntime Protocol
  ([`ff0f471`](https://github.com/thiesgerken/carapace/commit/ff0f4718163d1c66385ca8db14035287133c39d7))

- ♻️ refactor: remove legacy Matrix mode, extract _resolve_pending helper
  ([`c7fbed2`](https://github.com/thiesgerken/carapace/commit/c7fbed20302f656ba8a15c703d87329def1ba57c))

  - Remove dual code paths (engine vs standalone) from MatrixChannel
  - Make engine parameter required
  - Delete legacy-only methods: _run_turn, _run_turn_locked, _keep_typing, _build_deps, _room_lock
  - Extract _resolve_pending() to deduplicate approve/deny slash commands
  - Update all Matrix tests to use mock SessionEngine
  - Net: -220 lines

### Other


- 🔥 cleanup: delete dead _resolve_path and its tests
  ([`a52ac7a`](https://github.com/thiesgerken/carapace/commit/a52ac7a44eb1c26dd2c420bce2d88507065f27af))

- 📝 docs: clarify stdlib logging import in server.py
  ([`d0a4140`](https://github.com/thiesgerken/carapace/commit/d0a4140c7b229d05babce9377c817d42e41280c7))

- 🏷️ types: HistoryMessage.role as Literal instead of plain str
  ([`31ea104`](https://github.com/thiesgerken/carapace/commit/31ea104433a0f07a0c24580a43f5cb6d0774c8a5))

- 📝 docs: add deferred-import ban to coding guidelines
  ([`6c5d7be`](https://github.com/thiesgerken/carapace/commit/6c5d7be834c3ffec61a4ac115ba259477b03fcda))

### 🔧 Configuration


- 🔧 style: add missing future annotations to runtime.py
  ([`9b41830`](https://github.com/thiesgerken/carapace/commit/9b41830b84ff7e42d77b4ad27d1c28beb1dc4890))

### ✨ Features


- ✨ feat: render Matrix /usage report as Markdown tables
  ([`815fc9f`](https://github.com/thiesgerken/carapace/commit/815fc9fc366899124b1317b04333cd1b8a0f34f8))

### 🐛 Bug Fixes


- 🐛 fix: convert cost string to float before formatting in Matrix /usage command
  ([`011e68e`](https://github.com/thiesgerken/carapace/commit/011e68e09fa3706ce5d0a0d0ae07b5a7d2fb6c1d))

## v0.19.1 (2026-03-14)


### 🐛 Bug Fixes


- 🐛 fix: echo slash commands as user_message so they appear in the UI
  ([`f29a715`](https://github.com/thiesgerken/carapace/commit/f29a7157c7c3d8c27a8108eb6e6511e5106123cf))

## v0.19.0 (2026-03-14)


### ✨ Features


- ✨ refactor session handling
  ([`d07cd03`](https://github.com/thiesgerken/carapace/commit/d07cd0370f0567e4aec2164e09070a5cd2bb3fcf))

- ✨ refactor session handling
  ([`d07cd03`](https://github.com/thiesgerken/carapace/commit/d07cd0370f0567e4aec2164e09070a5cd2bb3fcf))

### 🐛 Bug Fixes


- 🐛 remove bad session / security fallbacks
  ([`d07cd03`](https://github.com/thiesgerken/carapace/commit/d07cd0370f0567e4aec2164e09070a5cd2bb3fcf))

  * avoid double websocket subs

- 🐛 fix read method to check for file existence correctly
  ([`d07cd03`](https://github.com/thiesgerken/carapace/commit/d07cd0370f0567e4aec2164e09070a5cd2bb3fcf))

  * ca certs in sandbox

  * fix bugs due to refactor

  * more tests

  * play with matrix verbosity

  * fix valueerror

  * fix typing

  * fix tests without anthropic key

### ♻️ Refactoring


- ♻️ refactor matrix.py into multiple files
  ([`d07cd03`](https://github.com/thiesgerken/carapace/commit/d07cd0370f0567e4aec2164e09070a5cd2bb3fcf))

  * adjust style guide

  * fix typing issues

## v0.18.4 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 fix tests
  ([`e2c059b`](https://github.com/thiesgerken/carapace/commit/e2c059b919274089c7b06e9fce229fab0b0241a2))

## v0.18.3 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 focus textarea on mount and add title attribute for session display
  ([`e447382`](https://github.com/thiesgerken/carapace/commit/e4473822577c1e27dd01aa1f04452109627fd0ef))

## v0.18.2 (2026-03-08)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`16346e8`](https://github.com/thiesgerken/carapace/commit/16346e8139abf3a787bdf4ab742d1f122bcf7b3e))

## v0.18.1 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 fix linter issues
  ([`d21115c`](https://github.com/thiesgerken/carapace/commit/d21115cf5d080f401de4d93539c1307a25c2f89b))

- 🐛 fix react lints
  ([`e9f3c69`](https://github.com/thiesgerken/carapace/commit/e9f3c69048bb89e0a1dd61a669c9c75d1a6b83a0))

- 🐛 fix dependency in submit callback to use queuedMessage instead of hasQueuedMessage
  ([`d95d9ef`](https://github.com/thiesgerken/carapace/commit/d95d9ef0b6766286b9d48d1359435adcbf784123))

## v0.18.0 (2026-03-08)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`85d8e88`](https://github.com/thiesgerken/carapace/commit/85d8e88413d85851663caab528af31a95f93b048))

## v0.17.1 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 don't immediately append queued messages to history
  ([`9d6b55a`](https://github.com/thiesgerken/carapace/commit/9d6b55a8a481618c24c52ba5b891e102bc63cfa9))

### ✨ Features


- ✨ title generation
  ([`52149c3`](https://github.com/thiesgerken/carapace/commit/52149c3245c982bffc43a655b6eb344ceabf167a))

## v0.17.0 (2026-03-08)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`06df22e`](https://github.com/thiesgerken/carapace/commit/06df22ef29d1443374f9d5f870f47a078a2fc920))

## v0.16.0 (2026-03-08)


### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`abfab2e`](https://github.com/thiesgerken/carapace/commit/abfab2e299d3004fad5a211a4b89295e04f11e7c))

## v0.15.0 (2026-03-08)


### ✨ Features


- ✨ show a gauge with current session size
  ([`472e730`](https://github.com/thiesgerken/carapace/commit/472e73027f3848cad6aafa88fae5048764b68551))

- ✨ add queued message handling and interrupt functionality to chat view
  ([`4093130`](https://github.com/thiesgerken/carapace/commit/40931308f2225d7a9b4f0289552bf51b8cb1b84c))

- ✨ hold session id in url param
  ([`05437c3`](https://github.com/thiesgerken/carapace/commit/05437c3d5664a62cbdbcb8609320311ea9f92eb4))

- ✨ autocomplete for slash commands
  ([`18893d2`](https://github.com/thiesgerken/carapace/commit/18893d2699419fe784abbf47e6b60cabfd8b3f8e))

- ✨ add slash command autocomplete feature to chat input
  ([`03dc93d`](https://github.com/thiesgerken/carapace/commit/03dc93d7239a2886d3d38586748c396964d46dbb))

## v0.14.0 (2026-03-08)


### ✨ Features


- ✨ stop button to cancel agent
  ([`675d133`](https://github.com/thiesgerken/carapace/commit/675d1334c7950704321873a65f4f8ee4829871f7))

### 🐛 Bug Fixes


- 🐛 play around with approval options
  ([`3122dfc`](https://github.com/thiesgerken/carapace/commit/3122dfc796c4b1c365a1109a9e01b269286fa044))

## v0.13.0 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 escalation for eicar.com did not work
  ([`8704fd6`](https://github.com/thiesgerken/carapace/commit/8704fd6ffad52611e7f008cecc2e035eacd6c711))

- 🐛 escalation for eicar.com did not work
  ([`364125f`](https://github.com/thiesgerken/carapace/commit/364125f84b1ee4ddfcaf43c588213a716a2ed57f))

### Other


- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`f3de4df`](https://github.com/thiesgerken/carapace/commit/f3de4dfdb42d697f7b32ca7086466b30df040d52))

## v0.12.1 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 restore approvals on UI reload
  ([`143e850`](https://github.com/thiesgerken/carapace/commit/143e8507ae7212fb801c87c1cd696c2d1299f74c))

- 🐛 fix tool call approval
  ([`125c850`](https://github.com/thiesgerken/carapace/commit/125c8506f3e7e204dbaee993c2273c455898937d))

- 🐛 make the sidebar slightly wider for the new ids
  ([`d70615c`](https://github.com/thiesgerken/carapace/commit/d70615cfbf99933b8ff5fe937e810b2ee4d438cd))

### Other


- document linting in agents.md
  ([`4c40804`](https://github.com/thiesgerken/carapace/commit/4c4080413d5ecf963c7a15edcd917adf5c0c2388))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`bb722fc`](https://github.com/thiesgerken/carapace/commit/bb722fc9fef0269f5cd81d003e167988d1075928))

### ✨ Features


- ✨ add a test command to test sentinel escalation
  ([`09026f5`](https://github.com/thiesgerken/carapace/commit/09026f5469b4583df1cfaf007fb2aff89dd5cb20))

- ✨ better readable session ids
  ([`89df1f1`](https://github.com/thiesgerken/carapace/commit/89df1f159c681a80eadb8a49a7cc2ab93d23cec1))

## v0.12.0 (2026-03-08)


### 🐛 Bug Fixes


- 🐛 use short keys for formatting args summary in ToolCallBadge
  ([`73c6ccd`](https://github.com/thiesgerken/carapace/commit/73c6ccd7e6bb65816e9896b70cfca5cb20792d29))

- 🐛 persist proxy requests in events
  ([`c903f4f`](https://github.com/thiesgerken/carapace/commit/c903f4ff91ca2168c51c6540bb7e471099b25213))

- 🐛 fix(frontend): tool call spinner not clearing when proxy_domain intercepts result
  ([`fd1f897`](https://github.com/thiesgerken/carapace/commit/fd1f8977e84c7f48558e028770ca0aded19c74e4))

### ✨ Features


- ✨ docs: add commit message convention using gitmoji
  ([`3ebe25b`](https://github.com/thiesgerken/carapace/commit/3ebe25b5cefaa22cd845e5214f258f681380191a))

- ✨ Update datetime handling to use UTC in models and session management
  ([`004c8db`](https://github.com/thiesgerken/carapace/commit/004c8db338f18a315a7d6df8bd6c3a7aef2799ab))

## v0.11.0 (2026-03-08)


### ✨ Features


- ✨ Rename Bouncer to Sentinel
  ([`49819d8`](https://github.com/thiesgerken/carapace/commit/49819d828ccdd319188b13cef529d08557c97bc6))

## v0.10.0 (2026-03-08)


### Other


- relock
  ([`362fd15`](https://github.com/thiesgerken/carapace/commit/362fd1555d37d26d116fb4575ed2a875589c9b98))

### ✨ Features


- ✨ Enhance message handling in ChatView to support tool results and additional message details
  ([`1600386`](https://github.com/thiesgerken/carapace/commit/1600386480da69d0f935493642307ea3e1dd579a))

- ✨ Add tool result handling and notifications across components
  ([`080c21a`](https://github.com/thiesgerken/carapace/commit/080c21a2f1ecc523735962bf00683b4d00a774f8))

## v0.9.0 (2026-03-08)


### ✨ Features


- ✨ Tool/Proxy Approval via Shadow-Agent
  ([`463f10e`](https://github.com/thiesgerken/carapace/commit/463f10ed7daf095c82ad34666f3862eccf8f77cb))

- ✨ Security v2
  ([`463f10e`](https://github.com/thiesgerken/carapace/commit/463f10ed7daf095c82ad34666f3862eccf8f77cb))

  * 🛡️ Update SECURITY.md to enhance security guidelines and clarify agent behavior regarding prompt injection and accidental rogue actions. Added detailed sections on command scrutiny, sandbox operations, and user escalation protocols.

  * Update docs/credentials.md

  Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>

  * Convert `test_format_domain_escalation` to plain `def` (#40)

  * Initial plan

  * Remove async from test_format_domain_escalation (no await expressions)

  Co-authored-by: thiesgerken <7550099+thiesgerken@users.noreply.github.com>

  ---------

  Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

  * Include SECURITY.md in sandbox workspace mounts (#42)

  * Fix _build_mounts to include SECURITY.md as readonly mount

  * Remove dead `bouncer_messages` field from `SessionSecurity` (#43)

  * Remove dead bouncer_messages field from SessionSecurity

  * Remove unused asyncio.Lock from SessionSecurity (#44)

  * Remove unused _lock (asyncio.Lock) and asyncio import from SessionSecurity

  * Move function-level imports to module level in server, models, and matrix (#41)

  * fix: move function-level imports to module level in server.py, models.py, matrix.py

  * remove sandbox=on

  * Handle session retrieval with fallback to initialization in MatrixChannel

  * Verbessere die Funktion get_host_ip, um die IP-Adresse des Hosts im Docker-Netzwerk zu ermitteln und eine Fallback-Option für die Gateway-IP hinzuzufügen.

  * Füge Audit-Logging für Benutzerentscheidungen hinzu und verbessere die Protokollierung von Toolaufrufen

  * Vereinfache die Entscheidungslogik für Proxygenehmigungen und aktualisiere das Modell zur Unterstützung neuer Entscheidungen

  * Füge Referenzzählung für Sicherheitssitzungen hinzu und verbessere die Sitzungsbereinigung

  * make the read/write/patch ops work in the sandbox

  * Add domain info callbacks and switch history/usage/event storage to YAML format

  * fix yaml

  * Remove dash from detail display in ToolCallBadge component

  Co-authored-by: Copilot <198982749+Copilot@users.noreply.github.com>

### Other


- Enhance Python style guidelines to encourage clarity in user requests. Added a note advising users to avoid technical debt and seek better solutions.
  ([`ab6b668`](https://github.com/thiesgerken/carapace/commit/ab6b66818b988ac93a06d98353616a111ef82386))

## v0.8.0 (2026-02-22)


### ✨ Features


- ✨ Matrix as additional frontend
  ([`bb92183`](https://github.com/thiesgerken/carapace/commit/bb92183d2d3711d76c462275ff7c742a48099c24))

- ✨ Matrix as additional frontend
  ([`bb92183`](https://github.com/thiesgerken/carapace/commit/bb92183d2d3711d76c462275ff7c742a48099c24))

  * pass-through matrix pw

  * make it possible to auth using password instead of token

  * improve error handling in matrix code

  * Enhance Matrix channel command handling and logging

  - Updated approval command from `/approve` to `/allow` for clarity.
  - Improved session command result formatting to include activated, disabled rules, approved credentials, and allowed domains.
  - Refactored agent turn execution to run as a background task, allowing for immediate response to new events.
  - Added a new method `_run_turn_locked` to manage room-specific locks during agent turns.
  - Set logging levels for additional libraries to WARNING in server.py for better log management.

  * fix tests

### Other


- 💚 add docker builds to the ci
  ([`fcb36f6`](https://github.com/thiesgerken/carapace/commit/fcb36f62ccc5cd0d22bf9d4bc6bf67bf92314fff))

## v0.7.1 (2026-02-22)


### 🐛 Bug Fixes


- 🐛 bad gitignore
  ([`36ada40`](https://github.com/thiesgerken/carapace/commit/36ada4061bc0fdc65a522999424f66d7dfd9d8e3))

## v0.7.0 (2026-02-22)


### ✨ Features


- ✨ route sandbox http calls through the backend using a CONNECT proxy
  ([`58b96e8`](https://github.com/thiesgerken/carapace/commit/58b96e88329a7184a7cdf4263e96216eaa52336b))

- ✨ route sandbox http calls through the backend using a CONNECT proxy
  ([`58b96e8`](https://github.com/thiesgerken/carapace/commit/58b96e88329a7184a7cdf4263e96216eaa52336b))

- ✨ Enhance Docker configuration and logging for sandbox environment
  ([`58b96e8`](https://github.com/thiesgerken/carapace/commit/58b96e88329a7184a7cdf4263e96216eaa52336b))

  - Added `tty` support in `docker-compose.yml` for the carapace service.
  - Updated volume mappings to include the source directory for carapace.
  - Introduced `ANTHROPIC_API_KEY` as an environment variable in the Docker setup.
  - Changed frontend port mapping from 3000 to 3001.
  - Enhanced logging in `server.py` to display network interface information and resolved sandbox network names.
  - Improved `DockerRuntime` to manage network names and ensure correct network connections for containers.
  - Updated `SandboxManager` to dynamically resolve and log proxy URLs based on the container's network settings.

- ✨ Implement proxy domain approval mechanism in sandbox
  ([`58b96e8`](https://github.com/thiesgerken/carapace/commit/58b96e88329a7184a7cdf4263e96216eaa52336b))

  - Added support for proxy domain approval requests in the chat view and message components.
  - Introduced `handleProxyApproval` function to manage user decisions on proxy access.
  - Updated `SandboxManager` to handle domain approval requests and decisions, integrating with the proxy server.
  - Enhanced WebSocket communication to facilitate proxy approval responses.
  - Improved session management to display allowed domains and their scopes in the CLI.
  - Refactored related components to ensure seamless integration of the new approval workflow.

  * Fix content length in forbidden response for proxy policy

  * Enhance ProxyServer to filter hop-by-hop headers and enforce connection closure. Updated header processing to drop existing Connection headers and append "Connection: close" to prevent HTTP/1.1 keep-alive issues.

  * Fix session token management and enhance error handling in SandboxManager

  - Evict orphaned tokens from previous failed attempts to ensure clean session initialization.
  - Refactor IP resolution logic to include error handling, ensuring proper cleanup on failure.
  - Maintain existing functionality for proxy URL generation and container configuration.

  * Refactor SandboxManager proxy configuration in tests

  - Simplified the instantiation of SandboxManager in test cases by removing the hardcoded proxy URL.
  - Updated the `_build_proxy_env` method calls to include the proxy URL as a parameter, enhancing flexibility in testing proxy configurations.
  - Ensured that the tests maintain their functionality while improving code clarity and maintainability.

  * Refactor ProxyServer domain checking methods in tests

  - Renamed `_check_domain` method to `_is_allowed` for clarity in the ProxyServer class.
  - Updated test cases to reflect the new method name while maintaining existing functionality.
  - Improved code readability and consistency in domain approval checks.

  * Remove unused proxyApprovalState ref

  The proxyApprovalState ref was written to but never read. Proxy approval state is tracked directly on message objects via the decision property, making this ref redundant.

  Applied via @cursor push command

  * Fix proxy approval allow-all CLI choices

  Co-authored-by: Thies Gerken <thiesgerken@users.noreply.github.com>

  * Enhance WebSocket error handling and improve test setup

  - Added contextlib suppression to handle unexpected WebSocket errors gracefully by closing the connection with code 1011.
  - Updated the test server setup to return an empty list for domain info in the SandboxManager, improving test reliability.

  * fix: preserve proxy approvals across container recreation

  ---------

  Co-authored-by: Cursor Agent <cursoragent@cursor.com>

## v0.6.0 (2026-02-22)


### ✨ Features


- ✨ Docker sandboxing for sessions
  ([`ce5ca5b`](https://github.com/thiesgerken/carapace/commit/ce5ca5bcc4a7e94e89c5e09c01088e46dedc6e6c))

- ✨ Docker sandboxing for sessions
  ([`ce5ca5b`](https://github.com/thiesgerken/carapace/commit/ce5ca5bcc4a7e94e89c5e09c01088e46dedc6e6c))

- ✨ Update logging guidelines in AGENTS.md and python-style.mdc
  ([`ce5ca5b`](https://github.com/thiesgerken/carapace/commit/ce5ca5bcc4a7e94e89c5e09c01088e46dedc6e6c))

  - Added a section on logging best practices, specifying the exclusive use of `loguru` over stdlib `logging`.
  - Included instructions for importing `loguru` and using f-strings in log calls for improved readability and performance.

  * add loguru

  * Refactor logging to use loguru across the codebase

  - Replaced instances of the standard logging library with loguru for improved logging capabilities.
  - Updated log messages to utilize f-strings for better readability and performance.
  - Removed the `enabled` field from `SandboxConfig` as it is no longer needed.
  - Enhanced error handling and logging in the Docker runtime and sandbox manager for better debugging and maintenance.

- ✨ Enhance Docker runtime with network management
  ([`ce5ca5b`](https://github.com/thiesgerken/carapace/commit/ce5ca5bcc4a7e94e89c5e09c01088e46dedc6e6c))

  - Added a method to ensure the existence of Docker networks before container creation.
  - Improved the DockerRuntime class to manage and log network creation, enhancing the overall functionality of the sandbox environment.

  * Fix input prompt formatting in approval request to escape brackets for proper display

  * Refactor sandbox configuration and Docker integration

  - Removed the carapace-sandbox-image service from docker-compose.yml and deleted its Dockerfile.
  - Updated SandboxConfig to allow an empty base_image, enabling auto-building from a bundled Dockerfile.
  - Introduced a method to read the bundled Dockerfile content in bootstrap.py.
  - Enhanced DockerRuntime with a build_image method to build the sandbox image from the bundled Dockerfile.
  - Adjusted server lifespan logic to build the sandbox image if no base_image is specified in the configuration.

  * Enhance error handling and logging in sandbox and Docker runtime

  - Introduced custom exceptions `ContainerGoneError` and `SkillVenvError` for better error management in the sandbox environment.
  - Updated the `DockerRuntime` and `SandboxManager` classes to handle these exceptions, improving robustness during container execution and skill virtual environment building.
  - Enhanced logging to provide clearer insights into errors and warnings related to container management and skill activation.

  * Set logging levels for specific libraries to WARNING in server.py

  - Adjusted logging configuration to set the logging level to WARNING for the "httpcore", "httpx", and "docker" libraries, improving log clarity and reducing verbosity.

  * Enhance logging configuration in server.py

  - Added "anthropic" and "websockets" to the list of libraries with WARNING logging level.
  - Introduced a custom emoji patcher for log records to replace specific prefixes with emojis, improving log readability.

  * Update Python style guidelines in python-style.mdc

  - Clarified the use of Pydantic `BaseModel` for structured data, removing references to stdlib `@dataclass`.
  - Introduced the use of `Annotated[type, Field(...)]` for field metadata and defaults, emphasizing correct usage.
  - Specified that non-nullable fields should not be assigned `None` with `# type: ignore`, promoting better type safety.
  - Updated guidance on avoiding mutable default arguments to use `Annotated` for consistency.

  * Refactor agent and sandbox management for improved structure and logging

  - Removed the local command execution fallback in favor of a more streamlined sandbox execution approach.
  - Enhanced the `Deps` class to utilize Pydantic's `BaseModel` and `Annotated` for better type safety and field management.
  - Updated the `SessionContainer` and `Mount` classes to inherit from `BaseModel`, ensuring consistent data handling.
  - Improved error handling in the agent's skill activation process with enhanced logging using `loguru`.
  - Adjusted server cleanup logic to ensure proper management of sandbox resources.

  * Rename `bash` tool to `shell` in agent.py for clarity and update command execution in DockerRuntime to use `bash` instead of `sh` for consistency in command handling.

  * Update Dockerfile to use specific version of uv and remove unnecessary apt-get commands

  * Update default server host in ServerConfig to allow external access

  * Improve WebSocket error handling in _chat_loop function

  - Added reconnection logic for both sending messages and reading server responses upon ConnectionClosed exceptions.
  - Enhanced user feedback during reconnection attempts to improve user experience.

  * Refactor WebSocket connection handling in cli.py

  - Updated the WebSocket connection logic to use the `websockets.asyncio.client` module directly for improved clarity and consistency.
  - Enhanced type hinting for the `_connect_ws` function to specify the return type as `ClientConnection`.

  * Refactor skill management in Deps class and server dependency building

  - Updated the `Deps` class to initialize `skill_catalog` and `activated_skills` with default empty lists for improved clarity and consistency.
  - Modified the `_build_deps` function in `server.py` to pass an empty list for `activated_skills`, ensuring proper initialization during dependency construction.

  * Add CARAPACE_HOST_DATA_DIR environment variable and update SandboxManager for host path handling

  - Introduced the `CARAPACE_HOST_DATA_DIR` environment variable in `docker-compose.yml` to specify the host data directory.
  - Updated `server.py` to retrieve and pass the host data directory to the `SandboxManager`.
  - Enhanced `SandboxManager` to handle host paths for bind mounts, ensuring correct path resolution when running in Docker.
  - Improved logging to provide feedback on host data directory overrides during sandbox initialization.

  * Implement skill name validation in SandboxManager

  - Added a regex-based validation function for skill names to ensure they are non-empty, start with an alphanumeric character, and contain only valid characters.
  - Integrated the validation function into the `activate_skill`, `_build_skill_venv`, and `save_skill` methods to enforce skill name rules and return appropriate error messages when invalid names are provided.
  - Refactored the `SessionContainer` class to initialize `activated_skills` with an empty list for consistency.

  * fix lint issues

  * Enhance documentation in agent.py for skill activation and command execution

  - Updated the prompt for skill activation to clarify the setup of a virtual environment.
  - Improved the docstring for the exec function to specify that it typically runs bash commands.
  - Removed the unused shell function to streamline the code.

  * Refactor session directory structure in SandboxManager

  - Changed the session directory structure to use a single 'workspace' directory for skills and temporary files.
  - Updated the relevant methods to reflect the new paths for skill and temporary directories, ensuring consistent handling of session data.

## v0.5.0 (2026-02-20)


### ✨ Features


- ✨ Implement token usage tracking and reporting
  ([`00fbd8e`](https://github.com/thiesgerken/carapace/commit/00fbd8eab83a2906cb6902064ce06e1ab65a15f8))

- ✨ Implement token usage tracking and reporting
  ([`00fbd8e`](https://github.com/thiesgerken/carapace/commit/00fbd8eab83a2906cb6902064ce06e1ab65a15f8))

  - Added a new `UsageTracker` class to monitor token usage across models and categories.
  - Introduced a `/usage` command in the CLI to display token usage statistics.
  - Enhanced the `classify_operation` and `check_rules` functions to record usage data.
  - Updated the frontend to visualize usage data with a new `UsageView` component.
  - Bumped `carapace` version to 0.4.0 to reflect these changes.

- ✨ Enhance usage tracking and reporting features
  ([`00fbd8e`](https://github.com/thiesgerken/carapace/commit/00fbd8eab83a2906cb6902064ce06e1ab65a15f8))

  - Updated `pyproject.toml` to specify version constraints for dependencies.
  - Added new `costs` field to `UsagePayload` for tracking costs associated with token usage.
  - Implemented cost estimation in `UsageTracker` to calculate total costs based on token usage.
  - Enhanced frontend components to display command results and usage costs.
  - Improved session management to persist usage data and events for better tracking.
  - Updated CLI to include costs in the `/usage` command output.

  This commit builds upon the previous implementation of token usage tracking, providing a more comprehensive view of resource utilization.

## v0.4.0 (2026-02-20)


### ✨ Features


- ✨ Add a web frontend
  ([`4d7e028`](https://github.com/thiesgerken/carapace/commit/4d7e0281acdb0fef1c252d0ce818fe6afc98ba6e))

## v0.3.0 (2026-02-19)


### ✨ Features


- ✨ Revamp Carapace architecture with server and CLI client integration
  ([`6644bfe`](https://github.com/thiesgerken/carapace/commit/6644bfe8bca5e79801320c76fed669e1775fa4f5))

- ✨ Revamp Carapace architecture with server and CLI client integration
  ([`6644bfe`](https://github.com/thiesgerken/carapace/commit/6644bfe8bca5e79801320c76fed669e1775fa4f5))

  - Introduced a FastAPI server for handling requests and WebSocket connections.
  - Updated CLI to connect to the server, replacing the previous interactive model.
  - Enhanced documentation in AGENTS.md and README.md to reflect new server and client structure.
  - Added bearer token authentication for secure communication between CLI and server.
  - Updated project dependencies to include FastAPI, Uvicorn, and WebSockets.
  - Version bump to 0.2.0 to signify major architectural changes.

- ✨ Implement session locking in WebSocket chat handler
  ([`6644bfe`](https://github.com/thiesgerken/carapace/commit/6644bfe8bca5e79801320c76fed669e1775fa4f5))

  - Added asyncio locks to manage concurrent access to session data, ensuring serialized agent turns.
  - Refactored chat_ws function to utilize session locks for loading and saving message history and session state.
  - Improved error handling and logging during agent execution.

  * 🧹 Clean up unused server URL function in CLI

  - Removed the `_server_url` function as it was no longer needed in the updated architecture.
  - Streamlined the code for better readability and maintenance.

- ✨ Improve error handling for approval requests in CLI and server
  ([`6644bfe`](https://github.com/thiesgerken/carapace/commit/6644bfe8bca5e79801320c76fed669e1775fa4f5))

  - Added exception handling for keyboard interruptions during approval requests in the CLI, ensuring a graceful denial message is displayed.
  - Updated server logic to handle interrupted approvals by marking them as denied and clearing pending requests, enhancing overall robustness.

  * Fix 5 bugs: WebSocket auth exception, token permissions, session lock cleanup, async input blocking, and verbose output routing

  - Use WebSocketException instead of HTTPException for WebSocket auth failures
  - Set token file permissions to 0600 for security
  - Clean up session locks on WebSocket disconnect to prevent memory leak
  - Use run_in_executor for approval prompt input to avoid blocking event loop
  - Route verbose tool call output via WebSocket instead of server stdout

  Applied via @cursor push command

  * Fix fire-and-forget WebSocket send by saving task references

  - Save created tasks in a set to prevent garbage collection
  - Add error handling to log WebSocket send failures
  - Cancel pending tasks on client disconnect
  - This ensures the server detects dropped clients and stops expensive LLM calls

  * pc

  * Refactor WebSocket chat handler for improved control flow and error handling

  - Changed return statement to break in command handling for better flow control.
  - Added a finally block to ensure session locks are cleaned up on disconnect.
  - Enhanced error handling for unexpected agent output types during message sending.

  * Enhance session management in WebSocket chat handler

  - Introduced an async context manager for session connections to manage locks more effectively.
  - Updated chat_ws function to utilize the new session connection management, ensuring proper lock handling during WebSocket interactions.
  - Improved error handling and cleanup on client disconnect to prevent memory leaks and ensure session integrity.

  ---------

  Co-authored-by: Cursor Agent <cursoragent@cursor.com>

### Other


- 💚 Update build command in pyproject.toml to include 'uv lock'
  ([`5cedc87`](https://github.com/thiesgerken/carapace/commit/5cedc87e2c8a74a142eaab058013e8993fcbdc45))

## v0.2.0 (2026-02-15)


### ✨ Features


- ✨ Integrate Logfire for enhanced logging and tracing
  ([`7c1ddeb`](https://github.com/thiesgerken/carapace/commit/7c1ddeb0cb5787fa0ff3f6883c3a9b2a2c0c1008))

  - Added `logfire` dependency to `pyproject.toml` and `uv.lock`.
  - Configured Logfire in the CLI to enable tracing based on user token.
  - Updated `CarapaceConfig` to include `logfire_token` field.
  - Modified example `config.yaml` to indicate where to set the Logfire token.

### Other


- 📝 Update README.md to include new security guideline for skills
  ([`83d90b1`](https://github.com/thiesgerken/carapace/commit/83d90b1f343811cdb8ffb278470680e3d8da4225))

  - Added a section emphasizing the importance of reviewing skills before installation, highlighting that skills are considered trusted code and the user's responsibility in managing them.

## v0.1.0 (2026-02-15)


### ✨ Features


- ✨ Update commit parser options in pyproject.toml
  ([`632eaf4`](https://github.com/thiesgerken/carapace/commit/632eaf494bc4a6a29472427323cd38efdcda368e))

  - Added major, minor, and patch tags for semantic release.
  - Enhanced commit parsing configuration to support emoji and text tags.

- ✨ Implement message replay functionality in chat session
  ([`dfe883b`](https://github.com/thiesgerken/carapace/commit/dfe883bfaededd25087aa887a282114b3b2dcda7))

  - Added `_replay_history` function to display previous conversation turns.
  - Introduced `--prev` option in the `chat` command to specify the number of previous turns to replay.
  - Updated response validation logic for improved readability.

- ✨ Add bootstrap module and initial asset files for Carapace
  ([`655e154`](https://github.com/thiesgerken/carapace/commit/655e154612384688fa5c25d6c20600de78ec1bd4))

  - Introduced `bootstrap.py` to ensure the creation of critical files and directories.
  - Added asset files including `config.yaml`, `CORE.md`, `SOUL.md`, `USER.md`, and rules in `rules.yaml`.
  - Implemented functionality to seed skills and manage data directory initialization in the CLI.

### Other


- 📝 Add Python coding style guide for carapace project
  ([`8f91cf2`](https://github.com/thiesgerken/carapace/commit/8f91cf2e2b65f36a1e277533d6cba3cf5470ade0))

- 📝 Add AGENTS.md for project overview, setup, code style, structure, testing, and CI details
  ([`b79fbbb`](https://github.com/thiesgerken/carapace/commit/b79fbbba67733067727b8e7c4a539b06fe8b3184))

- update readme
  ([`2f1daa1`](https://github.com/thiesgerken/carapace/commit/2f1daa15813b60241506afde11931881fd7d1e66))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`85552db`](https://github.com/thiesgerken/carapace/commit/85552db18aa94bd696bc879fefca3801aecc3f34))

- 📝 Add MIT LICENSE file
  ([`1226e36`](https://github.com/thiesgerken/carapace/commit/1226e3622ac8a65335b3eb16367104af3cdfa7a2))

  Co-authored-by: Cursor Agent <cursoragent@cursor.com>

- fix url in readme
  ([`f2ece16`](https://github.com/thiesgerken/carapace/commit/f2ece16e3f29036c1b85d95b2c3fa39ab88fc564))

- 📝 Enrich README with getting started guide and demo output
  ([`593d395`](https://github.com/thiesgerken/carapace/commit/593d3952b870e44ebd94f5f376ca2cb31b5b5318))

  * 📝 Enrich README with getting started guide and demo output

  Add installation, running, and configuration instructions. Include a pruned demo session showcasing the interactive CLI.

  Co-authored-by: Cursor <cursoragent@cursor.com>

  * tired of that

  ---------

- 💚 Fix CI: add pytest dev dep and gitmoji PR title check
  ([`7e0ba76`](https://github.com/thiesgerken/carapace/commit/7e0ba766fd6b13f7c68b191236fce903c06bb48f))

  * 💚 Fix CI: add pytest dev dep and gitmoji PR title check

  - Add pytest to dependency-groups so `uv sync --dev` installs it
  - Add pr-title job to enforce gitmoji prefix on PR titles

  Co-authored-by: Cursor <cursoragent@cursor.com>

  * 💚 Disable color in CLI test runner to fix CI assertions

  * 💚 Use NO_COLOR env var instead of color kwarg in test runner

  * 💚 Strip ANSI escape codes in CLI test assertions

  ---------

## v0.0.0 (2026-02-14)


### Other


- update build command in pyproject.toml to install uv before building
  ([`b67255c`](https://github.com/thiesgerken/carapace/commit/b67255ca8a177da256fcbcfaf40b1d84be8dafa8))

- add ci
  ([`dd57de9`](https://github.com/thiesgerken/carapace/commit/dd57de9d6a1be3ba413bd8c20ed12d45fb5032e4))

- add tests, add precommit, fix lints
  ([`3adb428`](https://github.com/thiesgerken/carapace/commit/3adb4283ae1ec76dc69a4df62bddd7db9a36985d))

- let opus code a PoC
  ([`7e2f876`](https://github.com/thiesgerken/carapace/commit/7e2f876aa755be5176601f7a5fa217cca59f0694))

- add docs and brainstorming
  ([`54eacb2`](https://github.com/thiesgerken/carapace/commit/54eacb2091b136948e35bdd3ae7e3d305a4a1330))
