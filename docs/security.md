# Security System

Carapace gates every agent action through a two-layer security system: a fast **safe-list** bypass for known-harmless operations, and an LLM-powered **bouncer agent** for everything else. The bouncer maintains a persistent conversation per session, evaluating each action against a natural-language security policy and the full history of what happened so far.

## How it works

Every tool call and skill invocation passes through the security module before execution:

1. **Safe-list check.** A hardcoded set of tool names (reads, memory reads, skill listing) is auto-allowed without any LLM call.
2. **Bouncer evaluation.** All other operations are sent to the bouncer agent -- an LLM that receives the action log, the tool name and arguments, and makes a contextual decision.
3. **Verdict.** The bouncer returns one of three decisions:
   - **allow** -- proceed without interruption.
   - **escalate** -- pause the operation and ask the user for approval.
   - **deny** -- block the operation outright.
4. **Audit.** Every decision (safe-list or bouncer) is recorded in a per-session audit log.

```mermaid
flowchart TD
    ToolCall[Agent calls a tool / skill]
    SafeList{Tool in safe-list?}
    Bouncer["Bouncer agent evaluates action
    against SECURITY.md policy
    and session context"]
    Proceed[Operation proceeds]
    Gate["Approval Gate fires
    (sends prompt to user)"]
    Blocked[Operation blocked]

    ToolCall --> SafeList
    SafeList -->|yes| Proceed
    SafeList -->|no| Bouncer
    Bouncer -->|allow| Proceed
    Bouncer -->|escalate| Gate
    Bouncer -->|deny| Blocked
    Gate -->|user approves| Proceed
    Gate -->|user denies| Blocked
```

## SECURITY.md -- the policy file

The security policy lives in `$CARAPACE_DATA_DIR/SECURITY.md`. It is written in plain English and becomes part of the bouncer agent's system prompt. There are no rigid YAML rules to parse -- the bouncer interprets the policy with full LLM understanding.

The default policy covers:

- **General principles** -- reads are safe, writes need evaluation.
- **Shell commands** -- read-only commands are fine; scripts need scrutiny.
- **External communication** -- outbound actions require approval unless explicitly requested.
- **Memory** -- writes to persistent memory require approval.
- **Skills** -- activation is fine; modification requires approval.
- **Credentials** -- first use per session requires approval.
- **Autonomy and vigilance** -- more scrutiny when the agent has been running unattended or after consuming unsanitized external content.
- **Proxy domain requests** -- plausibility checks for network requests from sandboxed containers.

Edit `SECURITY.md` to customize the policy for your setup. The bouncer will immediately pick up changes on the next session.

## Safe-list

The following tools are auto-allowed without consulting the bouncer:

| Tool          | Reason                                         |
| ------------- | ---------------------------------------------- |
| `read`        | File reads are always safe                     |
| `write`       | Writes to the agent's scratchpad/workspace     |
| `edit`        | File edits in the agent's workspace            |
| `apply_patch` | Patch application in the agent's workspace     |
| `read_memory` | Memory reads are non-destructive               |
| `list_skills` | Listing available skills is informational      |
| `use_skill`   | Activating a skill loads trusted documentation |

The safe-list is defined in `src/carapace/security/__init__.py`.

## The bouncer agent

The bouncer is a Pydantic AI agent with its own LLM model (configured as `agent.bouncer_model` in `config.yaml`). It has two key properties:

### Shadow conversation

Instead of stateless per-call evaluations, the bouncer maintains a **persistent conversation** for each session. Each evaluation request is appended as a new message to the ongoing conversation, giving the bouncer full context of:

- All previous tool calls and their decisions
- User messages and agent responses (metadata only -- not raw tool results, to prevent prompt injection)
- Previous approvals and denials
- Skill activations

This enables nuanced judgments like "the user just confirmed this is what they want" or "the agent has been running autonomously for a while after reading external data."

The bouncer's conversation is periodically reset (configurable via `reset_threshold`) to prevent unbounded context growth. On reset, the full action log is summarized into the first message of the new conversation.

### Restricted tool access

The bouncer has read-only access to **skill directories** via two tools:

- `list_skill_files(skill_name)` -- list files in a skill directory.
- `read_skill_file(skill_name, path)` -- read a specific skill file.

This lets the bouncer inspect trusted skill code to understand what a tool invocation will actually do. Crucially, the bouncer **cannot** read the main agent's workspace -- files there may have been written by the agent and could contain prompt injection attempts.

## Action log

The action log is a per-session, append-only chronological record of all significant events:

| Entry type            | What it records                                            |
| --------------------- | ---------------------------------------------------------- |
| `UserMessageEntry`    | User sent a message (truncated preview)                    |
| `AgentResponseEntry`  | Agent generated a response (token count only)              |
| `ToolCallEntry`       | Tool was called, with decision and explanation             |
| `ToolResultEntry`     | Tool returned a result (metadata only, not content)        |
| `ApprovalEntry`       | User approved or denied an escalated action                |
| `SkillActivatedEntry` | A skill was activated (metadata only)                      |
| `UserVouchedEntry`    | User explicitly vouched for context via `/approve-context` |

The action log serves as the bouncer's primary source of truth. Raw tool results are never included -- only their metadata (size, success/failure) -- to prevent prompt injection via tool output.

## Audit log

Every security decision is written to a per-session audit log file at `$CARAPACE_DATA_DIR/sessions/<session_id>/audit.jsonl`. Each entry includes:

- Timestamp
- Whether it was a tool call or proxy domain request
- The bouncer's verdict (decision, explanation, risk level)
- The final decision (may differ if user overrode an escalation)

## Proxy domain requests

When a sandboxed container makes a network request, the proxy intercepts it and routes the domain to the security module. The bouncer evaluates whether the domain makes sense given the approved tool call that triggered it:

- A `curl` to `api.github.com` when running a git command → expected.
- A Python script connecting to an unrelated domain not mentioned in the task → suspicious.

The bouncer's system prompt explicitly tells it that the tool call itself was already approved -- domain checks are a plausibility/safety-net layer, not a second full evaluation.

If the bouncer escalates a domain request, it is forwarded to the user through their channel (WebSocket, Matrix).

## Veto semantics

Carapace follows strict veto semantics: if **any** part of the security system says "no" (or "needs approval"), that decision is final. This means:

- A safe-list bypass cannot override a bouncer denial (safe-list only applies to its own set of tools).
- The bouncer cannot override a deterministic denial from the safe-list check (which denies nothing -- it only auto-allows).
- A user denial on an escalated action is always final.

This makes the system easy to reason about: the strictest judgment always wins.

## Slash commands

Users can interact with the security system through slash commands:

| Command            | Description                                                                           |
| ------------------ | ------------------------------------------------------------------------------------- |
| `/security`        | Show the current security policy and a summary of the action log                      |
| `/approve-context` | Record a `UserVouchedEntry` in the action log, signaling trust in the current context |

## Prompt injection hardening

The bouncer is designed to resist prompt injection:

1. **No raw tool results.** The bouncer never sees file contents, API responses, or command output -- only metadata about the results.
2. **Adversarial awareness.** The bouncer's system prompt includes explicit warnings about prompt injection attempts in action log entries.
3. **Restricted file access.** The bouncer can only read trusted skill directories, not the agent's potentially compromised workspace.
4. **Structured output.** The bouncer returns a `BouncerVerdict` Pydantic model, not free-form text, reducing the attack surface for output manipulation.
