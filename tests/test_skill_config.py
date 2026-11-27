"""Editing one skill's entry in skills/config.json: typed like the Nix options, sorted, empty parts pruned."""

from __future__ import annotations

from typing import Any

import pytest

from carapace.builder.models import CredentialSlotDeclaration, SettingDeclaration, SkillDeclarations
from carapace.builder.skill_config import ConfigRefusedError, config_text, with_skill_entry

_DECLARED = SkillDeclarations(
    settings={
        "CITY": SettingDeclaration(type="str", description="City to report on", default="Berlin"),
        "DAYS": SettingDeclaration(type="int", description="Days ahead"),
        "METRIC": SettingDeclaration(type="bool", default=True),
    },
    credentials={"API_KEY": CredentialSlotDeclaration(type="secret", description="Weather API key")},
)


def _edit(
    config: dict[str, Any],
    *,
    enable: bool = True,
    settings: dict[str, Any] | None = None,
    credentials: dict[str, str | None] | None = None,
    declarations: SkillDeclarations | None = _DECLARED,
) -> dict[str, Any]:
    return with_skill_entry(
        config,
        "weather",
        enable=enable,
        settings=settings or {},
        credentials=credentials or {},
        declarations=declarations,
    )


def test_a_setting_is_set_and_reset_and_other_keys_stay() -> None:
    config = {"weather": {"credentials": {"API_KEY": "bitwarden/abc"}}, "notes": {"enable": False}}

    changed = _edit(config, settings={"DAYS": 3})
    reset = _edit(changed, settings={"DAYS": None})

    assert changed == {
        "weather": {"credentials": {"API_KEY": "bitwarden/abc"}, "settings": {"DAYS": 3}},
        "notes": {"enable": False},
    }
    assert reset == config


def test_a_skill_on_its_defaults_has_no_entry() -> None:
    config = {"weather": {"enable": False, "settings": {"CITY": "Hamburg"}}}

    assert _edit(config, settings={"CITY": None}) == {}


def test_turning_a_skill_off_needs_no_declarations() -> None:
    assert _edit({}, enable=False, declarations=None) == {"weather": {"enable": False}}


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"DAYS": True}, "DAYS has type int, not True"),
        ({"DAYS": "3"}, "DAYS has type int, not '3'"),
        ({"METRIC": 1}, "METRIC has type bool, not 1"),
        ({"CITY": 7}, "CITY has type str, not 7"),
        ({"COUNTRY": "DE"}, "declares no setting COUNTRY"),
    ],
)
def test_a_value_the_declaration_rules_out_is_refused(settings: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigRefusedError, match=message):
        _edit({}, settings=settings)


def test_a_value_waits_for_the_declarations_but_a_reset_does_not() -> None:
    with pytest.raises(ConfigRefusedError, match="not known until it is evaluated"):
        _edit({}, settings={"CITY": "Kiel"}, declarations=None)

    # Clearing a value the skill no longer declares, so the module system stops rejecting it.
    stale = {"weather": {"settings": {"GONE": "x"}}}
    assert _edit(stale, settings={"GONE": None}) == {}


def test_the_file_is_sorted_whatever_order_the_edits_came_in() -> None:
    assert config_text({"b": {"settings": {"Z": 1, "A": 2}}, "a": {"enable": False}}) == (
        '{\n  "a": {\n    "enable": false\n  },\n'
        '  "b": {\n    "settings": {\n      "A": 2,\n      "Z": 1\n    }\n  }\n}\n'
    )


def test_a_credential_slot_is_bound_and_unbound() -> None:
    config = {"weather": {"settings": {"DAYS": 3}}}

    bound = _edit(config, credentials={"API_KEY": "personal/abc"})
    unbound = _edit(bound, credentials={"API_KEY": None}, declarations=None)

    assert bound == {"weather": {"settings": {"DAYS": 3}, "credentials": {"API_KEY": "personal/abc"}}}
    assert unbound == config


@pytest.mark.parametrize(
    ("credentials", "message"),
    [
        ({"API_KEY": "no-slash"}, "takes a vault path <backend>/<id>"),
        ({"API_KEY": "personal/with space"}, "takes a vault path <backend>/<id>"),
        ({"TOKEN": "personal/abc"}, "declares no credential slot TOKEN"),
    ],
)
def test_a_binding_the_slot_rules_out_is_refused(credentials: dict[str, str | None], message: str) -> None:
    with pytest.raises(ConfigRefusedError, match=message):
        _edit({}, credentials=credentials)
