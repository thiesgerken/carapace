"""Editing one skill's entry in skills/config.json: typed like the Nix options, sorted, empty parts pruned."""

from __future__ import annotations

import pytest

from carapace.builder.models import SettingDeclaration
from carapace.builder.skill_config import ConfigRefusedError, config_text, with_skill_entry

_DECLARED = {
    "CITY": SettingDeclaration(type="str", description="City to report on", default="Berlin"),
    "DAYS": SettingDeclaration(type="int", description="Days ahead"),
    "METRIC": SettingDeclaration(type="bool", default=True),
}


def test_a_setting_is_set_and_reset_and_other_keys_stay() -> None:
    config = {"weather": {"credentials": {"API_KEY": "bitwarden/abc"}}, "notes": {"enable": False}}

    changed = with_skill_entry(config, "weather", enable=True, settings={"DAYS": 3}, declared=_DECLARED)
    reset = with_skill_entry(changed, "weather", enable=True, settings={"DAYS": None}, declared=_DECLARED)

    assert changed == {
        "weather": {"credentials": {"API_KEY": "bitwarden/abc"}, "settings": {"DAYS": 3}},
        "notes": {"enable": False},
    }
    assert reset == config


def test_a_skill_on_its_defaults_has_no_entry() -> None:
    config = {"weather": {"enable": False, "settings": {"CITY": "Hamburg"}}}

    assert with_skill_entry(config, "weather", enable=True, settings={"CITY": None}, declared=_DECLARED) == {}


def test_turning_a_skill_off_needs_no_declarations() -> None:
    assert with_skill_entry({}, "weather", enable=False, settings={}, declared=None) == {"weather": {"enable": False}}


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
        with_skill_entry({}, "weather", enable=True, settings=settings, declared=_DECLARED)  # pyrefly: ignore


def test_a_value_waits_for_the_declarations_but_a_reset_does_not() -> None:
    with pytest.raises(ConfigRefusedError, match="not known until it is evaluated"):
        with_skill_entry({}, "weather", enable=True, settings={"CITY": "Kiel"}, declared=None)

    # Clearing a value the skill no longer declares, so the module system stops rejecting it.
    stale = {"weather": {"settings": {"GONE": "x"}}}
    assert with_skill_entry(stale, "weather", enable=True, settings={"GONE": None}, declared=_DECLARED) == {}


def test_the_file_is_sorted_whatever_order_the_edits_came_in() -> None:
    assert config_text({"b": {"settings": {"Z": 1, "A": 2}}, "a": {"enable": False}}) == (
        '{\n  "a": {\n    "enable": false\n  },\n'
        '  "b": {\n    "settings": {\n      "A": 2,\n      "Z": 1\n    }\n  }\n}\n'
    )
