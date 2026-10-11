from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, croniter
from pydantic import BaseModel, Field, model_validator

from ..usernames import normalize_username


class JobCronTrigger(BaseModel):
    type: Literal["cron"] = "cron"
    expression: str
    timezone: str | None = Field(
        default=None,
        description="IANA time zone name such as 'UTC' or 'Europe/Berlin'.",
    )

    @model_validator(mode="after")
    def _validate_trigger(self) -> JobCronTrigger:
        expression = self.expression.strip()
        if not expression:
            raise ValueError("job cron trigger expression must not be empty")
        try:
            croniter(expression, datetime.now(tz=UTC))
        except CroniterBadCronError as exc:
            raise ValueError(f"invalid cron expression: {expression!r}") from exc
        self.expression = expression

        if self.timezone is None:
            return self
        timezone = self.timezone.strip()
        if not timezone:
            raise ValueError("job cron trigger timezone must not be empty")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                "job cron trigger timezone must be an IANA time zone name such as 'UTC' or 'Europe/Berlin'"
            ) from exc
        self.timezone = timezone
        return self


class JobDefinitionInput(BaseModel):
    id: str
    name: str
    enabled: bool = True
    triggers: Annotated[list[JobCronTrigger], Field(default_factory=list)]
    prompt: str
    private: bool = False
    unattended: bool = True
    ask_mode: bool = False
    yolo_mode: bool = False
    archive_previous_sessions: bool = False
    persistent_session_id: str | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None
    title_model_name: str | None = None
    # Sessions of this job are excluded from long-term memory unless it opts in.
    memory_enabled: bool = False

    @model_validator(mode="after")
    def _validate_job(self) -> JobDefinitionInput:
        def normalize_optional_model_name(value: str | None) -> str | None:
            if value is None:
                return None
            normalized = value.strip()
            return normalized or None

        self.id = self.id.strip()
        if not self.id:
            raise ValueError("job id must not be empty")

        self.name = self.name.strip()
        if not self.name:
            raise ValueError("job name must not be empty")

        self.prompt = self.prompt.strip()
        if not self.prompt:
            raise ValueError("job prompt must not be empty")

        self.agent_model_name = normalize_optional_model_name(self.agent_model_name)
        self.sentinel_model_name = normalize_optional_model_name(self.sentinel_model_name)
        self.title_model_name = normalize_optional_model_name(self.title_model_name)

        if self.ask_mode and self.yolo_mode:
            raise ValueError("job ask_mode and yolo_mode are mutually exclusive")

        if self.persistent_session_id is None:
            return self

        persistent_session_id = self.persistent_session_id.strip()
        if not persistent_session_id:
            raise ValueError("job persistent_session_id must not be empty when set")
        if self.unattended:
            raise ValueError("job unattended must be false when persistent_session_id is set")
        if any((self.private, self.ask_mode, self.yolo_mode)):
            raise ValueError("job session mode overrides cannot be used with persistent_session_id")
        if any((self.agent_model_name, self.sentinel_model_name, self.title_model_name)):
            raise ValueError("job model overrides cannot be used with persistent_session_id")
        if self.archive_previous_sessions:
            raise ValueError("job archive_previous_sessions cannot be used with persistent_session_id")
        self.persistent_session_id = persistent_session_id
        return self


class JobDefinition(JobDefinitionInput):
    user: str

    @model_validator(mode="after")
    def _validate_owner(self) -> JobDefinition:
        self.user = normalize_username(self.user)
        return self


class JobsFile(BaseModel):
    jobs: Annotated[list[JobDefinition], Field(default_factory=list)]

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> JobsFile:
        seen: set[str] = set()
        for job in self.jobs:
            if job.id in seen:
                raise ValueError(f"duplicate job id: {job.id}")
            seen.add(job.id)
        return self
