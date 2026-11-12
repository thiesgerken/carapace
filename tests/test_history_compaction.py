"""Compaction inside a pydantic-ai run, through the history compaction capability."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from carapace.agent.history_compaction import HistoryCompactionCapability
from carapace.session.compaction import fold_summary_text, is_fold_message, make_fold_message
from carapace.usage import ProviderCostCapability


@pytest.mark.anyio
async def test_compacted_history_reaches_the_request_and_the_rest_of_the_run() -> None:
    seen: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        step = sum(isinstance(m, ModelResponse) for m in messages)
        parts = [ToolCallPart("work", {"n": step})] if len(seen) < 4 else [TextPart("done")]
        return ModelResponse(parts=parts, provider_details={"cost": "0.01"})

    async def compact(messages: list[ModelMessage]) -> list[ModelMessage] | None:
        # Fold everything before the newest step once the run has made three tool calls.
        if len(seen) != 3:
            return None
        newest_step = max(i for i, m in enumerate(messages) if isinstance(m, ModelResponse))
        return [make_fold_message("SUMMARY"), *messages[newest_step:]]

    agent = Agent(FunctionModel(respond), capabilities=[HistoryCompactionCapability(compact)])

    @agent.tool_plain
    def work(n: int) -> str:
        return f"worked {n}"

    provider_cost = ProviderCostCapability()
    result = await agent.run("start", capabilities=[provider_cost])

    assert result.output == "done"
    fourth_request = seen[3]
    assert is_fold_message(fourth_request[0]) and fold_summary_text(fourth_request[0]) == "SUMMARY"
    assert not any(
        isinstance(p, ToolCallPart) and p.args_as_dict() == {"n": 0} for m in fourth_request for p in m.parts
    )
    history = result.all_messages()
    assert is_fold_message(history[0])
    assert sum(isinstance(m, ModelRequest) and is_fold_message(m) for m in history) == 1
    # Four responses were billed, two of them folded away before the run ended.
    assert provider_cost.total_usd == Decimal("0.04")
