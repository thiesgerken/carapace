# Session Compaction

Long sessions eventually approach the agent model's context window. Compaction shrinks the
model history that is sent to the LLM while keeping the full human-readable transcript intact.

For the agent, carapace treats compaction the same way it treats the rest of its state: nothing is
hidden. The model sees a compacted cut, but the originals stay in the events transcript and the
Git-backed session archive, and every compaction is visible in the web UI. The sentinel's shadow
conversation is different: its compaction overwrites the persisted conversation, and only the
action log, the audit log and the latest compaction request in the [debug view](debug-view.md)
remain (see [Sentinel](#sentinel)).

> The agent's model history is compacted **automatically** once it reaches the agent model's
> compaction threshold: by the model's provider where it offers that (see
> [Provider-side compaction](#provider-side-compaction)), otherwise by carapace inside the run (see
> [Automatic compaction](#automatic-compaction)). `/compact` compacts on demand. The sentinel's shadow
> conversation is compacted automatically too (see [Sentinel](#sentinel)).

## What gets compacted

Three strategies operate on different regions of the history:

| Strategy | Region | What it does |
| --- | --- | --- |
| Thinking-drop | All but the newest turn | Removes stale `thinking` parts (providers do not need them back). Free, no LLM call. |
| Tool-return compaction | Kept turns, excluding the verbatim hot zone | Summarizes large tool outputs (e.g. log/`kubectl` dumps) in place. The tool call/return pairing is preserved; the part is marked so it is never compacted twice. |
| Message-fold | `/compact`: turns older than the keep-window `K`. Automatic: everything but the newest steps | Collapses the older history (user + assistant + tool returns) and the previous summary into one summary block. |

The newest `verbatim_tool_turns` completed turns form a **verbatim hot zone**: their tool outputs are
never summarized, so the agent keeps exact fidelity on its most recent work. Tool-return compaction
only touches outputs in kept turns *older* than that zone (and never inside a fold block). Set it to
`0` to allow compacting every kept tool output, including the latest turn's.

Folds **roll**: the history holds at most one summary block. A new fold summarizes the previous
summary together with the newly folded region, so the history stays bounded and every summary is
written knowing what came before. The compaction tree keeps every earlier summary, so a rewind into
the folded region falls back to the summary that was current at that point.

The summarizer sees the folded turns as plain text: user prompts, assistant replies, every tool call
with its arguments (paths, commands, URLs) and every tool result. Arguments and results are cut
deterministically to their first and last lines (and characters, for single-line dumps), so a few
huge outputs cannot crowd out the rest. If the rendered region still exceeds the compaction model's
`max_input_tokens`, the fold fails with an `input too large` error instead of sending it.

Every run of pydantic-ai merges consecutive requests and persists the merged history: a fold block
absorbs the next turn's prompt, and an unattended turn's `task_done`/`task_failed` return absorbs the
next task. Compaction, rewind and fork recognize folds and turn boundaries only on separate requests,
so the agent's history is split back apart whenever it is loaded (and the sentinel's shadow
conversation before it is compacted).

The model is always told that content was compacted: folded blocks become a clearly marked summary
message, and compacted tool outputs are prefixed with a marker naming the way back,
`read_tool_output("<tool call id>")`. That tool returns the original output from the session's events
transcript, which compaction never rewrites, so the agent doesn't have to re-run a tool that may have
side effects. The original is what the model saw before compaction, already capped at
`tool_output_max_chars`. The tool is safe-listed (it only returns what this session's agent has
seen) and its definition is static, so it doesn't affect the prefix cache.

Summaries run as the agent itself: their system prompt leads with the agent's shared prefix
(`AGENTS.md`, `SOUL.md`, `USER.md`, skill catalog), followed by the compaction instructions. See
[system prompt loading](persistent-context.md#system-prompt-loading).

Compaction fails loudly. A failed or empty summary, an exhausted session budget or an input that
does not fit the compaction model aborts the whole `/compact` with a visible error, and the history
stays exactly as it was. Nothing is skipped silently.

Token counts in reports and in the automatic ladder are local estimates without `thinking` parts:
providers strip old thinking themselves, so counting it would overstate both the history and what
dropping it saves. The report still says how many thinking parts were dropped.

## Provider-side compaction

Where the model's provider compacts server-side, that is the default, for the agent and the sentinel
independently (each by its own model): no extra model, no extra round trip.

| Model provider | Compaction |
| --- | --- |
| `anthropic` | Server-side (`context_management`) at the model's compaction threshold, raised to Anthropic's minimum of 50,000 tokens. The provider summarizes with carapace's own instructions: the fold instructions for the agent, the sentinel fold instructions for the sentinel. |
| `openai-responses` (OpenAI itself, no custom `base_url`) | Server-side (`context_management`) at the model's compaction threshold. OpenAI takes no instructions. |
| `openai-codex` | Server-side (`context_management`) at the model's compaction threshold, like `openai-responses`. The Codex CLI never uses this (it sends a `compaction_trigger` input item instead), but the Codex backend honours it (verified live on 2026-11-12, #485). `/responses/compact` answers 404 there. |
| everything else (`openai`, `openai-chat`, `openrouter`, custom `base_url`s, …) | Local, see [Automatic compaction](#automatic-compaction). |

For a model that compacts server-side, carapace's own automatic compaction inside the run only watches
the provider (see *Provider failures* below). The provider returns a `CompactionPart` (Anthropic: a readable summary; OpenAI: encrypted) as part of a
response. It stays in the model history, and every later request sends only what comes after it. The
history keeps every original message before it too, which is what makes the cases below lossless. The
price: on such a model the stored history grows without bound, although only the part after the latest
compaction is sent. All local estimates (reports, the automatic ladder, the debug view, request
shapes) count only that sent part.

- **Provider switch:** a provider reads back only its own compaction parts. Before a turn, when the
  history holds a part the agent model would not read back (another provider, or a model that
  compacts locally), carapace strips it and runs the automatic ladder once, regardless of the trigger:
  the last measurement came from the compacted context. The sentinel does the same before an
  evaluation. Neither needs the events transcript.
- **`/compact` on such a model** runs carapace's local ladder; after a fold, the provider's compaction
  parts are dropped, since the fold now covers what they covered. Without a fold it summarizes only tool
  outputs after the provider's latest compaction: the ones before it are never sent. The provider compacts again later
  on its own when needed.
- **Usage:** what the provider reports for its compaction (Anthropic does) counts under the
  `compaction` category, the rest of the request under `agent` or `sentinel`.
- **Large histories:** after a long server-side session the stored history can exceed the compaction
  model's window. A fold then summarizes it in slices, oldest first, each slice together with the
  summary so far, and ends with one summary. A single message too large even on its own fails loudly.
- **Provider failures** are loud and fall back to carapace for that compaction, so a session keeps
  working when a provider changes its behaviour:
  - *Skipped:* a request the provider was asked to compact (measured by that provider, above the
    threshold it was sent, which for Anthropic is at least 50,000) whose response carries no compaction
    part means the provider ignored the setting. carapace logs an error, marks a failed compaction in the
    transcript, and compacts this once with its own ladder, from the originals (provider parts
    stripped). The agent checks this before each request inside the run, the sentinel before each
    evaluation.
  - *Rejected:* a `400` that names `context_management` means the provider refuses the setting. That
    request fails (the turn ends with the provider's error; **Continue** retries it; a sentinel
    evaluation fails like any other), carapace logs an error and marks it, and the model compacts locally
    until the server restarts. A sentinel rebuilds its agent right away, so its next evaluation goes out
    without the setting.
- **`/uncompact`** also removes the provider's compaction (the history is rebuilt from the events) and
  its markers. A rewind into the middle of a turn rebuilds that turn without the compaction part and
  drops its marker too.

## Automatic compaction

Before every model request of a run (a pydantic-ai capability), carapace checks the input tokens the
provider reported for the newest measured request against the agent model's compaction threshold (see
[Configuration](#configuration)). Responses carapace writes itself, such as the error that ended a
failed turn, carry no measurement and are skipped, so **Continue** after a failure is checked too. Above it, the history is compacted and the run continues from the
compacted history, without user interaction, so a single long autonomous turn with hundreds of tool
calls never outgrows the context window.

The ladder stops at the **target**, half the threshold (not configurable), checked between rungs.
The check adds to the local estimate (thinking included) what the provider counted on top of it for
the measured request (system prompt, tool definitions, tokenizer differences), so a small window or a
large prompt cannot make a history look smaller than it is.

1. Thinking-drop.
2. Tool-return compaction outside the verbatim hot zone.
3. Message-fold of everything but the newest steps that together fit half the target (by the local
   estimate). A step is one
   model response plus its tool returns, so the cut may land inside the running turn; a tool call
   never loses its return, and the newest step always stays verbatim.

A measurement taken before the session's last compaction (e.g. `/compact` between turns) describes
a history that no longer exists and is ignored. The session state remembers the provider timestamp of
the newest measured response at each compaction, so both sides of that comparison come from the
provider's clock. If a fresh measurement is above the threshold and nothing is left to compact, the turn fails through the regular error path (the **Continue** action then
applies). A failed summary fails the turn the same way: the agent never continues past the threshold
uncompacted. The compacted history is saved with the turn, also when the turn fails later.

`/compact` runs every rung regardless of the target. It folds before it summarizes tool outputs, so
it never pays for summaries the fold would discard.

## The `/compact` command

```
/compact                          Run the full ladder: drop stale thinking → fold all but the last K turns → summarize big tool outputs
/compact keep the migration details   Same, and every summary request is told to keep what the focus names
```

`K` is *Keep recent turns* and the tool-output hot zone is *Verbatim tool turns* (see Configuration
below); the command takes no numbers. The optional focus is free text appended to each summary
request (after the material, so it does not split the cached prompt prefix). The reply shows tokens
before/after and a breakdown of what was compacted.

The same lives in the chat's **Usage** card: **Compact** runs `/compact`, and the "…" button opens a
dialog with a dry run from the planners (no LLM call): the last request's provider-reported input
tokens against the agent model's compaction threshold and context window, the thinking parts, turns and tool outputs that would go,
and the estimated size afterwards without the summaries, whose size is unknown until they are
written. It takes a focus and runs `/compact [focus]`; its collapsed *Debug* section runs
`/uncompact`. The dry run is `GET /api/sessions/{id}/compaction/preview`.

## Configuration

Compaction is configured per platform in **Settings → Platform** (admin only). Values are stored in
the DB-backed platform settings (the `agent` scalar row), not a config file:

| Setting | Where | Default | Meaning |
| --- | --- | --- | --- |
| Compaction | Default models | Default (title model) | Model used for fold/tool summaries (a first-level default model alongside agent/sentinel/title) |
| Keep recent turns | Compaction | 8 | Completed turns kept verbatim; the `K` that `/compact` keeps |
| Verbatim tool turns | Compaction | 4 | Newest turns whose tool outputs are never summarized (`0` disables) |
| Tool-output floor (tokens) | Compaction | 4000 | Tool outputs smaller than this are left alone |
| Compaction threshold (tokens) | Each model row | `min(60 % × max input tokens, 250k)` | Context size at which a conversation on this model is compacted automatically. Max input tokens counts as 200k when unset. Must stay below that window |

The threshold belongs to the model, not the role: the sentinel compacts at the threshold of the
sentinel model. 60 % leaves room for the system prompt, the next request and the answer; the 250k
cap keeps huge context windows from growing slow and expensive long before they fill. Leave the
field empty unless a model needs something else (the placeholder shows the computed default).

The compaction model is a separate, configurable default model (a cheap/haiku-class model is a good
default); leaving it on "Default" reuses the title model. Its usage is tracked under the
`compaction` category, separate from the agent. The first tool-output summary runs alone so it
writes the compaction model's prompt cache; the rest then run concurrently (reading that cache),
bounded by the shared `agent.max_parallel_llm` limit, and the first failure cancels the others. Each
summary call costs at least the cached system prompt plus the output, which is why the floor is
high: summarizing small outputs costs more than it saves. Code defaults live in
`agent.compaction_model` and `agent.compaction` (`AgentConfig` / `CompactionConfig`).

The platform default is just a default: each session can override the compaction model like the
other roles with `/model compaction NAME` (and `/model NAME` switches all four roles at once, while
`/model compaction reset` returns to the default). Per-user defaults live under
`default_models.compaction` in the user config.

## Viewing compaction in the UI

The main view always shows the **original, uncompacted** conversation — compaction is surfaced as a
subtle marker plus an on-demand peek at what the model actually sees, never by hiding the originals.

- **Compacted tool rows** outside a fold show a `compacted` badge; expanding the row reveals a **"Model sees"**
  disclosure with the shortened tool output and token savings, alongside the full original output.
- **Folded turns** stay inline and expanded, wrapped in a left **margin rail** with a header chip
  (`N turns condensed for the model`). The chip expands to the model-facing summary text, the newest
  summary for every folded turn; the original turns render normally inside the rail. A turn that an
  automatic fold cut in two is inside the rail up to the cut. Automatic compaction during a turn shows
  up after the next reload of the transcript.
- **Provider compaction** shows as a marker at the point where the provider compacted ("Context
  compacted by anthropic"). It expands to the provider's summary, or says that the provider keeps it
  encrypted. The messages above it stay shown as they were. A failed provider compaction shows as a
  red marker ("Compaction by openai-codex failed, compacted locally", or for a refusal "openai-codex
  rejected compaction; this model compacts locally from now on") that expands to the reason.
- The [debug view](debug-view.md) shows the agent's latest request exactly as it went to the model,
  fold summaries, compacted tool returns and a provider's compaction part included (nothing before
  that part), and the latest compaction request itself.

The `/history` API enriches each compaction annotation with the model-facing text (`summary` for a
fold node, `model_text` for a compacted tool return) so the main view needs no second request.

## Data model

- Model history (`session_history`) holds the compacted cut: a marked synthetic message per fold,
  and shortened `ToolReturnPart`s stamped with compaction metadata (the re-compaction guard).
- The compaction tree (`session_compaction`) stores the fold summary nodes for the UI.
- The events transcript retains the originals and carries per-event compaction annotations, plus a
  `compaction` event (provider, readable summary if any) where a provider compacted, or with `failed`
  (the reason) where its compaction failed and carapace stepped in. The Git archive
  keeps the untouched history. Compaction is therefore inspectable and reversible.

## Sentinel

The sentinel keeps its own shadow conversation (see [security.md](security.md#sentinel-state)). It is
never reset and **not** affected by `/compact`; instead it is compacted automatically.

- **When:** on a sentinel model that compacts server-side, the provider does it (see
  [Provider-side compaction](#provider-side-compaction)) and carapace steps in only after a provider
  switch or when the provider skipped a compaction. Otherwise before each sentinel evaluation, once the provider-reported input tokens of the
  previous evaluation exceed the compaction threshold of the sentinel model (see Configuration).
- **What:** the same ladder and settings as `/compact`, with one evaluation (request, skill
  inspections, verdict) as one turn: thinking-drop, fold all but the newest *Keep recent turns*
  evaluations, then summarize large tool outputs (in practice `read_skill_file` returns) outside the
  newest *Verbatim tool turns* evaluations. Like agent folds, sentinel folds roll, so the
  conversation stays bounded by one summary plus *Keep recent turns* evaluations. There is no
  target: every compaction runs the whole ladder.
- **How:** summaries lead with the sentinel's own system prompt (including `SECURITY.md` and the
  session's ask/unattended mode), followed by compaction instructions that require keeping user
  decisions, what the user asked for and agreed to in chat (with the agent proposal it answers),
  change requests, denials and escalations, granted contexts, suspicious agent behaviour and what inspected
  skill code does. Fold summaries are rendered with the verdicts' arguments, so the decisions reach
  the summarizer verbatim.
- **Result:** the compacted conversation replaces the persisted one. The sentinel forgets which skill
  files it was "already provided", so it reads them again in full when needed.
- **Failure:** a failing compaction fails the evaluation through the regular sentinel error path. The
  sentinel never evaluates uncompacted. The sentinel timeout covers compaction and evaluation together.
- **Visibility:** no transcript marker. The [debug view](debug-view.md) shows the request in the
  `compaction` slot with `compaction_target: sentinel`, and the compacted conversation in the
  `sentinel` slot. Usage counts under the `compaction` category.
