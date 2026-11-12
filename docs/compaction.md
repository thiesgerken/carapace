# Session Compaction

Long sessions eventually approach the agent model's context window. Compaction shrinks the
model history that is sent to the LLM while keeping the full human-readable transcript intact.

For the agent, carapace treats compaction the same way it treats the rest of its state: nothing is
hidden. The model sees a compacted cut, but the originals stay in the events transcript and the
Git-backed session archive, and every compaction is visible in the web UI. The sentinel's shadow
conversation is different: its compaction overwrites the persisted conversation, and only the
action log, the audit log and the latest compaction request in the [debug view](debug-view.md)
remain (see [Sentinel](#sentinel)).

> The agent's model history is compacted **manually only**, with `/compact`. The sentinel's shadow
> conversation is compacted **automatically** (see [Sentinel](#sentinel)).

## What gets compacted

Three strategies operate on different regions of the history:

| Strategy | Region | What it does |
| --- | --- | --- |
| Thinking-drop | All but the newest turn | Removes stale `thinking` parts (providers do not need them back). Free, no LLM call. |
| Tool-return compaction | Kept turns, excluding the verbatim hot zone | Summarizes large tool outputs (e.g. log/`kubectl` dumps) in place. The tool call/return pairing is preserved; the part is marked so it is never compacted twice. |
| Message-fold | Turns older than the keep-window `K` | Collapses whole turns (user + assistant + tool returns) into one summary block. |

The newest `verbatim_tool_turns` completed turns form a **verbatim hot zone**: their tool outputs are
never summarized, so the agent keeps exact fidelity on its most recent work. Tool-return compaction
only touches outputs in kept turns *older* than that zone (and never inside a fold block). Set it to
`0` to allow compacting every kept tool output, including the latest turn's.

Folds are **append-only**: each `/compact` adds a new summary block rather than re-summarizing
existing ones.

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
message, and compacted tool outputs are prefixed with a note that the full output can be obtained by
re-running the tool.

Summaries run as the agent itself: their system prompt leads with the agent's shared prefix
(`AGENTS.md`, `SOUL.md`, `USER.md`, skill catalog), followed by the compaction instructions. See
[system prompt loading](persistent-context.md#system-prompt-loading).

Compaction fails loudly. A failed or empty summary, an exhausted session budget or an input that
does not fit the compaction model aborts the whole `/compact` with a visible error, and the history
stays exactly as it was. Nothing is skipped silently.

## The `/compact` command

```
/compact            Run the full ladder: drop stale thinking → fold turns older than K → summarize big tool outputs
/compact 4          Same, but keep the last 4 completed turns verbatim
/compact fold       Only fold old turns (default K)
/compact fold 8     Only fold, keeping the last 8 turns
/compact tools      Only summarize large tool outputs in the kept region
/compact tools 1    Same, but keep only the newest 1 turn's tool outputs verbatim
```

`K` is a count of completed turns to keep verbatim. When omitted, `/compact` (and `/compact fold`)
use the configured default `keep_turns` (see Configuration below); passing a number overrides it for
that run only. For `/compact tools [N]`, `N` overrides `verbatim_tool_turns` (the hot-zone size) for
that run instead. The reply shows tokens before/after and a breakdown of what was compacted.

## Configuration

Compaction is configured per platform in **Settings → Platform** (admin only). Values are stored in
the DB-backed platform settings (the `agent` scalar row), not a config file:

| Setting | Where | Default | Meaning |
| --- | --- | --- | --- |
| Compaction | Default models | Default (title model) | Model used for fold/tool summaries (a first-level default model alongside agent/sentinel/title) |
| Keep recent turns | Compaction | 8 | Completed turns kept verbatim; also the default `K` for `/compact` |
| Verbatim tool turns | Compaction | 4 | Newest turns whose tool outputs are never summarized (`0` disables) |
| Tool-output floor (tokens) | Compaction | 4000 | Tool outputs smaller than this are left alone |
| Sentinel threshold (% of context) | Compaction | 50 | Share of the sentinel model's context window at which its shadow conversation is compacted (1 to 90) |

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
  (`N turns condensed for the model`). The chip expands to the model-facing summary text; the
  original turns render normally inside the rail.
- The [debug view](debug-view.md) shows the agent's latest request exactly as it went to the model,
  fold summaries and compacted tool returns included, and the latest compaction request itself.

The `/history` API enriches each compaction annotation with the model-facing text (`summary` for a
fold node, `model_text` for a compacted tool return) so the main view needs no second request.

## Data model

- Model history (`session_history`) holds the compacted cut: a marked synthetic message per fold,
  and shortened `ToolReturnPart`s stamped with compaction metadata (the re-compaction guard).
- The compaction tree (`session_compaction`) stores the fold summary nodes for the UI.
- The events transcript retains the originals and carries per-event compaction annotations; the
  Git archive keeps the untouched history. Compaction is therefore inspectable and reversible.

## Sentinel

The sentinel keeps its own shadow conversation (see [security.md](security.md#sentinel-state)). It is
never reset and **not** affected by `/compact`; instead it is compacted automatically.

- **When:** before each sentinel evaluation, once the conversation fills the sentinel threshold of
  the sentinel model's context window (`max_input_tokens` from the model catalog, 200k if unset).
  The estimate counts the conversation only, not the system prompt or the new evaluation request,
  which is why the threshold is capped at 90%.
- **What:** the same ladder and settings as `/compact`, with one evaluation (request, skill
  inspections, verdict) as one turn: thinking-drop, fold all but the newest *Keep recent turns*
  evaluations, then summarize large tool outputs (in practice `read_skill_file` returns) outside the
  newest *Verbatim tool turns* evaluations. Unlike agent folds, the sentinel keeps a single summary:
  each fold summarizes the earlier summary together with the newly folded evaluations, so the
  conversation stays bounded by one summary plus *Keep recent turns* evaluations.
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
