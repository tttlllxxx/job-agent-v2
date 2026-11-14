import asyncio
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, or_, select

from . import schemas as S
from .common import commit_operation, existing_operation, get, revise
from .config import settings
from .database import (
    Action,
    Application,
    Approval,
    Check,
    Company,
    Decision,
    Delivery,
    Event,
    Evidence,
    Fact,
    FillSession,
    Goal,
    GoalCompany,
    Inbox,
    Job,
    JobSource,
    Legacy,
    Material,
    MaterialVersion,
    Message,
    Operation,
    Profile,
    Progress,
    Resume,
    Run,
    Setting,
    Snapshot,
    Source,
    Subscription,
    Thread,
    get_db,
    now,
    serialize,
)
from .services import (
    append_progress,
    company_out,
    create_run,
    job_out,
    project_application,
    setting,
)

router = APIRouter(prefix="/api")


def data_patch(payload):
    return payload.model_dump(
        exclude_unset=True, exclude={"expected_revision", "operation_id"}
    )


def request_data(payload, kind, object_id=None):
    return {
        "kind": kind,
        "id": object_id,
        **payload.model_dump(exclude={"operation_id"}),
    }


@router.get("/status")
def status(db=Depends(get_db)):
    from .providers import model_config

    config = model_config(db)
    return {
        "version": "2.0.0",
        "local": True,
        "model_ready": bool(
            config.get("model")
            and (config.get("kind") == "codex" or config.get("api_key"))
        ),
        "search_ready": bool(setting(db, "search_api_key", settings().search_api_key)),
        "migration": setting(db, "migration_complete"),
        "profile_revision": get(db, Profile, 1).revision,
    }


@router.get("/workspace")
def workspace(db=Depends(get_db)):
    return {
        "actions": [
            serialize(row)
            for row in db.scalars(
                select(Action)
                .where(Action.completed.is_(False))
                .order_by(Action.due_at, Action.id)
            )
        ],
        "inbox": [
            serialize(row)
            for row in db.scalars(
                select(Inbox)
                .where(Inbox.seen_at.is_(None))
                .order_by(Inbox.id.desc())
                .limit(20)
            )
        ],
        "runs": [
            serialize(row)
            for row in db.scalars(
                select(Run)
                .where(
                    Run.status.in_(
                        ["queued", "running", "waiting_user", "result_unknown"]
                    )
                )
                .order_by(Run.id.desc())
                .limit(20)
            )
        ],
        "subscriptions": [serialize(row) for row in db.scalars(select(Subscription))],
        "counts": {
            "applications": db.scalar(select(func.count()).select_from(Application)),
            "jobs": db.scalar(select(func.count()).select_from(Job)),
            "goals": db.scalar(
                select(func.count()).select_from(Goal).where(Goal.archived.is_(False))
            ),
        },
    }


@router.get("/profile")
def get_profile(db=Depends(get_db)):
    return serialize(get(db, Profile, 1))


@router.patch("/profile")
def patch_profile(payload: S.ProfilePatch, db=Depends(get_db)):
    year = payload.data.get("graduation_year")
    if year and (not str(year).isdigit() or not 1900 <= int(year) <= 2100):
        raise HTTPException(422, "毕业年份不正确")
    for key in ["days_per_week", "duration_months"]:
        if payload.data.get(key) is not None:
            try:
                if float(payload.data[key]) < 0:
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(422, "到岗天数或时长不正确")
    row = revise(get(db, Profile, 1), {"data": payload.data}, payload.expected_revision)
    db.commit()
    return serialize(row)


@router.get("/facts")
def list_facts(resume_id: int | None = None, db=Depends(get_db)):
    query = select(Fact).order_by(Fact.id)
    if resume_id:
        query = query.where(Fact.resume_id == resume_id)
    return [serialize(row) for row in db.scalars(query)]


@router.post("/facts")
def create_fact(payload: S.FactInput, db=Depends(get_db)):
    if payload.resume_id:
        get(db, Resume, payload.resume_id)
    row = Fact(**payload.model_dump())
    db.add(row)
    if payload.resume_id:
        get(db, Resume, payload.resume_id).revision += 1
    get(db, Profile, 1).revision += 1
    db.commit()
    return serialize(row)


@router.patch("/facts/{fact_id}")
def update_fact(fact_id: int, payload: S.FactPatch, db=Depends(get_db)):
    row = get(db, Fact, fact_id)
    revise(row, data_patch(payload), payload.expected_revision)
    if row.resume_id:
        get(db, Resume, row.resume_id).revision += 1
    get(db, Profile, 1).revision += 1
    db.commit()
    return serialize(row)


@router.delete("/facts/{fact_id}")
def delete_fact(fact_id: int, db=Depends(get_db)):
    row = get(db, Fact, fact_id)
    row.active = False
    row.value = ""
    row.metadata_ = {}
    row.source_ref = ""
    row.revision += 1
    get(db, Profile, 1).revision += 1
    db.commit()
    return {"deleted": True}


@router.get("/goals")
def list_goals(archived: bool = False, db=Depends(get_db)):
    return [
        serialize(row)
        for row in db.scalars(
            select(Goal).where(Goal.archived == archived).order_by(Goal.id)
        )
    ]


@router.post("/goals")
def create_goal(payload: S.GoalInput, db=Depends(get_db)):
    request = request_data(payload, "goal")
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    row = Goal(**data_patch(payload))
    db.add(row)
    db.flush()
    return commit_operation(db, payload.operation_id, request, serialize(row))


@router.get("/goals/{goal_id}")
def get_goal(goal_id: int, db=Depends(get_db)):
    row = get(db, Goal, goal_id)
    result = serialize(row)
    result["companies"] = [
        company_out(db, company)
        for company in db.scalars(
            select(Company)
            .join(GoalCompany)
            .where(GoalCompany.goal_id == goal_id, GoalCompany.active.is_(True))
        )
    ]
    result["subscriptions"] = [
        serialize(item)
        for item in db.scalars(
            select(Subscription).where(Subscription.goal_id == goal_id)
        )
    ]
    return result


@router.patch("/goals/{goal_id}")
def patch_goal(goal_id: int, payload: S.GoalPatch, db=Depends(get_db)):
    row = revise(get(db, Goal, goal_id), data_patch(payload), payload.expected_revision)
    for sub in db.scalars(select(Subscription).where(Subscription.goal_id == goal_id)):
        sub.initialized = False
        sub.revision += 1
    db.commit()
    return serialize(row)


@router.get("/companies")
def list_companies(db=Depends(get_db)):
    return [
        company_out(db, row)
        for row in db.scalars(select(Company).order_by(Company.name))
    ]


@router.post("/goals/{goal_id}/companies")
def follow_company(goal_id: int, payload: dict, db=Depends(get_db)):
    get(db, Goal, goal_id)
    company = get(db, Company, int(payload["company_id"]))
    row = db.scalar(
        select(GoalCompany).where(
            GoalCompany.goal_id == goal_id, GoalCompany.company_id == company.id
        )
    )
    if row:
        row.active = bool(payload.get("active", True))
    else:
        row = GoalCompany(
            goal_id=goal_id,
            company_id=company.id,
            reason=str(payload.get("reason", "用户关注")),
        )
        db.add(row)
    for sub in db.scalars(select(Subscription).where(Subscription.goal_id == goal_id)):
        if row.active:
            sub.initialized = False
    db.commit()
    return serialize(row)


@router.post("/discoveries", status_code=202)
async def create_discovery(payload: S.DiscoverInput, db=Depends(get_db)):
    from .execution import dispatch

    get(db, Goal, payload.goal_id)
    request = request_data(payload, "discovery")
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    from .discovery import normalize_url

    for url in payload.urls:
        normalize_url(url)
    run = create_run(
        db,
        "discovery",
        goal_id=payload.goal_id,
        context=payload.model_dump(exclude={"operation_id"}),
    )
    result = commit_operation(db, payload.operation_id, request, serialize(run))
    dispatch(result["id"])
    return result


@router.get("/jobs")
def list_jobs(
    goal_id: int | None = None,
    query: str = "",
    status: str = "",
    offset: int = 0,
    limit: int = 30,
    db=Depends(get_db),
):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    statement = select(Job).join(Company)
    if query:
        statement = statement.where(
            or_(
                Job.title.contains(query),
                Company.name.contains(query),
                Job.city.contains(query),
            )
        )
    if status == "closed":
        statement = statement.where(Job.status == "closed")
    elif status != "all":
        statement = statement.where(Job.status != "closed")
    goal = get(db, Goal, goal_id) if goal_id else None
    results = []
    for job in db.scalars(statement.order_by(Job.id.desc())):
        item = job_out(db, job, goal_id)
        if (
            goal
            and status in ["pass", "unknown", "fail"]
            and item["assessment"]["status"] != status
        ):
            continue
        if (
            goal
            and status in ["want", "later", "rejected"]
            and item.get("decision", {}).get("value") != status
        ):
            continue
        results.append(item)
    if goal:
        results.sort(
            key=lambda item: (
                item["assessment"]["direction_related"],
                item["assessment"]["status"] != "fail",
                item["assessment"]["score"],
            ),
            reverse=True,
        )
    db.commit()
    return {
        "items": results[offset : offset + limit],
        "total": len(results),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(results) else None,
        "scope": "本地已保存岗位",
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: int, goal_id: int | None = None, db=Depends(get_db)):
    job = get(db, Job, job_id)
    result = job_out(db, job, goal_id)
    result["sources"] = []
    for link in db.scalars(select(JobSource).where(JobSource.job_id == job_id)):
        source = get(db, Source, link.source_id)
        result["sources"].append(
            {
                **serialize(link),
                "source": serialize(source),
                "evidence": [
                    serialize(row)
                    for row in db.scalars(
                        select(Evidence)
                        .where(Evidence.job_source_id == link.id)
                        .order_by(Evidence.id.desc())
                        .limit(5)
                    )
                ],
            }
        )
    result["applications"] = [
        serialize(row)
        for row in db.scalars(select(Application).where(Application.job_id == job_id))
    ]
    result["materials"] = [
        serialize(row)
        for row in db.scalars(select(Material).where(Material.job_id == job_id))
    ]
    db.commit()
    return result


@router.put("/jobs/{job_id}/decision")
def decide_job(job_id: int, payload: dict, db=Depends(get_db)):
    get(db, Job, job_id)
    goal_id = int(payload["goal_id"])
    get(db, Goal, goal_id)
    value = payload.get("decision")
    if value not in ["want", "later", "rejected", "undecided"]:
        raise HTTPException(422, "无效岗位决定")
    row = db.scalar(
        select(Decision).where(Decision.goal_id == goal_id, Decision.job_id == job_id)
    )
    if row is None:
        row = Decision(goal_id=goal_id, job_id=job_id)
        db.add(row)
    row.value = value
    row.reason = str(payload.get("reason", ""))
    row.revision = (row.revision or 0) + 1
    db.commit()
    return serialize(row)


@router.post("/result-exposures")
def result_exposure(payload: dict, db=Depends(get_db)):
    from .monitoring import baseline_existing

    goal_id = int(payload["goal_id"])
    get(db, Goal, goal_id)
    ids = [int(item) for item in payload.get("job_ids", [])][:100]
    for subscription in db.scalars(
        select(Subscription).where(Subscription.goal_id == goal_id)
    ):
        baseline_existing(db, subscription, ids)
    db.commit()
    return {"recorded": len(ids)}


@router.get("/subscriptions")
def list_subscriptions(db=Depends(get_db)):
    return [
        serialize(row)
        for row in db.scalars(select(Subscription).order_by(Subscription.id))
    ]


@router.post("/subscriptions")
async def create_subscription(payload: S.SubscriptionInput, db=Depends(get_db)):
    from .execution import dispatch
    from .monitoring import baseline_existing, next_due, validate_config

    get(db, Goal, payload.goal_id)
    request = request_data(payload, "subscription")
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    config = validate_config(payload.config)
    row = Subscription(
        goal_id=payload.goal_id,
        name=payload.name,
        enabled=payload.enabled,
        config=config,
        next_run_at=next_due(config),
    )
    db.add(row)
    db.flush()
    baseline_existing(db, row)
    run = create_run(
        db, "discovery", goal_id=row.goal_id, context={"subscription_id": row.id}
    )
    db.add(Check(subscription_id=row.id, occurrence_key="initial", run_id=run.id))
    result = commit_operation(
        db, payload.operation_id, request, {**serialize(row), "initial_run_id": run.id}
    )
    dispatch(result["initial_run_id"])
    return result


@router.patch("/subscriptions/{subscription_id}")
async def patch_subscription(
    subscription_id: int, payload: S.SubscriptionPatch, db=Depends(get_db)
):
    from .monitoring import next_due, subscription_lock, validate_config

    async with subscription_lock(subscription_id):
        row = get(db, Subscription, subscription_id)
        db.refresh(row)
        changes = data_patch(payload)
        if payload.goal_id:
            get(db, Goal, payload.goal_id)
        if payload.config is not None:
            changes["config"] = validate_config(payload.config)
        revise(row, changes, payload.expected_revision)
        if payload.config is not None or payload.goal_id is not None:
            row.initialized = False
        row.next_run_at = next_due(row.config) if row.enabled else None
        db.commit()
        return serialize(row)


@router.post("/subscriptions/{subscription_id}/checks")
async def check_subscription(subscription_id: int, payload: dict, db=Depends(get_db)):
    from .execution import dispatch

    row = get(db, Subscription, subscription_id)
    key = str(payload.get("operation_id", ""))
    request = {"kind": "check", "subscription_id": subscription_id}
    prior = existing_operation(db, key, request)
    if prior is not None:
        return prior
    run = create_run(
        db, "discovery", goal_id=row.goal_id, context={"subscription_id": row.id}
    )
    db.add(Check(subscription_id=row.id, occurrence_key=key, run_id=run.id))
    result = commit_operation(db, key, request, serialize(run))
    dispatch(result["id"])
    return result


@router.get("/subscriptions/{subscription_id}/history")
def subscription_history(subscription_id: int, db=Depends(get_db)):
    return {
        "subscription": serialize(get(db, Subscription, subscription_id)),
        "checks": [
            serialize(row)
            for row in db.scalars(
                select(Check)
                .where(Check.subscription_id == subscription_id)
                .order_by(Check.id.desc())
                .limit(100)
            )
        ],
    }


@router.get("/inbox")
def list_inbox(db=Depends(get_db)):
    return [
        {
            **serialize(row),
            "deliveries": [
                serialize(item)
                for item in db.scalars(
                    select(Delivery).where(Delivery.inbox_id == row.id)
                )
            ],
        }
        for row in db.scalars(select(Inbox).order_by(Inbox.id.desc()).limit(300))
    ]


@router.patch("/inbox/{inbox_id}")
def read_inbox(inbox_id: int, db=Depends(get_db)):
    row = get(db, Inbox, inbox_id)
    row.seen_at = now()
    db.commit()
    return serialize(row)


@router.post("/deliveries/{delivery_id}/retry")
def retry_delivery(delivery_id: int, db=Depends(get_db)):
    row = get(db, Delivery, delivery_id)
    if row.status not in ["failed", "unknown"]:
        raise HTTPException(409, "此投递无需重试")
    row.status = "pending"
    db.commit()
    return serialize(row)


@router.get("/applications")
def list_applications(
    query: str = "",
    stage: str = "",
    offset: int = 0,
    limit: int = 100,
    view: str = "",
    sort: str = "default",
    db=Depends(get_db),
):
    statement = select(Application)
    if query:
        statement = statement.where(
            or_(
                Application.company.contains(query),
                Application.title.contains(query),
                Application.notes.contains(query),
            )
        )
    if stage:
        statement = statement.where(Application.stage == stage)
    ended = ["Offer", "未通过", "主动放弃", "岗位取消", "已撤回"]
    if view == "进行中":
        statement = statement.where(Application.stage.notin_(ended))
    if view == "已结束":
        statement = statement.where(Application.stage.in_(ended))
    if view == "面试安排":
        statement = statement.where(Application.stage.contains("面"))
    ordering = [Application.id.desc()]
    if sort == "newest":
        ordering = [Application.applied_at.desc(), Application.id.desc()]
    if sort == "oldest":
        ordering = [
            func.coalesce(func.nullif(Application.applied_at, ""), "9999").asc(),
            Application.id.desc(),
        ]
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = list(
        db.scalars(
            statement.order_by(*ordering)
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), 500))
        )
    )
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
    }


@router.post("/applications")
def create_application(payload: S.ApplicationInput, db=Depends(get_db)):
    request = request_data(payload, "application")
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    if payload.job_id:
        get(db, Job, payload.job_id)
    row = Application(**data_patch(payload))
    db.add(row)
    db.flush()
    append_progress(db, row, row.stage, data={"source": "manual"})
    return commit_operation(db, payload.operation_id, request, serialize(row))


@router.get("/applications/{application_id}")
def get_application(application_id: int, db=Depends(get_db)):
    row = get(db, Application, application_id)
    return {
        **serialize(row),
        "events": [
            serialize(event)
            for event in db.scalars(
                select(Progress)
                .where(Progress.application_id == row.id)
                .order_by(Progress.sequence, Progress.id)
            )
        ],
        "actions": [
            serialize(item)
            for item in db.scalars(
                select(Action).where(Action.application_id == row.id)
            )
        ],
        "fill_sessions": [
            serialize(item)
            for item in db.scalars(
                select(FillSession).where(FillSession.application_id == row.id)
            )
        ],
    }


@router.patch("/applications/{application_id}")
def patch_application(
    application_id: int, payload: S.ApplicationPatch, db=Depends(get_db)
):
    row = get(db, Application, application_id)
    previous = row.stage
    changes = data_patch(payload)
    revise(row, changes, payload.expected_revision)
    if payload.stage and payload.stage != previous:
        append_progress(db, row, payload.stage, data={"source": "table"})
    if "next_action" in changes or "next_action_at" in changes:
        actions = list(
            db.scalars(
                select(Action).where(
                    Action.application_id == row.id, Action.completed.is_(False)
                )
            )
        )
        existing = next(
            (
                action
                for action in actions
                if action.data.get("source") == "application_next"
            ),
            None,
        )
        if row.next_action:
            if existing:
                existing.title = row.next_action
                existing.due_at = row.next_action_at
                existing.revision += 1
            else:
                db.add(
                    Action(
                        application_id=row.id,
                        title=row.next_action,
                        due_at=row.next_action_at,
                        data={"source": "application_next"},
                    )
                )
        elif existing:
            existing.completed = True
    db.commit()
    return serialize(row)


@router.post("/applications/{application_id}/events")
def create_progress(application_id: int, payload: S.EventInput, db=Depends(get_db)):
    application = get(db, Application, application_id)
    request = request_data(payload, "progress", application_id)
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    event = append_progress(db, application, **data_patch(payload))
    return commit_operation(
        db,
        payload.operation_id,
        request,
        {"event": serialize(event), "application": serialize(application)},
    )


@router.patch("/applications/{application_id}/events/{event_id}")
def patch_progress(
    application_id: int, event_id: int, payload: S.EventPatch, db=Depends(get_db)
):
    row = get(db, Progress, event_id)
    if row.application_id != application_id:
        raise HTTPException(409, "进展记录与申请不一致")
    history = row.data.get("revisions", [])
    previous = serialize(row)
    revise(row, data_patch(payload), payload.expected_revision)
    row.data = {
        **row.data,
        "revisions": [
            *history,
            {key: value for key, value in previous.items() if key != "data"},
        ],
    }
    application = get(db, Application, application_id)
    for action in db.scalars(
        select(Action).where(Action.application_id == application_id)
    ):
        if action.data.get("progress_id") == row.id:
            action.title = row.label
            action.due_at = row.planned_at
            action.completed = row.state != "planned"
            action.revision += 1
    db.flush()
    project_application(db, application)
    db.commit()
    return {"event": serialize(row), "application": serialize(application)}


@router.post("/applications/{application_id}/submission-confirmations")
def confirm_submission(
    application_id: int, payload: S.SubmissionInput, db=Depends(get_db)
):
    application = get(db, Application, application_id)
    request = request_data(payload, "submission", application_id)
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    from datetime import date

    try:
        date.fromisoformat(payload.applied_at)
    except ValueError:
        raise HTTPException(422, "请填写实际投递日期")
    for version_id in payload.materials.get("version_ids", []):
        version = get(db, MaterialVersion, int(version_id))
        material = get(db, Material, version.material_id)
        if application.job_id and material.job_id != application.job_id:
            raise HTTPException(409, "材料版本属于其他岗位，请重新核对")
    for resume_id in payload.materials.get("resume_ids", []):
        get(db, Resume, int(resume_id))
    application.applied_at = payload.applied_at
    application.material = str(
        payload.materials.get("description") or application.material
    )
    application.submitted_materials = payload.materials
    append_progress(
        db,
        application,
        "已投递",
        occurred_at=payload.applied_at,
        data={
            "source": "user_confirmation",
            "note": payload.note,
            "materials": payload.materials,
        },
    )
    return commit_operation(db, payload.operation_id, request, serialize(application))


@router.get("/actions")
def list_actions(db=Depends(get_db)):
    return [
        serialize(row)
        for row in db.scalars(
            select(Action).order_by(Action.completed, Action.due_at, Action.id)
        )
    ]


@router.post("/actions")
def create_action(payload: S.ActionInput, db=Depends(get_db)):
    if payload.application_id:
        get(db, Application, payload.application_id)
    if payload.goal_id:
        get(db, Goal, payload.goal_id)
    row = Action(**payload.model_dump())
    db.add(row)
    db.commit()
    return serialize(row)


@router.patch("/actions/{action_id}")
def patch_action(action_id: int, payload: S.ActionPatch, db=Depends(get_db)):
    row = revise(
        get(db, Action, action_id), data_patch(payload), payload.expected_revision
    )
    db.commit()
    return serialize(row)


@router.get("/resumes")
def list_resumes(db=Depends(get_db)):
    return [
        serialize(row) for row in db.scalars(select(Resume).order_by(Resume.id.desc()))
    ]


@router.post("/resumes/import")
async def upload_resume(file: UploadFile = File(...), db=Depends(get_db)):
    from .materials import import_resume

    content = await file.read(20 * 1024 * 1024 + 1)
    return serialize(import_resume(db, file.filename or "resume.txt", content))


@router.patch("/resumes/{resume_id}")
def activate_resume(resume_id: int, payload: dict, db=Depends(get_db)):
    row = get(db, Resume, resume_id)
    if payload.get("active"):
        for other in db.scalars(select(Resume)):
            other.active = False
        row.active = True
        profile = get(db, Profile, 1)
        profile.data = {**profile.data, "active_resume_id": row.id}
        profile.revision += 1
    if "name" in payload:
        row.name = str(payload["name"])[:300]
    row.revision += 1
    db.commit()
    return serialize(row)


@router.get("/resumes/{resume_id}/file")
def resume_file(resume_id: int, db=Depends(get_db)):
    row = get(db, Resume, resume_id)
    path = Path(row.path).resolve()
    if not path.is_relative_to(settings().data_dir.resolve()) or not path.is_file():
        raise HTTPException(404, "原文件不可用，请查看历史文字或重新上传")
    return FileResponse(path, media_type=row.media_type, filename=row.name)


@router.post("/jobs/{job_id}/materials", status_code=202)
async def prepare_material(job_id: int, payload: S.MaterialInput, db=Depends(get_db)):
    from .execution import dispatch

    get(db, Job, job_id)
    get(db, Resume, payload.resume_id)
    request = request_data(payload, "material", job_id)
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    run = create_run(
        db, "materials", context={"job_id": job_id, "resume_id": payload.resume_id}
    )
    result = commit_operation(db, payload.operation_id, request, serialize(run))
    dispatch(result["id"])
    return result


@router.get("/materials/{material_id}")
def get_material(material_id: int, db=Depends(get_db)):
    row = get(db, Material, material_id)
    job = get(db, Job, row.job_id)
    resume = get(db, Resume, row.resume_id)
    return {
        **serialize(row),
        "job": job_out(db, job),
        "resume": serialize(resume),
        "stale": row.job_revision != job.revision
        or row.resume_revision != resume.revision,
        "versions": [
            serialize(item)
            for item in db.scalars(
                select(MaterialVersion)
                .where(MaterialVersion.material_id == row.id)
                .order_by(MaterialVersion.id.desc())
            )
        ],
    }


@router.patch("/materials/{material_id}")
def update_material(material_id: int, payload: S.SuggestionPatch, db=Depends(get_db)):
    row = get(db, Material, material_id)
    if payload.suggestions is not None:
        originals = {item["id"]: item for item in row.suggestions}
        for item in payload.suggestions:
            original = originals.get(item.get("id"))
            if original is None or any(
                item.get(key) != original.get(key)
                for key in ["original", "proposed", "fact_ids"]
            ):
                raise HTTPException(422, "建议依据不一致，请重新核对")
            if item.get("decision") not in ["pending", "accepted", "rejected"]:
                raise HTTPException(422, "无效建议状态")
    revise(row, data_patch(payload), payload.expected_revision)
    db.commit()
    return serialize(row)


@router.post("/materials/{material_id}/versions")
def create_material_version(material_id: int, payload: dict, db=Depends(get_db)):
    from .materials import save_version

    row = get(db, Material, material_id)
    key = str(payload.get("operation_id", ""))
    request = {
        "kind": "version",
        "material_id": material_id,
        "revision": payload.get("expected_revision"),
    }
    prior = existing_operation(db, key, request)
    if prior is not None:
        return prior
    if payload.get("expected_revision") != row.revision:
        raise HTTPException(409, "材料已变化，请刷新核对")
    version = save_version(db, row)
    return commit_operation(db, key, request, serialize(version))


@router.get("/material-versions/{version_id}/download")
def download_material(version_id: int, format: str = "md", db=Depends(get_db)):
    from .materials import export_content

    if format not in ["md", "pdf", "docx"]:
        raise HTTPException(422, "不支持的导出格式")
    row = get(db, MaterialVersion, version_id)
    content, media = export_content(row.content, format)
    return Response(
        content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="resume-{row.id}.{format}"'
        },
    )


@router.get("/threads")
def list_threads(db=Depends(get_db)):
    return [
        serialize(row)
        for row in db.scalars(
            select(Thread)
            .where(Thread.archived.is_(False))
            .order_by(Thread.updated_at.desc())
        )
    ]


@router.post("/threads")
def create_thread(payload: dict, db=Depends(get_db)):
    goal_id = payload.get("goal_id")
    if goal_id:
        get(db, Goal, int(goal_id))
    row = Thread(
        title=str(payload.get("title", "新的求职对话"))[:200], active_goal_id=goal_id
    )
    db.add(row)
    db.commit()
    return serialize(row)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, db=Depends(get_db)):
    row = get(db, Thread, thread_id)
    return {
        **serialize(row),
        "messages": [
            serialize(item)
            for item in db.scalars(
                select(Message)
                .where(Message.thread_id == thread_id)
                .order_by(Message.id)
            )
        ],
        "runs": [
            serialize(item)
            for item in db.scalars(
                select(Run).where(Run.thread_id == thread_id).order_by(Run.id.desc())
            )
        ],
    }


@router.patch("/threads/{thread_id}")
def patch_thread(thread_id: int, payload: dict, db=Depends(get_db)):
    row = get(db, Thread, thread_id)
    if "goal_id" in payload:
        if payload["goal_id"]:
            get(db, Goal, payload["goal_id"])
        row.active_goal_id = payload["goal_id"]
    if "title" in payload:
        row.title = str(payload["title"])[:200]
    if "archived" in payload:
        row.archived = bool(payload["archived"])
    row.revision += 1
    db.commit()
    return serialize(row)


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: int, db=Depends(get_db)):
    row = get(db, Thread, thread_id)
    row.summary = ""
    row.title = "已删除对话"
    row.archived = True
    for message in db.scalars(select(Message).where(Message.thread_id == thread_id)):
        message.content = ""
        message.data = {}
    from .database import Step

    for run in db.scalars(select(Run).where(Run.thread_id == thread_id)):
        run.context = {}
        run.result = {}
        run.error = ""
        run.cancellation_requested = True
        for event in db.scalars(select(Event).where(Event.run_id == run.id)):
            event.data = {}
        for step in db.scalars(select(Step).where(Step.run_id == run.id)):
            step.result = {}
            step.operation_key = f"deleted:{step.id}"
    for operation in db.scalars(select(Operation)):
        if (
            operation.request.get("kind") == "message"
            and operation.request.get("id") == thread_id
        ):
            operation.request = {"kind": "deleted_message", "id": thread_id}
            operation.result = {}
    db.commit()
    return {"deleted": True}


@router.post("/threads/{thread_id}/messages", status_code=202)
async def send_message(thread_id: int, payload: S.MessageInput, db=Depends(get_db)):
    from .execution import dispatch

    thread = get(db, Thread, thread_id)
    request = request_data(payload, "message", thread_id)
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    if payload.goal_id:
        get(db, Goal, payload.goal_id)
        thread.active_goal_id = payload.goal_id
    user = Message(thread_id=thread.id, role="user", content=payload.content)
    db.add(user)
    db.flush()
    reply = Message(thread_id=thread.id, role="assistant", content="")
    db.add(reply)
    db.flush()
    run = create_run(
        db,
        "conversation",
        goal_id=thread.active_goal_id,
        thread_id=thread.id,
        context={
            "content": payload.content,
            "user_message_id": user.id,
            "assistant_message_id": reply.id,
        },
    )
    thread.updated_at = now()
    result = commit_operation(db, payload.operation_id, request, serialize(run))
    dispatch(result["id"])
    return result


@router.get("/runs")
def list_runs(db=Depends(get_db)):
    return [
        serialize(row)
        for row in db.scalars(select(Run).order_by(Run.id.desc()).limit(200))
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db=Depends(get_db)):
    row = get(db, Run, run_id)
    return {
        **serialize(row),
        "events": [
            serialize(item)
            for item in db.scalars(
                select(Event).where(Event.run_id == run_id).order_by(Event.id)
            )
        ],
    }


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: int, request: Request, after: int = 0):
    from .database import Session

    cursor = max(after, int(request.headers.get("last-event-id", "0") or 0))

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            with Session() as db:
                run = get(db, Run, run_id)
                events = list(
                    db.scalars(
                        select(Event)
                        .where(Event.run_id == run_id, Event.id > cursor)
                        .order_by(Event.id)
                    )
                )
                for item in events:
                    cursor = item.id
                    yield f"id: {item.id}\ndata: {json.dumps(serialize(item), ensure_ascii=False)}\n\n"
                if run.status not in ["queued", "running"]:
                    break
            yield ": keepalive\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, db=Depends(get_db)):
    from .agent import bridge

    row = get(db, Run, run_id)
    row.cancellation_requested = True
    if row.status in ["queued", "waiting_user"]:
        row.status = "cancelled"
    db.commit()
    if row.kind == "conversation" and row.status == "running":
        await bridge.request("agent.abort", {"run_id": row.id})
    return serialize(row)


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: int, db=Depends(get_db)):
    from .execution import dispatch

    row = get(db, Run, run_id)
    if row.status not in ["failed", "waiting_user", "partial"]:
        raise HTTPException(409, "当前任务无需恢复")
    if row.kind not in ["discovery", "materials", "conversation"]:
        raise HTTPException(409, "请在关联申请重新扫描后继续")
    row.status = "queued"
    row.error = ""
    row.cancellation_requested = False
    db.commit()
    dispatch(row.id)
    return serialize(row)


@router.post("/applications/{application_id}/fill-sessions")
def start_fill(application_id: int, payload: S.FillInput, db=Depends(get_db)):
    from .discovery import normalize_url

    application = get(db, Application, application_id)
    request = request_data(payload, "fill", application_id)
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        return prior
    application.url = normalize_url(payload.url)
    row = db.scalar(
        select(FillSession).where(
            FillSession.application_id == application_id,
            FillSession.status != "completed",
            FillSession.executor == payload.executor,
        )
    )
    if row is None:
        row = FillSession(application_id=application_id, executor=payload.executor)
        db.add(row)
        db.flush()
    return commit_operation(
        db,
        payload.operation_id,
        request,
        {
            **serialize(row),
            "capabilities": {
                "upload": False,
                "submit": False,
                "scan": True,
                "fill": True,
            },
        },
    )


@router.get("/fill-sessions/{session_id}")
def get_fill(session_id: int, db=Depends(get_db)):
    row = get(db, FillSession, session_id)
    snapshot = db.scalar(
        select(Snapshot)
        .where(Snapshot.fill_session_id == row.id)
        .order_by(Snapshot.id.desc())
    )
    return {
        **serialize(row),
        "application": serialize(get(db, Application, row.application_id)),
        "snapshot": serialize(snapshot) if snapshot else None,
        "approvals": [
            serialize(item)
            for item in db.scalars(
                select(Approval)
                .where(Approval.fill_session_id == row.id)
                .order_by(Approval.id.desc())
                .limit(10)
            )
        ],
    }


@router.post("/fill-sessions/{session_id}/snapshots")
def create_snapshot(session_id: int, payload: S.SnapshotInput, db=Depends(get_db)):
    from .filling import build_snapshot

    session = get(db, FillSession, session_id)
    return serialize(
        build_snapshot(db, session, payload.url, payload.fields, payload.blockers)
    )


@router.post("/fill-sessions/{session_id}/scan")
async def scan_browser(session_id: int, db=Depends(get_db)):
    from .filling import browser

    session = get(db, FillSession, session_id)
    if session.executor != "playwright":
        raise HTTPException(409, "请在浏览器扩展中扫描当前页")
    snapshot, submit = await browser.scan(db, session)
    return {**serialize(snapshot), "submit_text": submit}


@router.post("/fill-sessions/{session_id}/execute")
async def execute_fill(session_id: int, payload: S.FillExecution, db=Depends(get_db)):
    from .filling import approve_fill, browser

    session = get(db, FillSession, session_id)
    snapshot = get(db, Snapshot, payload.snapshot_id)
    request = request_data(payload, "fill_execute", session_id)
    prior = existing_operation(db, payload.operation_id, request)
    if prior is not None:
        if session.executor == "playwright" and "results" not in prior:
            raise HTTPException(409, "此前填写结果需要核对，请重新扫描当前页")
        return prior
    approval = approve_fill(
        db,
        session,
        snapshot,
        payload.selected,
        payload.sensitive,
        payload.overwrite,
        payload.answers,
        payload.operation_id,
    )
    if session.executor == "extension":
        approval.status = "executing"
    result = commit_operation(db, payload.operation_id, request, serialize(approval))
    if session.executor == "playwright":
        result = await browser.execute(db, approval)
        db.get(Operation, payload.operation_id).result = result
        db.commit()
        return result
    return result


@router.post("/approvals/{approval_id}/complete")
def complete_fill(approval_id: int, payload: dict, db=Depends(get_db)):
    row = get(db, Approval, approval_id)
    if row.status == "consumed":
        return serialize(row)
    if row.status != "executing":
        raise HTTPException(409, "授权状态不支持继续")
    if payload.get("url") != row.data["url"]:
        raise HTTPException(409, "当前网页与授权页面不一致")
    row.status = "result_unknown" if payload.get("error") else "consumed"
    session = get(db, FillSession, row.fill_session_id)
    session.status = "needs_scan" if payload.get("error") else "waiting_user"
    session.pages = [
        *session.pages,
        {
            "url": payload["url"],
            "snapshot_id": row.snapshot_id,
            "status": "result_unknown" if payload.get("error") else "filled",
            "error": str(payload.get("error") or "")[:500],
            "results": payload.get("results", []),
            "at": now(),
        },
    ]
    db.commit()
    return serialize(row)


@router.post("/fill-sessions/{session_id}/pause")
def pause_fill(session_id: int, db=Depends(get_db)):
    row = get(db, FillSession, session_id)
    row.status = "needs_scan"
    db.commit()
    return serialize(row)


@router.get("/sources")
def list_sources(db=Depends(get_db)):
    return [serialize(row) for row in db.scalars(select(Source).order_by(Source.id))]


@router.post("/sources")
def create_source(payload: dict, db=Depends(get_db)):
    from .discovery import normalize_url

    company_id = payload.get("company_id")
    if company_id:
        get(db, Company, int(company_id))
    row = Source(
        company_id=company_id,
        url=normalize_url(str(payload["url"])),
        name=str(payload.get("name", "自定义来源")),
        kind=str(payload.get("kind", "official")),
    )
    db.add(row)
    db.commit()
    return serialize(row)


SECRET_KEYS = {"llm_api_key", "search_api_key", "feishu_webhook"}
ALLOWED_SETTINGS = SECRET_KEYS | {
    "llm_model",
    "llm_base_url",
    "llm_provider",
    "mail_enabled",
    "calendar_enabled",
    "mail_account",
    "calendar_name",
}


@router.get("/settings")
def get_settings(db=Depends(get_db)):
    result = {}
    for key in ALLOWED_SETTINGS:
        value = setting(db, key, getattr(settings(), key, ""))
        result[key] = {"configured": bool(value)} if key in SECRET_KEYS else value
    return result


@router.patch("/settings")
def patch_settings(payload: S.SettingsPatch, db=Depends(get_db)):
    for key, value in payload.values.items():
        if key not in ALLOWED_SETTINGS:
            raise HTTPException(422, f"未知设置 {key}")
        row = db.get(Setting, key)
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value, secret=key in SECRET_KEYS))
    db.commit()
    return get_settings(db)


@router.post("/settings/check-model")
async def check_model(db=Depends(get_db)):
    from .agent import bridge
    from .providers import model_config

    async with bridge.lock:
        result = await bridge.request(
            "runtime.check_provider", {"provider": model_config(db)}
        )
    return {
        "ready": result.get("ready") is True,
        "streaming": True if result.get("ready") else False,
    }


@router.get("/legacy/{table}")
def legacy_records(table: str, offset: int = 0, limit: int = 100, db=Depends(get_db)):
    if table not in [
        "resume_attachments",
        "application_events",
        "user_feedback",
        "memory_items",
        "memory_candidates",
        "external_mail_events",
        "calendar_event_links",
        "task_runs",
        "automation_schedules",
        "notifications",
        "recommendations",
        "source_runs",
        "mcp_server_configs",
    ]:
        raise HTTPException(404, "该历史数据没有独立查询入口")
    rows = list(
        db.scalars(
            select(Legacy)
            .where(Legacy.source_table == table)
            .order_by(Legacy.id)
            .offset(max(offset, 0))
            .limit(min(limit, 100))
        )
    )
    return [serialize(row) for row in rows]


@router.post("/backups")
def backup(db=Depends(get_db)):
    directory = settings().data_dir
    filename = f"workspace-{now().replace(':', '-')}.zip"
    path = directory / "backups" / filename
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "workspace.db"
        original = sqlite3.connect(db.get_bind().url.database)
        destination = sqlite3.connect(snapshot)
        original.backup(destination)
        destination.close()
        original.close()
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "workspace.db")
            for folder in ["uploads", "generated"]:
                for file in (directory / folder).rglob("*"):
                    if file.is_file():
                        archive.write(file, file.relative_to(directory))
    return {"filename": filename, "url": "/api/backups/" + filename}


@router.get("/backups/{filename}")
def download_backup(filename: str):
    path = (settings().data_dir / "backups" / filename).resolve()
    if path.parent != (settings().data_dir / "backups").resolve() or not path.is_file():
        raise HTTPException(404, "备份不存在")
    return FileResponse(path, filename=filename)


@router.post("/backups/restore")
async def restore_backup(file: UploadFile = File(...)):
    from .backups import stage_restore

    content = await file.read(500 * 1024 * 1024 + 1)
    if len(content) > 500 * 1024 * 1024:
        raise HTTPException(413, "备份超过 500MB")
    return stage_restore(content)


@router.get("/material-versions")
def list_versions(job_id: int | None = None, db=Depends(get_db)):
    statement = select(MaterialVersion).join(Material)
    if job_id:
        statement = statement.where(Material.job_id == job_id)
    return [
        serialize(row)
        for row in db.scalars(statement.order_by(MaterialVersion.id.desc()))
    ]


@router.get("/attachments")
def list_attachments(db=Depends(get_db)):
    from .database import Attachment

    return [
        serialize(row)
        for row in db.scalars(select(Attachment).order_by(Attachment.id.desc()))
    ]


@router.post("/attachments")
async def upload_attachment(file: UploadFile = File(...), db=Depends(get_db)):
    from .database import Attachment

    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "附件超过 20MB")
    name = Path(file.filename or "attachment").name
    path = settings().data_dir / "uploads" / f"{uuid4().hex}{Path(name).suffix}"
    path.write_bytes(content)
    row = Attachment(
        name=name,
        path=str(path),
        media_type=file.content_type or "application/octet-stream",
        confirmed=True,
    )
    db.add(row)
    db.commit()
    return serialize(row)


@router.get("/attachments/{attachment_id}/file")
def attachment_file(attachment_id: int, db=Depends(get_db)):
    from .database import Attachment

    row = get(db, Attachment, attachment_id)
    path = Path(row.path).resolve()
    if not path.is_relative_to(settings().data_dir.resolve()) or not path.is_file():
        raise HTTPException(404, "附件文件不可用")
    return FileResponse(path, filename=row.name, media_type=row.media_type)


@router.post("/jobs/{job_id}/materials/import")
async def import_material(
    job_id: int, file: UploadFile = File(...), db=Depends(get_db)
):
    from .materials import import_resume, save_version

    get(db, Job, job_id)
    resume = import_resume(
        db, file.filename or "material.txt", await file.read(20 * 1024 * 1024 + 1)
    )
    material = Material(
        job_id=job_id, resume_id=resume.id, content=resume.text, status="saved"
    )
    db.add(material)
    db.flush()
    version = save_version(db, material)
    db.commit()
    return {"material_id": material.id, "version": serialize(version)}


@router.patch("/companies/{company_id}")
def patch_company(company_id: int, payload: dict, db=Depends(get_db)):
    row = get(db, Company, company_id)
    data = payload.get("data", {})
    if data.get("size") and not data.get("size_evidence"):
        raise HTTPException(422, "公司规模需要提供依据或来源")
    revise(row, {"data": {**row.data, **data}}, payload.get("expected_revision"))
    db.commit()
    return serialize(row)


@router.post("/connections/mail/sync")
async def sync_mail(db=Depends(get_db)):
    from .connections import sync_mail as synchronize

    return await synchronize(db)


@router.post("/connections/mail/{record_id}/confirm")
def confirm_mail(record_id: int, payload: dict, db=Depends(get_db)):
    row = get(db, Legacy, record_id)
    if row.source_table != "external_mail_events":
        raise HTTPException(404, "邮件记录不存在")
    if row.data.get("status") == "confirmed":
        return row.data
    application = get(db, Application, int(payload["application_id"]))
    event = append_progress(
        db,
        application,
        str(payload["label"]),
        state=payload.get("state", "planned"),
        planned_at=payload.get("planned_at"),
        occurred_at=payload.get("occurred_at"),
        data={"source": "mail_confirmed", "mail_id": row.id},
    )
    row.data = {
        **row.data,
        "status": "confirmed",
        "application_id": application.id,
        "event_id": event.id,
    }
    db.commit()
    return row.data


@router.post("/connections/calendar/{event_id}")
async def sync_calendar(event_id: int, db=Depends(get_db)):
    from .connections import calendar_event

    return await calendar_event(db, get(db, Progress, event_id))


@router.post("/applications/{application_id}/interview-pack")
async def interview_pack(application_id: int, db=Depends(get_db)):
    from .providers import generate_json

    application = get(db, Application, application_id)
    job = db.get(Job, application.job_id) if application.job_id else None
    result = await generate_json(
        db,
        "依据确认的申请、JD 和实际提交材料生成面试准备包，返回 summary,checklist,questions,missing。只引用已有事实，缺失材料要说明。",
        {
            "application": serialize(application),
            "submitted_versions": [
                serialize(get(db, MaterialVersion, int(version_id)))
                for version_id in application.submitted_materials.get("version_ids", [])
            ],
            "submitted_resumes": [
                {"id": resume.id, "name": resume.name, "text": resume.text}
                for resume in [
                    get(db, Resume, int(resume_id))
                    for resume_id in application.submitted_materials.get(
                        "resume_ids", []
                    )
                ]
            ],
            "job": serialize(job) if job else None,
            "events": [
                serialize(row)
                for row in db.scalars(
                    select(Progress).where(Progress.application_id == application_id)
                )
            ],
        },
    )
    action = Action(
        application_id=application.id,
        title=f"准备 {application.company} 面试",
        data={
            "kind": "interview_pack",
            "pack": result,
            "job_revision": job.revision if job else None,
            "materials": application.submitted_materials,
        },
    )
    db.add(action)
    db.commit()
    return serialize(action)


@router.post("/applications/{application_id}/reflections")
def reflection(application_id: int, payload: dict, db=Depends(get_db)):
    application = get(db, Application, application_id)
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(422, "请填写真实问题和复盘内容")
    row = Action(
        application_id=application.id,
        title="面试复盘",
        completed=True,
        data={"kind": "reflection", "content": content},
    )
    db.add(row)
    db.commit()
    return serialize(row)


@router.get("/usage")
def usage(db=Depends(get_db)):
    from .database import Usage

    return [
        serialize(row)
        for row in db.scalars(select(Usage).order_by(Usage.id.desc()).limit(200))
    ]


@router.post("/applications/bulk-stage")
def bulk_stage(payload: dict, db=Depends(get_db)):
    key = str(payload.get("operation_id", ""))
    request = {
        "kind": "bulk-stage",
        "items": payload.get("items", []),
        "stage": payload.get("stage", ""),
    }
    prior = existing_operation(db, key, request)
    if prior is not None:
        return prior
    stage = str(payload.get("stage", "")).strip()
    if not stage or len(stage) > 100:
        raise HTTPException(422, "请填写有效阶段")
    rows = []
    for item in payload.get("items", [])[:500]:
        row = get(db, Application, int(item["id"]))
        if row.revision != item.get("expected_revision"):
            raise HTTPException(409, f"{row.company} 的记录已更新，请刷新后批量修改")
        rows.append(row)
    for row in rows:
        append_progress(db, row, stage, data={"source": "bulk_table"})
    return commit_operation(
        db, key, request, {"updated": [serialize(row) for row in rows]}
    )
