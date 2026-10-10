#!/usr/bin/env python3
"""Dev harness for the memory extraction prompt: render archived sessions, estimate, optionally run.

Takes archived ``conversation.json`` files, or directories searched recursively for them.
Sandbox workspaces hold clones of the knowledge repo, so the same session can appear many times;
each session id is kept once (the copy with the latest ``last_active``).

Default is a dry run: rendered input size, token and cost estimate per session, plus the spread.
``--call`` sends every session to the model (real money, real provider). ``--test-model`` runs
the call path against pydantic-ai's TestModel instead, for CI smoke tests.

    uv run python scripts/memory_eval.py data/sessions                     # dry run
    uv run python scripts/memory_eval.py --test-model path/to/conversation.json
    uv run python scripts/memory_eval.py --call --model anthropic:claude-haiku-4-5 --limit 3 data/

Real calls resolve the model with pydantic-ai's ``infer_model`` (provider API key from the
environment), not carapace's model registry.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from carapace.memory.budget import estimate_cost
from carapace.memory.handlers import SESSION_EXTRACT_OUTPUT_CAP
from carapace.memory.input import ExtractionInput, render_extraction_input
from carapace.memory.llm import LlmCallError, prompt_tokens, run_structured
from carapace.memory.models import SessionExtraction
from carapace.memory.prompts import SESSION_EXTRACT

DEFAULT_MODEL = "anthropic:claude-haiku-4-5"

# Valid minimal output for --test-model: TestModel's generated data would trip the Fact validators.
_TEST_OUTPUT = SessionExtraction(
    abstract="Test extraction.", outcomes=[], open_loops=[], on_my_mind=[], facts=[], friction=[], tags=[]
)


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    title: str | None
    created_at: datetime
    last_active: datetime
    events: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Prepared:
    session: Session
    rendered: ExtractionInput
    user_prompt: str
    input_tokens: int
    # Upper bound (input + full output cap) and the input share alone; real outputs are far below
    # the cap, so the truth lies in between.
    cost_usd: Decimal | None
    input_cost_usd: Decimal | None


def load_sessions(paths: list[Path]) -> list[Session]:
    files = [f for p in paths for f in (sorted(p.rglob("conversation.json")) if p.is_dir() else [p])]
    latest: dict[str, Session] = {}
    for file in files:
        payload = json.loads(file.read_text(encoding="utf-8"))
        meta = payload["session"]
        session = Session(
            session_id=meta["session_id"],
            title=meta.get("title"),
            created_at=datetime.fromisoformat(meta["created_at"]),
            last_active=datetime.fromisoformat(meta["last_active"]),
            events=payload["history"],
        )
        known = latest.get(session.session_id)
        if known is None or session.last_active > known.last_active:
            latest[session.session_id] = session
    return sorted(latest.values(), key=lambda s: s.created_at)


def prepare(session: Session, model: str) -> Prepared:
    rendered = render_extraction_input(session.events)
    # Archives carry no event timestamps, so the session's creation date stands in for the
    # first user message (the handler uses the latter, in the user's timezone).
    user_prompt = SESSION_EXTRACT.user_prompt(rendered.text, session_date=session.created_at.date().isoformat())
    input_tokens = prompt_tokens(SESSION_EXTRACT, user_prompt, model)
    return Prepared(
        session=session,
        rendered=rendered,
        user_prompt=user_prompt,
        input_tokens=input_tokens,
        cost_usd=estimate_cost(model, input_tokens, SESSION_EXTRACT_OUTPUT_CAP),
        input_cost_usd=estimate_cost(model, input_tokens, 0),
    )


def print_estimates(prepared: list[Prepared], model: str) -> None:
    print(f"model {model}, output cap {SESSION_EXTRACT_OUTPUT_CAP:,} tokens per session (upper bound)\n")
    print(f"{'session':<34} {'events':>6} {'chars':>9} {'input tok':>10} {'est. max $':>11}  title")
    for p in prepared:
        cost = f"{p.cost_usd:.4f}" if p.cost_usd is not None else "n/a"
        title = (p.session.title or "")[:40]
        print(
            f"{p.session.session_id:<34} {len(p.session.events):>6} {len(p.rendered.text):>9,} "
            f"{p.input_tokens:>10,} {cost:>11}  {title}"
        )
    extractable = [p for p in prepared if p.rendered.text]
    print(f"\n{len(prepared)} sessions, {len(prepared) - len(extractable)} without a user message (skipped)")
    if not extractable:
        return
    tokens = [p.input_tokens for p in extractable]
    print(f"input tokens: total {sum(tokens):,}, median {statistics.median(tokens):,.0f}, max {max(tokens):,}")
    costs = [p.cost_usd for p in extractable if p.cost_usd is not None]
    if costs:
        print(
            f"est. max cost: total ${sum(costs):.2f}, median ${statistics.median(costs):.4f}, "
            f"p90 ${_percentile(costs, 0.9):.4f}, max ${max(costs):.4f}"
        )
        input_costs = [p.input_cost_usd for p in extractable if p.input_cost_usd is not None]
        print(f"input share alone: total ${sum(input_costs):.2f}, median ${statistics.median(input_costs):.4f}")
    else:
        print("est. max cost: n/a (no pricing for this model)")


def _percentile(values: list[Decimal], fraction: float) -> Decimal:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


async def run_calls(prepared: list[Prepared], model: str, resolve: Model | None) -> int:
    failures = 0
    for p in prepared:
        if not p.rendered.text:
            continue
        print(f"\n=== {p.session.session_id} {p.session.title or ''}")
        try:
            call = await run_structured(
                SESSION_EXTRACT,
                SessionExtraction,
                p.user_prompt,
                model=model,
                user="eval",
                model_factory=lambda name, *, user: resolve or infer_model(name),
                model_settings=ModelSettings(max_tokens=SESSION_EXTRACT_OUTPUT_CAP),
            )
        except LlmCallError as exc:
            failures += 1
            print(f"FAILED: {exc} (billed: {exc.usage})")
            continue
        print(call.output.model_dump_json(indent=2))
        usage = call.usage
        cost = f"${usage.cost_usd:.4f}" if usage.cost_usd is not None else "n/a"
        print(f"usage: {usage.input_tokens:,} in, {usage.output_tokens:,} out, {cost}, {usage.duration_ms:,} ms")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="conversation.json files or directories")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"pydantic-ai model id (default {DEFAULT_MODEL})")
    parser.add_argument("--limit", type=int, help="only the N most recent sessions")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--call", action="store_true", help="send sessions to the real model (costs money)")
    mode.add_argument("--test-model", action="store_true", help="run the call path against TestModel")
    args = parser.parse_args()

    sessions = load_sessions(args.paths)
    if args.limit is not None:
        sessions = sessions[-args.limit :]
    prepared = [prepare(session, args.model) for session in sessions]
    print_estimates(prepared, args.model)

    if args.call or args.test_model:
        test_model = TestModel(custom_output_args=_TEST_OUTPUT.model_dump()) if args.test_model else None
        sys.exit(1 if asyncio.run(run_calls(prepared, args.model, test_model)) else 0)


if __name__ == "__main__":
    main()
