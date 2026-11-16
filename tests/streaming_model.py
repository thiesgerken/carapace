from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, ModelResponseStreamEvent
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext


class ReplayStreamModel(FunctionModel):
    """A ``FunctionModel`` whose streamed requests replay the function's whole response at once.

    ``LlmRequestLogCapability`` makes every run stream, and ``FunctionModel``'s own stream function
    cannot carry usage, provider details or compaction parts the tests assert on.
    """

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        response = await self.request(messages, model_settings, model_request_parameters)
        yield _ReplayedResponse(model_request_parameters=model_request_parameters, response=response)


@dataclass
class _ReplayedResponse(StreamedResponse):
    response: ModelResponse

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        self._usage = self.response.usage
        self.provider_details = self.response.provider_details
        self.provider_response_id = self.response.provider_response_id
        self.finish_reason = self.response.finish_reason
        for index, part in enumerate(self.response.parts):
            yield self._parts_manager.handle_part(vendor_part_id=index, part=part)

    async def close_stream(self) -> None:
        pass

    @property
    def model_name(self) -> str:
        return self.response.model_name or ""

    @property
    def provider_name(self) -> str | None:
        return self.response.provider_name

    @property
    def provider_url(self) -> str | None:
        return self.response.provider_url

    @property
    def timestamp(self) -> datetime:
        return self.response.timestamp
