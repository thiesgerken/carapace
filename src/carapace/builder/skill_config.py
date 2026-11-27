"""skills/config.json as the Knowledge view edits it: one skill's entry at a time.

The Nix module system stays the authority on values (docs/skill-flakes.md). The check here only keeps an
obviously wrong value from becoming a commit; whatever it lets through and Nix rejects shows as that skill's
evaluation error.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SkillDeclarations
from .skills_head import _git, object_id

type ConfigValue = str | int | bool

# The Nix option types of skill settings (`settingTypes` in nix/skills/default.nix), by declared name.
_TYPES: dict[str, type] = {"str": str, "int": int, "bool": bool}
# A credential binding, as the Nix option checks it (`credentials` in nix/skills/default.nix).
_VAULT_PATH = re.compile(r"[^/\s]+/\S+")


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
    credentials: dict[str, str | None],
    declarations: SkillDeclarations | None,
) -> dict[str, Any]:
    """*config* with *skill* turned on or off and *settings* and *credentials* set; None resets one.

    Other keys of the entry stay as they are, and empty parts are left out, so a skill on its defaults has
    no entry at all.
    """
    if declarations is None and any(value is not None for value in [*settings.values(), *credentials.values()]):
        raise ConfigRefusedError(f"What {skill} declares is not known until it is evaluated; try again then.")
    for name, value in settings.items():
        # A reset needs no declaration: it also clears a value the skill no longer declares.
        if value is None:
            continue
        assert declarations is not None
        if name not in declarations.settings:
            raise ConfigRefusedError(f"{skill} declares no setting {name}.")
        expected = declarations.settings[name].type
        # Exact: a bool is no int here, as in Nix.
        if type(value) is not _TYPES[expected]:
            raise ConfigRefusedError(f"{skill}'s setting {name} has type {expected}, not {value!r}.")
    for slot, path in credentials.items():
        if path is None:
            continue
        assert declarations is not None
        if slot not in declarations.credentials:
            raise ConfigRefusedError(f"{skill} declares no credential slot {slot}.")
        if not _VAULT_PATH.fullmatch(path):
            raise ConfigRefusedError(
                f"{skill}'s credential slot {slot} takes a vault path <backend>/<id>, not {path!r}."
            )
    current = skill_entry(config, skill)
    entry = {key: value for key, value in current.items() if key not in ("enable", "settings", "credentials")}
    entry |= _merged(current, "settings", settings) | _merged(current, "credentials", credentials)
    if not enable:
        entry["enable"] = False
    rest = {name: value for name, value in config.items() if name != skill}
    return {**rest, skill: entry} if entry else rest


def skill_entry(config: dict[str, Any], skill: str) -> dict[str, Any]:
    """*skill*'s entry, `{}` without one; refused unless it and its parts are JSON objects."""
    entry = config.get(skill, {})
    if not isinstance(entry, dict) or any(
        not isinstance(entry.get(part, {}), dict) for part in ("settings", "credentials")
    ):
        raise ConfigRefusedError(f"The entry of {skill} in skills/config.json is malformed; fix it in the repo.")
    return entry


def _merged(entry: dict[str, Any], part: str, changes: dict[str, Any]) -> dict[str, Any]:
    """*entry*'s *part* with *changes* applied, as `{part: …}`, or nothing when it ends up empty."""
    values = {name: value for name, value in {**entry.get(part, {}), **changes}.items() if value is not None}
    return {part: values} if values else {}


def config_text(config: dict[str, Any]) -> str:
    """Sorted and indented, so a commit changes only what changed whatever order the edits came in."""
    return json.dumps(config, indent=2, sort_keys=True) + "\n"
