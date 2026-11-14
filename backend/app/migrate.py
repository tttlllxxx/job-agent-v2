"""Import the previous local database into the v2 workspace without editing the source."""

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from .database import (
    Action,
    Application,
    Base,
    Baseline,
    Company,
    Decision,
    Attachment,
    Event,
    Evidence,
    Fact,
    Goal,
    GoalCompany,
    Job,
    JobSource,
    Legacy,
    Material,
    MaterialVersion,
    Message,
    Profile,
    Progress,
    Resume,
    Run,
    Setting,
    Source,
    Step,
    Subscription,
    Thread,
    make_engine,
    now,
)


def value(row, key, default=None):
    result = row.get(key, default)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            pass
    return result


def migrate(source_path: Path, target_url: str):
    source = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    tables = {
        row[0]
        for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    def rows(table):
        return (
            [dict(row) for row in source.execute(f'SELECT * FROM "{table}"')]
            if table in tables
            else []
        )

    target = make_engine(target_url)
    Base.metadata.create_all(target)
    counts = {}
    with DatabaseSession(target) as db:
        if db.get(Setting, "migration_complete"):
            for row in rows("app_settings"):
                existing = db.get(Setting, row["key"])
                if existing and existing.value == row["value"]:
                    existing.value = value(row, "value")
            for row in rows("resume_attachments"):
                if not db.get(Attachment, row["id"]):
                    db.add(
                        Attachment(
                            id=row["id"],
                            resume_id=row.get("document_id"),
                            name=row["display_name"],
                            path=row["stored_path"],
                            media_type=row["media_type"],
                            kind=row["kind"],
                            confirmed=bool(row["confirmed"]),
                        )
                    )
            db.commit()
            return db.get(Setting, "migration_complete").value
        if db.scalar(select(Application.id).limit(1)):
            raise ValueError("目标数据库已有记录，无法覆盖导入")

        def archive(table, records=None):
            records = rows(table) if records is None else records
            for index, row in enumerate(records):
                db.add(
                    Legacy(
                        source_table=table,
                        source_id=str(row.get("id", row.get("key", index))),
                        data=row,
                    )
                )
            counts[table] = len(records)

        profiles = rows("candidate_profiles")
        old_profile = profiles[0] if profiles else {}
        profile_data = {
            "graduation_year": old_profile.get("target_graduation_year")
            if old_profile.get("confirmed")
            else None,
            "education_level": old_profile.get("education_level"),
            "skills": value(old_profile, "skills", []),
            "experience_summary": old_profile.get("experience_summary", ""),
            "project_summary": old_profile.get("project_summary", ""),
            "active_resume_id": old_profile.get("active_resume_id"),
            "in_school": None,
        }
        db.add(Profile(id=1, data=profile_data))
        directions = value(old_profile, "target_directions", [])
        goal = Goal(
            name="历史求职目标",
            direction="、".join(directions) or "待确认方向",
            recruitment_type="、".join(
                value(old_profile, "target_recruitment_types", [])
            ),
            constraints={},
            preferences={
                "cities": value(old_profile, "target_cities", []),
                "remote": old_profile.get("remote_preference"),
                "exclude_keywords": value(old_profile, "exclude_keywords", []),
                "needs_review": not old_profile.get("confirmed", False),
            },
        )
        db.add(goal)
        db.flush()
        archive("candidate_profiles")
        companies = {}
        sources = {}

        def company(name):
            name = name.strip() or "公司待补充"
            if name not in companies:
                entry = Company(name=name, data={"size": None})
                db.add(entry)
                db.flush()
                companies[name] = entry
                db.add(
                    GoalCompany(
                        goal_id=goal.id, company_id=entry.id, reason="历史岗位来源"
                    )
                )
            return companies[name]

        def source_record(key, company_id, url):
            if key not in sources:
                entry = Source(
                    name=key,
                    company_id=company_id,
                    url=url,
                    kind="official",
                    config={"legacy_key": key},
                )
                db.add(entry)
                db.flush()
                sources[key] = entry
            return sources[key]

        for row in rows("job_postings"):
            employer = company(row["company"])
            job = Job(
                id=row["id"],
                company_id=employer.id,
                title=row["title"],
                city=row.get("location") or "",
                department=row.get("department") or "",
                description=row.get("description") or "",
                recruitment_type=row.get("recruitment_type") or "",
                url=row["normalized_url"],
                status="closed" if row.get("closed") else "unverified",
                verified_at=row.get("last_seen_at"),
                published_at=row.get("published_at"),
                requirements={"graduation_text": row.get("graduation_year") or ""},
                created_at=row.get("first_seen_at") or now(),
            )
            db.add(job)
            db.flush()
            channel = source_record(
                row["source_key"], employer.id, row["normalized_url"]
            )
            link = JobSource(
                job_id=job.id,
                source_id=channel.id,
                external_id=str(row["external_job_id"]),
                url=row["normalized_url"],
            )
            db.add(link)
            db.flush()
            db.add(
                Evidence(
                    job_source_id=link.id,
                    text=job.description,
                    fields={
                        "legacy": value(row, "evidence_metadata", {}),
                        "graduation_text": row.get("graduation_year"),
                    },
                    created_at=job.verified_at or now(),
                )
            )
            if row.get("decision") and row["decision"] != "undecided":
                db.add(
                    Decision(
                        job_id=job.id,
                        goal_id=goal.id,
                        value=row["decision"],
                        reason=row.get("decision_reason") or "",
                    )
                )
        counts["job_postings"] = len(rows("job_postings"))
        for row in rows("source_health"):
            channel = sources.get(row["source_key"])
            if channel:
                channel.status = row["status"]
                channel.last_success_at = row["last_success_at"]
                channel.error = row.get("last_error") or ""
        for row in rows("resume_documents"):
            text = row.get("redacted_text") or ""
            pii = value(row, "pii_local", {})
            path = row.get("stored_path") or ""
            db.add(
                Resume(
                    id=row["id"],
                    name=row.get("display_name") or row["original_name"],
                    path=path,
                    media_type=row.get("media_type") or "text/plain",
                    text=text,
                    active=bool(row.get("is_active")),
                    data={
                        "pii_local": pii,
                        "tags": value(row, "tags", []),
                        "deleted_at": row.get("deleted_at"),
                        "file_missing": bool(path and not Path(path).exists()),
                    },
                    created_at=row.get("created_at") or now(),
                )
            )
        db.flush()
        for row in rows("resume_facts"):
            db.add(
                Fact(
                    key=row["fact_id"],
                    value=row.get("original_text") or row.get("redacted_text") or "",
                    resume_id=row["document_id"],
                    confirmed=bool(row.get("confirmed")),
                    active=bool(row.get("active")),
                    source_ref=f"resume:{row['document_id']}",
                    metadata_={"legacy": row},
                    created_at=row["created_at"],
                )
            )
        for row in rows("resume_fields"):
            db.add(
                Fact(
                    key=f"{row['section']}.{row['entry_id']}.{row['field_key']}",
                    value=row["value"],
                    resume_id=row["document_id"],
                    confirmed=bool(row.get("confirmed")),
                    source_ref=row.get("source_type") or "resume",
                    metadata_={
                        "section": row["section"],
                        "entry_id": row["entry_id"],
                        "field_key": row["field_key"],
                        "sensitivity": row.get("sensitivity"),
                    },
                )
            )
        for row in rows("resume_attachments"):
            db.add(
                Attachment(
                    id=row["id"],
                    resume_id=row.get("document_id"),
                    name=row["display_name"],
                    path=row["stored_path"],
                    media_type=row["media_type"],
                    kind=row["kind"],
                    confirmed=bool(row["confirmed"]),
                )
            )
        db.flush()
        for row in rows("applications"):
            stage = row.get("current_stage") or row.get("status") or "准备中"
            if stage in ["待投递", "未投递", "投递"]:
                stage = "已投递" if row.get("applied_date") else "准备中"
            db.add(
                Application(
                    id=row["id"],
                    job_id=row.get("job_id"),
                    company=row.get("company") or "公司待补充",
                    title=row.get("position") or "岗位待补充",
                    city=row.get("base_location") or "",
                    stage=stage,
                    applied_at=row.get("applied_date") or "",
                    url=row.get("url") or "",
                    next_action=row.get("next_action") or "",
                    next_action_at=row.get("next_action_at"),
                    notes=row.get("notes") or "",
                    material=(
                        db.get(Resume, row["resume_document_id"]).name
                        if row.get("resume_document_id")
                        and db.get(Resume, row["resume_document_id"])
                        else ""
                    ),
                    submitted_materials=value(row, "submitted_materials", {}),
                    extra={
                        "legacy": row,
                        "linked_resume_ids": [row["resume_document_id"]]
                        if row.get("resume_document_id")
                        else [],
                        "linked_material_version_ids": [row["resume_version_id"]]
                        if row.get("resume_version_id")
                        else [],
                    },
                    created_at=row.get("created_at") or now(),
                )
            )
            db.flush()
            if row.get("next_action"):
                db.add(
                    Action(
                        application_id=row["id"],
                        goal_id=goal.id,
                        title=row["next_action"],
                        due_at=row.get("next_action_at"),
                    )
                )
        db.flush()
        for row in rows("application_progress_events"):
            db.add(
                Progress(
                    id=row["id"],
                    application_id=row["application_id"],
                    label=row["label"],
                    state=row["state"],
                    sequence=row["sequence"],
                    occurred_at=row.get("completed_at")
                    or (row.get("primary_at") if row["state"] == "completed" else None),
                    planned_at=row.get("primary_at")
                    if row["state"] == "planned"
                    else None,
                    data={"source": row.get("source"), "legacy": row},
                    created_at=row["created_at"],
                )
            )
        for row in rows("agent_threads"):
            db.add(
                Thread(
                    id=row["id"],
                    title=row["title"],
                    active_goal_id=goal.id,
                    archived=bool(row.get("archived")),
                    created_at=row["created_at"],
                )
            )
        db.flush()
        for row in rows("agent_messages"):
            db.add(
                Message(
                    id=row["id"],
                    thread_id=row["thread_id"],
                    role=row["role"],
                    content=row["content"],
                    data={
                        "kind": row.get("kind"),
                        "metadata": value(row, "message_metadata", {}),
                    },
                    created_at=row["created_at"],
                )
            )
        for row in rows("agent_runs"):
            status = row["status"]
            if status in ["queued", "planning", "running", "recovering", "submitting"]:
                status = "waiting_user"
            elif status in ["succeeded", "success"]:
                status = "completed"
            elif "waiting" in status or status == "ready_to_fill":
                status = "waiting_user"
            elif status not in ["completed", "partial", "failed", "cancelled"]:
                status = "waiting_user"
            db.add(
                Run(
                    id=row["id"],
                    kind=row["workflow"],
                    status=status,
                    phase="历史任务，请核对后继续" if status == "waiting_user" else "",
                    goal_id=goal.id,
                    thread_id=row.get("thread_id"),
                    context={"legacy": value(row, "context", {})},
                    result=value(row, "result", {}),
                    error=row.get("error_message") or "",
                    created_at=row["created_at"],
                )
            )
        db.flush()
        for row in rows("agent_steps"):
            db.add(
                Step(
                    id=row["id"],
                    run_id=row["run_id"],
                    operation_key=str(row.get("idempotency_key") or row["id"]),
                    tool=row["tool_name"],
                    status=row["status"],
                    result=value(row, "result", {}),
                )
            )
        for row in rows("agent_events"):
            db.add(
                Event(
                    id=row["id"],
                    run_id=row["run_id"],
                    type=row["event_type"],
                    data=value(row, "payload", {}),
                    created_at=row["created_at"],
                )
            )
        for row in rows("automation_schedules"):
            if row["workflow"] not in [
                "refresh_pipeline",
                "job_discovery",
                "discover_jobs",
                "refresh_jobs",
            ]:
                continue
            db.add(
                Subscription(
                    id=row["id"],
                    goal_id=goal.id,
                    name=row["name"],
                    enabled=bool(row["enabled"]),
                    config={
                        "kind": "interval",
                        "interval_minutes": row["interval_minutes"],
                        "timezone": "Asia/Shanghai",
                        "events": ["new_match"],
                        "channels": ["inbox"],
                        "legacy_workflow": row["workflow"],
                        "legacy": value(row, "config", {}),
                    },
                    next_run_at=row.get("next_run_at"),
                    last_checked_at=row.get("last_run_at"),
                    initialized=True,
                )
            )
        db.flush()
        job_ids = list(db.scalars(select(Job.id)))
        for subscription in db.scalars(select(Subscription)):
            db.add_all(
                [
                    Baseline(
                        subscription_id=subscription.id,
                        job_id=job_id,
                        reason="migration",
                    )
                    for job_id in job_ids
                ]
            )
        for row in rows("resume_versions"):
            resume_id = row.get("resume_document_id") or profile_data.get(
                "active_resume_id"
            )
            if not resume_id:
                continue
            material = Material(
                job_id=row["job_id"],
                resume_id=resume_id,
                content=row["markdown_content"],
                status="saved",
            )
            db.add(material)
            db.flush()
            db.add(
                MaterialVersion(
                    id=row["id"],
                    material_id=material.id,
                    content=row["markdown_content"],
                    path=row.get("pdf_path") or "",
                    data={"legacy": row},
                )
            )
        # Latest scoring evidence is useful context. Historical scoring cache stays in the backup.
        if "recommendations" in tables:
            latest = [
                dict(row)
                for row in source.execute(
                    "SELECT r.* FROM recommendations r JOIN (SELECT job_id,max(id) id FROM recommendations GROUP BY job_id) x ON r.id=x.id"
                )
            ]
            archive("recommendations", latest)
        for table in [
            "resume_documents",
            "resume_attachments",
            "resume_fields",
            "resume_facts",
            "resume_versions",
            "application_answers",
            "application_events",
            "user_feedback",
            "memory_items",
            "memory_candidates",
            "conversation_summaries",
            "thread_context_states",
            "job_changes",
            "notifications",
            "task_runs",
            "automation_schedules",
            "form_snapshots",
            "approval_requests",
            "external_mail_events",
            "calendar_event_links",
            "mcp_server_configs",
            "source_runs",
            "source_health",
        ]:
            archive(table)
        for row in rows("app_settings"):
            db.add(
                Setting(
                    key=row["key"],
                    value=value(row, "value"),
                    secret=bool(row["secret"]),
                )
            )
        report = {
            "source": str(source_path),
            "counts": counts,
            "jobs": len(job_ids),
            "applications": len(rows("applications")),
            "resumes": len(rows("resume_documents")),
            "files_missing": sum(
                bool(r.get("stored_path") and not Path(r["stored_path"]).exists())
                for r in rows("resume_documents")
            ),
            "finished_at": now(),
        }
        db.add(Setting(key="migration_complete", value=report))
        db.commit()
    with target.connect() as connection:
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(f"迁移外键检查失败，数量 {len(violations)}")
    source.close()
    target.dispose()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.source, args.target), ensure_ascii=False))
