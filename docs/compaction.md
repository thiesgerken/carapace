# Session Compaction

Long sessions eventually approach the agent model's context window. Compaction shrinks the
model history that is sent to the LLM while keeping the full human-readable transcript intact.

carapace treats compaction the same way it treats the rest of its state: nothing is hidden. The
model sees a compacted cut, but the originals stay in the events transcript and the Git-backed
session archive, and every compaction is visible in the web UI.

> v1 is **manual only** — you trigger it with `/compact`. There is no automatic trigger yet.

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
existing ones, so summaries do not drift through repeated compaction. Adjacent blocks can later be
merged by a consolidation pass when they themselves grow large (a "tree" of summaries).

The model is always told that content was compacted: folded blocks become a clearly marked summary
message, and compacted tool outputs are prefixed with a note that the full output can be obtained by
re-running the tool.

Summaries run as the agent itself: their system prompt leads with the agent's shared prefix
(`AGENTS.md`, `SOUL.md`, `USER.md`, skill catalog), followed by the compaction instructions. See
[system prompt loading](persistent-context.md#system-prompt-loading).

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
| Tool-output floor (tokens) | Compaction | 500 | Tool outputs smaller than this are left alone |

The compaction model is a separate, configurable default model (a cheap/haiku-class model is a good
default); leaving it on "Default" reuses the title model. Its usage is tracked under the
`compaction` category, separate from the agent. Tool-output summaries run concurrently, bounded by
the shared `agent.max_parallel_llm` limit. Code defaults live in `agent.compaction_model` and
`agent.compaction` (`AgentConfig` / `CompactionConfig`).

The platform default is just a default: each session can override the compaction model like the
other roles with `/model compaction NAME` (and `/model NAME` switches all four roles at once, while
`/model compaction reset` returns to the default). Per-user defaults live under
`default_models.compaction` in the user config.

## Viewing compaction in the UI

The main view always shows the **original, uncompacted** conversation — compaction is surfaced as a
subtle marker plus an on-demand peek at what the model actually sees, never by hiding the originals.

- **Compacted tool rows** show a `compacted` badge; expanding the row reveals a **"Model sees"**
  disclosure with the shortened tool output and token savings, alongside the full original output.
- **Folded turns** stay inline and expanded, wrapped in a left **margin rail** with a header chip
  (`N turns condensed for the model`). The chip expands to the model-facing summary text; the
  original turns render normally inside the rail.
- **Agent view** (the eye icon in the session inspector) opens a read-only overlay rendering the
  model history exactly as the agent sees it: fold summaries in place of folded turns and short-form
  compacted tool returns. Useful for debugging what the model actually receives.

The `/history` API enriches each compaction annotation with the model-facing text (`summary` for a
fold node, `model_text` for a compacted tool return) so the main view needs no second request.

## Data model

- Model history (`session_history`) holds the compacted cut: a marked synthetic message per fold,
  and shortened `ToolReturnPart`s stamped with compaction metadata (the re-compaction guard).
- The compaction tree (`session_compaction`) stores the summary nodes for the UI and consolidation.
- The events transcript retains the originals and carries per-event compaction annotations; the
  Git archive keeps the untouched history. Compaction is therefore inspectable and reversible.

## Sentinel

The sentinel (security agent) keeps its own shadow conversation, which is bounded by its existing
reset threshold and is **not** affected by `/compact` in v1.
