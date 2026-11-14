from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GoalInput(Input):
    name: str = Field(min_length=1, max_length=200)
    direction: str = Field(min_length=1, max_length=200)
    recruitment_type: str = ""
    constraints: dict = Field(default_factory=dict)
    preferences: dict = Field(default_factory=dict)
    operation_id: str = Field(min_length=1)


class GoalPatch(Input):
    expected_revision: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    direction: str | None = Field(default=None, min_length=1, max_length=200)
    recruitment_type: str | None = None
    constraints: dict | None = None
    preferences: dict | None = None
    archived: bool | None = None


class ProfilePatch(Input):
    expected_revision: int
    data: dict


class FactInput(Input):
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(max_length=20000)
    confirmed: bool = True
    active: bool = True
    resume_id: int | None = None
    source_ref: str = "user"
    metadata_: dict = Field(default_factory=dict)


class FactPatch(FactInput):
    expected_revision: int


class ApplicationInput(Input):
    operation_id: str = Field(min_length=1)
    company: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=300)
    job_id: int | None = None
    city: str = ""
    stage: str = Field(default="准备中", min_length=1, max_length=100)
    applied_at: str = ""
    url: str = ""
    next_action: str = ""
    next_action_at: str | None = None
    material: str = ""
    notes: str = ""

    @field_validator("applied_at")
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value


class ApplicationPatch(Input):
    expected_revision: int
    company: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    city: str | None = None
    stage: str | None = Field(default=None, min_length=1, max_length=100)
    applied_at: str | None = None
    url: str | None = None
    next_action: str | None = None
    next_action_at: str | None = None
    material: str | None = None
    notes: str | None = None
    extra: dict | None = None

    @field_validator("applied_at")
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value


class EventInput(Input):
    operation_id: str
    label: str = Field(min_length=1, max_length=100)
    state: Literal["planned", "completed", "cancelled", "skipped"] = "completed"
    occurred_at: str | None = None
    planned_at: str | None = None
    sequence: int | None = None
    data: dict = Field(default_factory=dict)


class EventPatch(Input):
    expected_revision: int
    label: str | None = None
    state: Literal["planned", "completed", "cancelled", "skipped"] | None = None
    occurred_at: str | None = None
    planned_at: str | None = None
    sequence: int | None = None
    data: dict | None = None


class ActionInput(Input):
    title: str = Field(min_length=1, max_length=500)
    application_id: int | None = None
    goal_id: int | None = None
    due_at: str | None = None
    completed: bool = False
    data: dict = Field(default_factory=dict)


class ActionPatch(Input):
    expected_revision: int
    title: str | None = Field(default=None, min_length=1, max_length=500)
    due_at: str | None = None
    completed: bool | None = None
    data: dict | None = None


class SubscriptionInput(Input):
    operation_id: str
    goal_id: int
    name: str = "每日机会检查"
    enabled: bool = True
    config: dict = Field(
        default_factory=lambda: {
            "kind": "daily",
            "time": "09:00",
            "timezone": "Asia/Shanghai",
            "channels": ["inbox"],
            "events": ["new_match"],
        }
    )


class SubscriptionPatch(Input):
    expected_revision: int
    enabled: bool | None = None
    name: str | None = None
    goal_id: int | None = None
    config: dict | None = None


class DiscoverInput(Input):
    operation_id: str
    goal_id: int
    urls: list[str] = Field(default_factory=list, max_length=20)
    mode: Literal["search", "import", "companies"] = "search"
    company_ids: list[int] = Field(default_factory=list)


class MessageInput(Input):
    operation_id: str
    content: str = Field(min_length=1, max_length=30000)
    goal_id: int | None = None


class MaterialInput(Input):
    operation_id: str
    resume_id: int


class SuggestionPatch(Input):
    expected_revision: int
    suggestions: list[dict] | None = None
    content: str | None = None


class SubmissionInput(Input):
    operation_id: str
    applied_at: str
    materials: dict
    note: str = ""


class FillInput(Input):
    operation_id: str
    executor: Literal["extension", "playwright"] = "extension"
    url: str


class SnapshotInput(Input):
    url: str
    fields: list[dict] = Field(max_length=500)
    blockers: list[str] = Field(default_factory=list)


class FillExecution(Input):
    operation_id: str
    snapshot_id: int
    selected: list[str]
    sensitive: list[str] = Field(default_factory=list)
    overwrite: list[str] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)


class SettingsPatch(Input):
    values: dict[str, Any]
