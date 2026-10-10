from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..database.engine import SessionFactory
from ..models.config import Config
from ..models.user import UserConfig
from ..user_defaults import effective_memory_model
from .models import (
    BudgetWindowStatus,
    DigestLevel,
    EffectiveMemoryModels,
    EstimateTotal,
    FactFilter,
    FactListResponse,
    MemoryStatus,
    ModelRole,
    PeriodDetail,
    PeriodTree,
    SessionMemoryDetail,
    SessionMemoryFilter,
    SessionMemoryListResponse,
    TaskCountResponse,
    TaskFilter,
    TaskListResponse,
    TaskRunRequest,
    TaskSelection,
    TaskSpawnRequest,
    TaskSpawnResponse,
    TaskStatus,
)

_EMPTY_ESTIMATE = EstimateTotal(
    task_count=0, input_tokens=0, output_tokens_cap=0, cost_usd=Decimal(0), unpriced_count=0
)


class MemoryService:
    """Facade the server uses for everything memory: queries, task actions and the worker loop.

    ponytail: Phase 0 skeleton. Every query returns empty data and every action is a no-op until
    the store, spawner and worker land (Phase 1).
    """

    def __init__(
        self,
        *,
        config: Config,
        session_factory: SessionFactory,
        user_config_for: Callable[[str], UserConfig],
    ) -> None:
        self._config = config
        self._session_factory = session_factory
        self._user_config_for = user_config_for

    async def run(self) -> None:
        """Worker loop: spawn, promote, claim, execute. Started once by the server lifespan."""
        raise NotImplementedError("memory worker loop lands in Phase 1")

    async def status(self, user: str) -> MemoryStatus:
        user_config = self._user_config_for(user)
        budget = user_config.memory.budget
        now = datetime.now(tz=ZoneInfo(user_config.timezone))
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        return MemoryStatus(
            auto_mode=user_config.memory.auto_mode,
            timezone=user_config.timezone,
            day=BudgetWindowStatus(
                window_start=day_start.astimezone(UTC),
                spent_cost_usd=Decimal(0),
                spent_input_tokens=0,
                limit_cost_usd=budget.cost_usd_per_day,
                limit_input_tokens=budget.input_tokens_per_day,
            ),
            month=BudgetWindowStatus(
                window_start=month_start.astimezone(UTC),
                spent_cost_usd=Decimal(0),
                spent_input_tokens=0,
                limit_cost_usd=budget.cost_usd_per_month,
                limit_input_tokens=budget.input_tokens_per_month,
            ),
            queue={status: 0 for status in TaskStatus},
            blocked=0,
            models=EffectiveMemoryModels(
                memory_low=effective_memory_model(self._config, user_config, ModelRole.memory_low),
                memory_high=effective_memory_model(self._config, user_config, ModelRole.memory_high),
            ),
        )

    async def list_tasks(self, user: str, task_filter: TaskFilter, cursor: str | None, limit: int) -> TaskListResponse:
        return TaskListResponse(items=[], next_cursor=None, total=0, estimate=_EMPTY_ESTIMATE)

    async def estimate_tasks(self, user: str, request: TaskRunRequest) -> EstimateTotal:
        return _EMPTY_ESTIMATE

    async def run_tasks(self, user: str, request: TaskRunRequest) -> TaskCountResponse:
        return TaskCountResponse(count=0)

    async def cancel_tasks(self, user: str, selection: TaskSelection) -> TaskCountResponse:
        return TaskCountResponse(count=0)

    async def retry_tasks(self, user: str, task_ids: list[int]) -> TaskCountResponse:
        return TaskCountResponse(count=0)

    async def spawn_tasks(self, user: str, request: TaskSpawnRequest) -> TaskSpawnResponse:
        return TaskSpawnResponse(task_ids=[])

    async def list_sessions(
        self, user: str, session_filter: SessionMemoryFilter, cursor: str | None, limit: int
    ) -> SessionMemoryListResponse:
        return SessionMemoryListResponse(items=[], next_cursor=None, total=0)

    async def session_detail(self, user: str, session_id: str) -> SessionMemoryDetail | None:
        """None when the session does not exist, belongs to someone else or is not eligible."""
        return None

    async def periods(self, user: str) -> PeriodTree:
        return PeriodTree(months=[])

    async def period_detail(self, user: str, level: DigestLevel, key: str) -> PeriodDetail | None:
        """None when the period key is invalid or has no sessions."""
        return None

    async def facts(self, user: str, fact_filter: FactFilter) -> FactListResponse:
        return FactListResponse(items=[])
