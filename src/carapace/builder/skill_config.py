"""skills/config.json as the Knowledge view edits it: one skill's entry at a time.

The Nix module system stays the authority on values (docs/skill-flakes.md). The check here only keeps an
obviously wrong value from becoming a commit; whatever it lets through and Nix rejects shows as that skill's
evaluation error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SettingDeclaration
from .skills_head import _git, object_id

type ConfigValue = str | int | bool

# The Nix option types of skill settings (`settingTypes` in nix/skills/default.nix), by declared name.
_TYPES: dict[str, type] = {"str": str, "int": int, "bool": bool}


class ConfigRefusedError(Exception):
    """The change cannot be made as asked; the message says why."""


@dataclass(frozen=True, slots=True)
class ConfigAtHead:
    # The Git id of skills/config.json at HEAD; empty without one.
    blob: str
    text: str
    values: dict[str, Any]


async def config_at_head(repo_dir: Path) -> ConfigAtHead:
    """skills/config.json at HEAD; no file is `{}`, as for the skills flake."""
    blob = await object_id(repo_dir, "HEAD:skills/config.json")
    if not blob:
        return ConfigAtHead(blob="", text="", values={})
    text = (await _git(repo_dir, "cat-file", "blob", blob)).decode()
    try:
        values = json.loads(text)
    except ValueError as exc:
        raise ConfigRefusedError(f"skills/config.json is not valid JSON ({exc}); fix it in the repo.") from exc
    if not isinstance(values, dict):
        raise ConfigRefusedError("skills/config.json is not a JSON object; fix it in the repo.")
    return ConfigAtHead(blob=blob, text=text, values=values)


def with_skill_entry(
    config: dict[str, Any],
    skill: str,
    *,
    enable: bool,
    settings: dict[str, ConfigValue | None],
    declared: dict[str, SettingDeclaration] | None,
) -> dict[str, Any]:
    """*config* with *skill* turned on or off and *settings* set; None resets a setting to its default.

    Other keys of the entry (credential bindings) stay as they are, and empty parts are left out, so a
    skill on its defaults has no entry at all.
    """
    for name, value in settings.items():
        # A reset needs no declaration: it also clears a value the skill no longer declares.
        if value is None:
            continue
        if declared is None:
            raise ConfigRefusedError(f"The settings of {skill} are not known until it is evaluated; try again then.")
        if name not in declared:
            raise ConfigRefusedError(f"{skill} declares no setting {name}.")
        expected = declared[name].type
        # Exact: a bool is no int here, as in Nix.
        if type(value) is not _TYPES[expected]:
            raise ConfigRefusedError(f"{skill}'s setting {name} has type {expected}, not {value!r}.")
    entry = dict(config.get(skill, {}))
    values = {name: value for name, value in {**entry.get("settings", {}), **settings}.items() if value is not None}
    entry.pop("settings", None)
    entry.pop("enable", None)
    if values:
        entry["settings"] = values
    if not enable:
        entry["enable"] = False
    rest = {name: value for name, value in config.items() if name != skill}
    return {**rest, skill: entry} if entry else rest


def config_text(config: dict[str, Any]) -> str:
    """Sorted and indented, so a commit changes only what changed whatever order the edits came in."""
    return json.dumps(config, indent=2, sort_keys=True) + "\n"
