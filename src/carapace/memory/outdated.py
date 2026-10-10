"""Whether a stored record still matches what a fresh run would produce.

Outdated records are shown, never auto-respawned: a prompt tweak plus auto mode would otherwise
re-bill the whole archive.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.config import Config
from ..models.user import UserConfig
from ..user_defaults import effective_memory_model
from .digest_input import DIGEST_INPUT_FORMAT_VERSION
from .input import INPUT_FORMAT_VERSION
from .models import ModelRole, OutdatedReason, PeriodDigest, Provenance, SessionExtraction, TaskKind
from .prompts import MONTH_DIGEST, SESSION_EXTRACT, WEEK_DIGEST


@dataclass(frozen=True)
class CurrentVersions:
    """What a fresh run of one task kind would record."""

    model: str
    prompt_version: str
    input_format_version: int


_KINDS = {
    TaskKind.session_extract: (ModelRole.memory_low, SESSION_EXTRACT.version(SessionExtraction), INPUT_FORMAT_VERSION),
    TaskKind.week_digest: (ModelRole.memory_high, WEEK_DIGEST.version(PeriodDigest), DIGEST_INPUT_FORMAT_VERSION),
    TaskKind.month_digest: (ModelRole.memory_high, MONTH_DIGEST.version(PeriodDigest), DIGEST_INPUT_FORMAT_VERSION),
}


def current_versions(config: Config, user_config: UserConfig, kind: TaskKind) -> CurrentVersions:
    role, prompt_version, input_format_version = _KINDS[kind]
    return CurrentVersions(effective_memory_model(config, user_config, role), prompt_version, input_format_version)


def outdated_reasons(provenance: Provenance, current: CurrentVersions) -> list[OutdatedReason]:
    reasons = []
    if provenance.prompt_version != current.prompt_version:
        reasons.append(OutdatedReason.prompt_version)
    if provenance.model != current.model:
        reasons.append(OutdatedReason.model)
    if provenance.input_format_version != current.input_format_version:
        reasons.append(OutdatedReason.input_format_version)
    return reasons
