from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic_ai.messages import ModelRequest, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel

from carapace.config import build_config
from carapace.llm import SlotLimitedModel
from carapace.security.sentinel import Sentinel
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel

_PROMPT = [ModelRequest(parts=[UserPromptPart(content="hi")])]


def test_slot_limited_model_waits_for_a_free_slot() -> None:
    async def _run() -> None:
        slots = asyncio.Semaphore(1)
        model = SlotLimitedModel(TestModel(custom_output_text="ok"), slots)

        await slots.acquire()
        request = asyncio.create_task(model.request(_PROMPT, None, ModelRequestParameters()))
        await asyncio.sleep(0.01)
        assert not request.done()

        slots.release()
        response = await asyncio.wait_for(request, timeout=1)
        assert response.parts == [TextPart(content="ok")]
        assert not slots.locked()

    asyncio.run(_run())


def test_slot_limited_model_holds_the_slot_only_while_streaming() -> None:
    async def _run() -> None:
        slots = asyncio.Semaphore(1)
        model = SlotLimitedModel(TestModel(custom_output_text="ok"), slots)

        async with model.request_stream(_PROMPT, None, ModelRequestParameters()) as stream:
            assert slots.locked()
            async for _event in stream:
                pass
        assert not slots.locked()

    asyncio.run(_run())


def test_turns_waiting_outside_model_requests_do_not_block_other_sessions(tmp_path: Path, db_factory) -> None:
    """With one LLM slot, a turn parked on an approval and a turn running a long tool hold no
    slot, so another session's model request still goes through."""

    async def _run() -> None:
        config = build_config(tmp_path)
        config.agent.max_parallel_llm = 1
        engine = _make_engine(tmp_path, session_factory=db_factory, config=config)
        parked = asyncio.Event()

        async def _fake_run_agent_turn(
            user_input: str, deps: Any, _history: list[Any], **_kwargs: Any
        ) -> tuple[list[Any], str, str, None]:
            if user_input != "answer me":
                # Stand-in for collect_approvals or a long exec: the turn is busy between requests.
                await parked.wait()
                return [], "late", "", None
            response = await deps.agent_model.request(_PROMPT, None, ModelRequestParameters())
            return [], response.parts[0].content, "", None

        subscribers: dict[str, _FakeSubscriber] = {}
        for prompt in ("waiting for approval", "running a long tool", "answer me"):
            sid = engine.session_mgr.create_session(user="thies").session_id
            engine.get_or_activate(sid).agent_model = TestModel(custom_output_text="ok")
            subscribers[prompt] = _FakeSubscriber()
            engine.subscribe(sid, subscribers[prompt])
            with patch("carapace.session.engine.run_agent_turn", new=_fake_run_agent_turn):
                await engine.submit_message(sid, prompt)
                await asyncio.sleep(0.05)

        try:
            assert [content for content, _usage in subscribers["answer me"].done_messages] == ["ok"]
        finally:
            parked.set()
            await asyncio.sleep(0.05)

    with _patch_sentinel():
        asyncio.run(_run())


def test_sentinel_requests_take_an_llm_slot(tmp_path: Path) -> None:
    async def _run() -> None:
        slots = asyncio.Semaphore(1)
        sentinel = Sentinel(
            model="test:model",
            user="thies",
            knowledge_dir=tmp_path,
            skills_dir=tmp_path / "skills",
            llm_slots=slots,
            model_factory=lambda _name, *, user: TestModel(),
        )

        await slots.acquire()
        run = asyncio.create_task(sentinel.agent.run("review", deps=tmp_path / "skills"))
        await asyncio.sleep(0.01)
        assert not run.done()

        slots.release()
        await asyncio.wait_for(run, timeout=1)

    asyncio.run(_run())


def test_engine_gives_sentinels_the_shared_llm_slots(tmp_path: Path, db_factory) -> None:
    with _patch_sentinel() as sentinel_cls:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        engine.get_or_activate(engine.session_mgr.create_session(user="thies").session_id)

    assert sentinel_cls.call_args.kwargs["llm_slots"] is engine._llm_semaphore
