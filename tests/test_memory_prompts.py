from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import BaseModel

from carapace.memory.prompts import MONTH_DIGEST, SESSION_EXTRACT, WEEK_DIGEST, PromptTemplate


class _Output(BaseModel):
    abstract: str


class _OtherOutput(BaseModel):
    abstract: str
    tags: list[str]


ALL_TEMPLATES = [SESSION_EXTRACT, WEEK_DIGEST, MONTH_DIGEST]


def test_user_prompt_sandwiches_payload_between_context_and_tail() -> None:
    prompt = SESSION_EXTRACT.user_prompt("[#0 user]\nhello", context="Session date: 2026-09-02")

    assert prompt == (
        f"Session date: 2026-09-02\n\n<transcript>\n[#0 user]\nhello\n</transcript>\n\n{SESSION_EXTRACT.tail}"
    )


def test_version_is_stable_and_short() -> None:
    assert SESSION_EXTRACT.version(_Output) == SESSION_EXTRACT.version(_Output)
    assert len(SESSION_EXTRACT.version(_Output)) == 12


@pytest.mark.parametrize(
    "changed",
    [
        replace(SESSION_EXTRACT, system=SESSION_EXTRACT.system + " "),
        replace(SESSION_EXTRACT, tag="session"),
        replace(SESSION_EXTRACT, tail=SESSION_EXTRACT.tail + " "),
    ],
)
def test_version_changes_with_any_prompt_part(changed: PromptTemplate) -> None:
    assert changed.version(_Output) != SESSION_EXTRACT.version(_Output)


def test_version_changes_with_output_schema() -> None:
    assert SESSION_EXTRACT.version(_Output) != SESSION_EXTRACT.version(_OtherOutput)


def test_templates_have_distinct_versions() -> None:
    assert len({t.version(_Output) for t in ALL_TEMPLATES}) == len(ALL_TEMPLATES)


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_tail_names_the_delimiter(template: PromptTemplate) -> None:
    assert f"<{template.tag}>…</{template.tag}>" in template.tail
