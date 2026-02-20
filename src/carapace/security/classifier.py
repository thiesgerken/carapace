from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from carapace.models import OperationClassification

_classifier_agent: Agent[None, OperationClassification] | None = None


def _get_classifier_agent(model: str) -> Agent[None, OperationClassification]:
    global _classifier_agent
    if _classifier_agent is None:
        _classifier_agent = Agent(
            model,
            output_type=OperationClassification,
            instructions=(
                "You are a security classifier for an AI agent system. "
                "Given a tool name, its arguments, and optional context, "
                "classify the operation.\n\n"
                "Operation types:\n"
                "- read_local: reading files, listing directories, read-only shell commands\n"
                "- write_local: writing/modifying local files\n"
                "- read_external: reading from the internet, APIs, external services\n"
                "- write_external: sending emails, posting to APIs, outbound communication\n"
                "- read_sensitive: reading personal data (finances, health, documents)\n"
                "- write_sensitive: modifying personal/sensitive data\n"
                "- execute: running arbitrary code or commands that modify state\n"
                "- credential_access: fetching or using credentials/secrets\n"
                "- memory_read: reading agent memory files\n"
                "- memory_write: writing/modifying agent memory files\n"
                "- skill_modify: creating, editing, or deleting skill files\n\n"
                "Categories are free-form tags like: finance, email, documents, "
                "web, skills, shell, memory, health, etc.\n\n"
                "Be precise. A shell command like 'ls' or 'cat' is read_local. "
                "A shell command like 'rm' or 'curl -X POST' is execute or write_external. "
                "Reading a file in memory/ is memory_read. Writing to memory/ is memory_write."
            ),
        )
    return _classifier_agent


async def classify_operation(
    model: str,
    tool_name: str,
    args: dict[str, Any],
    context: str = "",
) -> tuple[OperationClassification, Any]:
    """Classify an operation and return (classification, result with usage info)."""
    agent = _get_classifier_agent(model)
    prompt_parts = [f"Tool: {tool_name}", f"Arguments: {args}"]
    if context:
        prompt_parts.append(f"Context: {context}")
    prompt = "\n".join(prompt_parts)
    result = await agent.run(prompt)
    return result.output, result
