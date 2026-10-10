from __future__ import annotations

from .memory.models import ModelRole
from .models.config import Config
from .models.session import SessionBudget, SessionState
from .models.user import UserConfig


def effective_user_budget(config: Config, user_config: UserConfig) -> SessionBudget:
    if user_config.budgets.has_any_limit:
        return user_config.budgets.model_copy(deep=True)
    return config.agent.default_session_budget.model_copy(deep=True)


def apply_user_model_defaults(state: SessionState, user_config: UserConfig) -> None:
    defaults = user_config.default_models
    if defaults.agent is not None:
        state.agent_model_name = defaults.agent
    if defaults.sentinel is not None:
        state.sentinel_model_name = defaults.sentinel
    if defaults.title is not None:
        state.title_model_name = defaults.title
    if defaults.compaction is not None:
        state.compaction_model_name = defaults.compaction


def apply_job_model_defaults(
    state: SessionState,
    user_config: UserConfig,
    *,
    agent_model_name: str | None,
    sentinel_model_name: str | None,
    title_model_name: str | None,
) -> None:
    defaults = user_config.default_models
    state.agent_model_name = agent_model_name or defaults.agent
    state.sentinel_model_name = sentinel_model_name or defaults.sentinel
    state.title_model_name = title_model_name or defaults.title
    state.compaction_model_name = defaults.compaction


def effective_memory_model(config: Config, user_config: UserConfig, role: ModelRole) -> str:
    agent = config.agent
    match role:
        case ModelRole.memory_low:
            return (
                user_config.default_models.memory_low
                or agent.memory_low_model
                or agent.compaction_model
                or agent.title_model
            )
        case ModelRole.memory_high:
            return user_config.default_models.memory_high or agent.memory_high_model or agent.model
