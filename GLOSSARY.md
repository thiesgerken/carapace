# carapace

A security-first personal AI agent: every action the agent takes is gated by a second LLM, and
everything either of them sees stays inspectable.

## Sessions

**Session**:
One conversation between a user and the agent, with its own sandbox, security state and history.
_Avoid_: Chat, thread

**Transcript**:
The complete, human-readable record of a session as the user experienced it. Never compacted.
_Avoid_: Event log, chat history

**Model History**:
The conversation as the agent receives it, which may be compacted.
_Avoid_: Agent history, context

**Rewind**:
Cutting a session back to an earlier turn, discarding the turns after it from transcript and model
history. Side effects in the sandbox are not undone.
_Avoid_: Reset, undo

**Fork**:
A new session that starts as a copy of another session up to a chosen turn.
_Avoid_: Clone, branch

**Compaction**:
Shrinking a model history or shadow conversation so it fits the model. For a model history the
transcript keeps the originals; a shadow conversation is overwritten, and the action log remains.
_Avoid_: Summarization, truncation

## Agent roles

**Agent Role**:
One of the LLM roles that work on a session: agent, sentinel, titler and compaction.
_Avoid_: Source, LLM type

**Agent**:
The role that talks to the user and calls tools.
_Avoid_: Main agent, assistant

**Sentinel**:
The role that decides whether an agent action is allowed, denied or escalated to the user.
_Avoid_: Security agent, gatekeeper, guard

## Security

**Action Log**:
The append-only record of what happened in a session, as the sentinel is told about it: user
messages, agent actions, sentinel verdicts and user decisions.
_Avoid_: Audit log (that is the separate record of final security decisions)

**Shadow Conversation**:
The sentinel's own conversation within a session: its evaluations, its skill inspections and its
verdicts.
_Avoid_: Sentinel history

**Sentinel State**:
Everything the sentinel knows about a session: its shadow conversation and the action log.

**User Decision**:
A user approving or denying an action that the sentinel escalated.
_Avoid_: Approval (ambiguous with sentinel allows)

## Debugging

**LLM Context**:
The exact content of one request to a model: instructions, messages including tool calls and tool
returns, and tool definitions, together with the model's response.
_Avoid_: Prompt, history

**Debug View**:
The per-session view that shows the latest LLM context of every agent role, live.
_Avoid_: Agent view, inspector
