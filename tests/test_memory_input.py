from __future__ import annotations

import hashlib
from typing import Any

import pytest

from carapace.memory.input import INPUT_FORMAT_VERSION, clamp, render_extraction_input
from carapace.usage import count_text_tokens


def _user(content: str, **extra: Any) -> dict[str, Any]:
    return {"role": "user", "content": content, **extra}


def _assistant(content: str, **extra: Any) -> dict[str, Any]:
    return {"role": "assistant", "content": content, **extra}


def test_renders_conversation_with_seq_labels() -> None:
    events = [
        _user("What is on my calendar?"),
        {"role": "tool_call", "tool": "exec", "args": {"command": "cal"}, "tool_id": "t1"},
        {"role": "tool_result", "tool": "exec", "result": "Mon: dentist", "exit_code": 0, "tool_id": "t1"},
        _assistant("You have a dentist appointment on Monday."),
    ]

    assert render_extraction_input(events).text == (
        "[#0 user]\nWhat is on my calendar?\n\n"
        '[#1 tool_call exec]\n{"command": "cal"}\n\n'
        "[#2 tool_result exec]\nMon: dentist\n\n"
        "[#3 assistant]\nYou have a dentist appointment on Monday."
    )


def test_starts_at_first_user_message_and_keeps_original_seqs() -> None:
    events = [
        _user("/model haiku"),
        {"role": "command", "command": "model", "data": {}},
        _assistant("stray text before the conversation"),
        _user("hello"),
        _assistant("hi"),
    ]

    assert render_extraction_input(events).text == "[#3 user]\nhello\n\n[#4 assistant]\nhi"


def test_drops_slash_commands_and_non_conversational_events() -> None:
    events = [
        _user("hello"),
        _user("/compact"),
        {"role": "command", "command": "compact", "data": {"ok": True}},
        {"role": "thinking", "content": "hmm"},
        {"role": "approval_request", "tool": "exec"},
        {"role": "approval_response", "approved": True},
        {"role": "credential_approval", "vault_paths": ["x"]},
        {"role": "domain_access_approval", "domain": "example.com"},
        {"role": "git_push_approval", "ref": "main"},
        _assistant(""),
        _assistant("bye"),
    ]

    assert render_extraction_input(events).text == "[#0 user]\nhello\n\n[#10 assistant]\nbye"


def test_slash_text_without_command_event_is_a_user_message() -> None:
    events = [_user("/etc/hosts is broken, fix it"), _assistant("Fixed.")]

    assert render_extraction_input(events).text == "[#0 user]\n/etc/hosts is broken, fix it\n\n[#1 assistant]\nFixed."


def test_tool_event_without_tool_name_fails_loudly() -> None:
    with pytest.raises(KeyError):
        render_extraction_input([_user("go"), {"role": "tool_call", "args": {}}])


def test_keeps_partial_assistant_text() -> None:
    events = [_user("go"), _assistant("working on it", partial=True), _assistant("done")]

    assert "[#1 assistant]\nworking on it" in render_extraction_input(events).text


def test_user_and_assistant_text_are_not_clamped() -> None:
    long = "x" * 5000
    text = render_extraction_input([_user(long), _assistant(long)]).text

    assert text == f"[#0 user]\n{long}\n\n[#1 assistant]\n{long}"


def test_attachment_placeholders_precede_user_text() -> None:
    attachments = [
        {"name": "screenshot.png", "path": "/workspace/uploads/screenshot.png", "mime": "image/png"},
        {"name": "notes.txt", "path": "/workspace/uploads/notes.txt"},
    ]
    events = [_user("see attached", attachments=attachments)]

    assert render_extraction_input(events).text == (
        "[#0 user]\n[attachment: image/png, screenshot.png]\n[attachment: notes.txt]\nsee attached"
    )


def test_attachment_only_user_message() -> None:
    events = [_user("", attachments=[{"name": "a.pdf", "path": "/p/a.pdf", "mime": "application/pdf"}])]

    assert render_extraction_input(events).text == "[#0 user]\n[attachment: application/pdf, a.pdf]"


def test_tool_call_args_are_stable_json_and_clamped() -> None:
    events = [
        _user("go"),
        {"role": "tool_call", "tool": "write", "args": {"path": "ä.txt", "content": "y" * 3000}},
    ]

    block = render_extraction_input(events).text.split("\n\n")[1]
    args_json = '{"content": "' + "y" * 3000 + '", "path": "ä.txt"}'

    assert block.startswith('[#1 tool_call write]\n{"content": "yyy')
    assert f"[… {len(args_json) - 1000:,} chars elided …]" in block
    assert block.endswith('yyy", "path": "ä.txt"}')


def test_tool_call_without_args() -> None:
    events = [_user("go"), {"role": "tool_call", "tool": "task_done"}]

    assert render_extraction_input(events).text.endswith("[#1 tool_call task_done]\n{}")


def test_tool_result_shows_nonzero_exit_code_and_clamps_output() -> None:
    output = "start\n" + "." * 2000 + "\nError: boom"
    events = [_user("go"), {"role": "tool_result", "tool": "exec", "result": output, "exit_code": 1}]

    block = render_extraction_input(events).text.split("\n\n")[1]

    assert block.startswith("[#1 tool_result exec exit=1]\nstart\n")
    assert block.endswith("\nError: boom")
    assert f"[… {len(output) - 1000:,} chars elided …]" in block


def test_tool_result_non_string_is_json() -> None:
    events = [_user("go"), {"role": "tool_result", "tool": "read", "result": {"ok": True}}]

    assert render_extraction_input(events).text.endswith('[#1 tool_result read]\n{"ok": true}')


def test_clamp_keeps_head_and_tail() -> None:
    assert clamp("a" * 1000) == "a" * 1000
    assert clamp("h" * 600 + "m" * 1 + "t" * 400) == "h" * 600 + "\n[… 1 chars elided …]\n" + "t" * 400
    clamped = clamp("h" * 600 + "m" * 12_345 + "t" * 400)
    assert clamped == "h" * 600 + "\n[… 12,345 chars elided …]\n" + "t" * 400


def test_metadata() -> None:
    result = render_extraction_input([_user("hello"), _assistant("hi")])

    assert result.input_hash == hashlib.sha256(result.text.encode()).hexdigest()
    assert result.token_estimate == count_text_tokens(result.text) > 0
    assert result.input_format_version == INPUT_FORMAT_VERSION


def test_hash_changes_when_session_continues() -> None:
    events = [_user("hello"), _assistant("hi")]

    first = render_extraction_input(events)
    again = render_extraction_input([dict(e) for e in events])
    continued = render_extraction_input([*events, _user("more"), _assistant("sure")])

    assert first.input_hash == again.input_hash
    assert first.input_hash != continued.input_hash


def test_no_user_message_renders_empty() -> None:
    result = render_extraction_input([_user("/help"), {"role": "command", "command": "help", "data": {}}])

    assert result.text == ""
    assert result.token_estimate == 0
