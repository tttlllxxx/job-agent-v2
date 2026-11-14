from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def now():
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now, onupdate=now)


class Profile(Record, Base):
    __tablename__ = "profiles"
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Fact(Record, Base):
    __tablename__ = "facts"
    key: Mapped[str] = mapped_column(index=True)
    value: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(default="user")
    confirmed: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id"))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class Goal(Record, Base):
    __tablename__ = "goals"
    name: Mapped[str] = mapped_column(String(200))
    direction: Mapped[str] = mapped_column(String(200))
    recruitment_type: Mapped[str] = mapped_column(default="")
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    archived: Mapped[bool] = mapped_column(default=False)


class Company(Record, Base):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(255), unique=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class GoalCompany(Record, Base):
    __tablename__ = "goal_companies"
    __table_args__ = (UniqueConstraint("goal_id", "company_id"),)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    reason: Mapped[str] = mapped_column(default="")
    active: Mapped[bool] = mapped_column(default=True)


class Source(Record, Base):
    __tablename__ = "sources"
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(default="")
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(default="official")
    status: Mapped[str] = mapped_column(default="unchecked")
    last_checked_at: Mapped[str | None]
    last_success_at: Mapped[str | None]
    error: Mapped[str] = mapped_column(default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Record, Base):
    __tablename__ = "jobs"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    department: Mapped[str] = mapped_column(default="")
    city: Mapped[str] = mapped_column(default="")
    recruitment_type: Mapped[str] = mapped_column(default="")
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(default="unverified")
    requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    published_at: Mapped[str | None]
    refreshed_at: Mapped[str | None]
    verified_at: Mapped[str | None]
    deadline_at: Mapped[str | None]
    program: Mapped[dict] = mapped_column(JSON, default=dict)


class JobSource(Record, Base):
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(Text)


class Evidence(Record, Base):
    __tablename__ = "evidence"
    job_source_id: Mapped[int] = mapped_column(ForeignKey("job_sources.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)


class Match(Record, Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("job_id", "goal_id"),)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    versions: Mapped[dict] = mapped_column(JSON, default=dict)
    assessment: Mapped[dict] = mapped_column(JSON, default=dict)


class Decision(Record, Base):
    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("job_id", "goal_id"),)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    value: Mapped[str] = mapped_column(default="undecided")
    reason: Mapped[str] = mapped_column(default="")


class Subscription(Record, Base):
    __tablename__ = "subscriptions"
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    name: Mapped[str] = mapped_column(default="每日机会检查")
    enabled: Mapped[bool] = mapped_column(default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    next_run_at: Mapped[str | None] = mapped_column(index=True)
    last_checked_at: Mapped[str | None]
    last_success_at: Mapped[str | None]
    initialized: Mapped[bool] = mapped_column(default=False)


class Baseline(Record, Base):
    __tablename__ = "baselines"
    __table_args__ = (UniqueConstraint("subscription_id", "job_id"),)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    reason: Mapped[str] = mapped_column(default="shown")
    job_revision: Mapped[int] = mapped_column(default=1)


class Check(Record, Base):
    __tablename__ = "checks"
    __table_args__ = (UniqueConstraint("subscription_id", "occurrence_key"),)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"))
    occurrence_key: Mapped[str] = mapped_column(String(100))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    status: Mapped[str] = mapped_column(default="queued")
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)


class JobEvent(Record, Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "kind", "job_revision"),)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    kind: Mapped[str] = mapped_column(default="new_match")
    job_revision: Mapped[int] = mapped_column(default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Intent(Record, Base):
    __tablename__ = "intents"
    __table_args__ = (UniqueConstraint("job_event_id", "subscription_id"),)
    job_event_id: Mapped[int] = mapped_column(ForeignKey("job_events.id"))
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"))
    status: Mapped[str] = mapped_column(default="pending")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Inbox(Record, Base):
    __tablename__ = "inbox"
    event_key: Mapped[str] = mapped_column(String(150), unique=True)
    title: Mapped[str] = mapped_column(default="")
    body: Mapped[str] = mapped_column(Text, default="")
    goal_reasons: Mapped[list] = mapped_column(JSON, default=list)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    seen_at: Mapped[str | None]


class Delivery(Record, Base):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("inbox_id", "channel"),)
    inbox_id: Mapped[int] = mapped_column(ForeignKey("inbox.id"))
    channel: Mapped[str] = mapped_column(default="feishu")
    status: Mapped[str] = mapped_column(default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(default="")
    sent_at: Mapped[str | None]


class Resume(Record, Base):
    __tablename__ = "resumes"
    name: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(default="text/plain")
    text: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(default=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Material(Record, Base):
    __tablename__ = "materials"
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"))
    job_revision: Mapped[int] = mapped_column(default=1)
    resume_revision: Mapped[int] = mapped_column(default=1)
    suggestions: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(default="draft")


class MaterialVersion(Record, Base):
    __tablename__ = "material_versions"
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    content: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Application(Record, Base):
    __tablename__ = "applications"
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(default="")
    stage: Mapped[str] = mapped_column(default="准备中")
    applied_at: Mapped[str] = mapped_column(default="")
    url: Mapped[str] = mapped_column(Text, default="")
    next_action: Mapped[str] = mapped_column(default="")
    next_action_at: Mapped[str | None]
    notes: Mapped[str] = mapped_column(Text, default="")
    material: Mapped[str] = mapped_column(default="")
    submitted_materials: Mapped[dict] = mapped_column(JSON, default=dict)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)


class Progress(Record, Base):
    __tablename__ = "progress"
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    label: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(default="completed")
    sequence: Mapped[int] = mapped_column(default=0)
    occurred_at: Mapped[str | None]
    planned_at: Mapped[str | None]
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Action(Record, Base):
    __tablename__ = "actions"
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"))
    title: Mapped[str] = mapped_column(String(500))
    due_at: Mapped[str | None]
    completed: Mapped[bool] = mapped_column(default=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Thread(Record, Base):
    __tablename__ = "threads"
    title: Mapped[str] = mapped_column(default="新的求职对话")
    active_goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"))
    archived: Mapped[bool] = mapped_column(default=False)
    summary: Mapped[str] = mapped_column(Text, default="")


class Message(Record, Base):
    __tablename__ = "messages"
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Run(Record, Base):
    __tablename__ = "runs"
    kind: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(default="queued", index=True)
    phase: Mapped[str] = mapped_column(default="")
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"))
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("threads.id"))
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    cancellation_requested: Mapped[bool] = mapped_column(default=False)


class Step(Record, Base):
    __tablename__ = "steps"
    __table_args__ = (UniqueConstraint("run_id", "operation_key"),)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    operation_key: Mapped[str] = mapped_column(String(500))
    tool: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(default="running")
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Record, Base):
    __tablename__ = "events"
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    type: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class FillSession(Record, Base):
    __tablename__ = "fill_sessions"
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    executor: Mapped[str] = mapped_column(default="extension")
    status: Mapped[str] = mapped_column(default="needs_scan")
    pages: Mapped[list] = mapped_column(JSON, default=list)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)


class Snapshot(Record, Base):
    __tablename__ = "snapshots"
    fill_session_id: Mapped[int] = mapped_column(ForeignKey("fill_sessions.id"))
    url: Mapped[str] = mapped_column(Text)
    fields: Mapped[list] = mapped_column(JSON, default=list)
    preview: Mapped[list] = mapped_column(JSON, default=list)
    blockers: Mapped[list] = mapped_column(JSON, default=list)


class Approval(Record, Base):
    __tablename__ = "approvals"
    fill_session_id: Mapped[int] = mapped_column(ForeignKey("fill_sessions.id"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    operation_id: Mapped[str] = mapped_column(String(150), unique=True)
    kind: Mapped[str] = mapped_column(default="fill")
    status: Mapped[str] = mapped_column(default="pending")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[object] = mapped_column(JSON)
    secret: Mapped[bool] = mapped_column(default=False)


class Operation(Base):
    __tablename__ = "operations"
    key: Mapped[str] = mapped_column(primary_key=True)
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)


class Legacy(Base):
    __tablename__ = "legacy_records"
    __table_args__ = (UniqueConstraint("source_table", "source_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_table: Mapped[str] = mapped_column(String(100))
    source_id: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSON)


def make_engine(url):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        if url.startswith("sqlite"):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=10000")

    return engine


engine = make_engine(settings().database_url)
Session = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with Session() as db:
        yield db


def serialize(row):
    return {
        column.key: getattr(row, column.key) for column in row.__mapper__.column_attrs
    }


class Attachment(Record, Base):
    __tablename__ = "attachments"
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id"))
    name: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(default="application/octet-stream")
    kind: Mapped[str] = mapped_column(default="attachment")
    confirmed: Mapped[bool] = mapped_column(default=False)


class Usage(Record, Base):
    __tablename__ = "usages"
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    model: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    estimated_rmb: Mapped[float | None]
