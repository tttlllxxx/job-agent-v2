from datetime import UTC, datetime
from pathlib import Path
import io
import json
import sqlite3
import zipfile

import pytest
from sqlalchemy import func, select

from app.database import (
    Application,
    Approval,
    Decision,
    Delivery,
    Evidence,
    Fact,
    FillSession,
    Goal,
    Inbox,
    Job,
    JobSource,
    JobEvent,
    Material,
    Match,
    Profile,
    Setting,
    Subscription,
    Snapshot,
    Run,
    Step,
    Thread,
)
from app.discovery import normalize_url, upsert_job
from app.filling import approve_fill, build_snapshot
from app.materials import export_content, import_resume, save_version
from app.migrate import migrate
from app.monitoring import (
    baseline_existing,
    eligible,
    evaluate_check,
    next_due,
    validate_config,
)
from app.services import assess


def add_job(db, external_id="a", **updates):
    data = {
        "company": "测试公司",
        "title": "AI 产品经理实习生",
        "city": "上海",
        "description": "参与大模型产品需求分析、用户研究和产品设计。",
        "recruitment_type": "日常实习",
        "external_id": external_id,
        "requirements": {"graduation_text": "2026届及以后"},
        **updates,
    }
    return upsert_job(
        db, data, "https://example.com/jobs/" + external_id, data["description"], 1
    )[0]


def test_context_and_idempotency(client):
    profile = client.get("/api/profile").json()
    assert (
        client.patch(
            "/api/profile",
            json={
                "expected_revision": profile["revision"],
                "data": {"graduation_year": "2029"},
            },
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/api/profile", json={"expected_revision": profile["revision"], "data": {}}
        ).status_code
        == 409
    )
    payload = {"name": "后端实习", "direction": "后端", "operation_id": "goal-1"}
    first = client.post("/api/goals", json=payload)
    assert first.status_code == 200
    assert client.post("/api/goals", json=payload).json()["id"] == first.json()["id"]
    assert (
        client.post("/api/goals", json={**payload, "direction": "前端"}).status_code
        == 409
    )
    assert client.get("/api/goals").json()[0]["direction"] == "AI 产品经理"


@pytest.mark.parametrize(
    "requirement,person,expected",
    [
        ("2026届及以后", {"graduation_year": "2028"}, "pass"),
        ("2027届", {"graduation_year": "2028"}, "fail"),
        ("2027-2029届", {"graduation_year": "2028"}, "pass"),
        ("全体在校生", {"in_school": True}, "pass"),
        ("全体在校生", {}, "unknown"),
    ],
)
def test_graduation(workspace, requirement, person, expected):
    with workspace() as db:
        db.get(Profile, 1).data = person
        db.get(Profile, 1).revision += 1
        job = add_job(db, requirements={"graduation_text": requirement})
        result = assess(db, job, db.get(Goal, 1))
        assert result["checks"][0]["result"] == expected
        assert result["direction_related"]


def test_precision_days_and_direction(workspace):
    with workspace() as db:
        job = add_job(
            db,
            requirements={
                "graduation_range": ["2028-05-01", "2028-08-31"],
                "days_per_week": 5,
            },
        )
        result = assess(db, job, db.get(Goal, 1))
        assert result["checks"][0]["result"] == "unknown"
        assert (
            next(item for item in result["checks"] if item["key"] == "days_per_week")[
                "result"
            ]
            == "unknown"
        )
        db.get(Profile, 1).data = {"graduation_date": "2028-06-01", "days_per_week": 4}
        db.get(Profile, 1).revision += 1
        result = assess(db, job, db.get(Goal, 1))
        assert result["checks"][0]["result"] == "pass"
        assert result["status"] == "fail"


def test_multiple_directions_and_matching_cache(workspace):
    with workspace() as db:
        goal = db.get(Goal, 1)
        goal.direction = "AI Agent 开发、算法工程、AI 平台/后端"
        job = add_job(
            db,
            title="算法工程实习生",
            description="负责推荐算法开发与效果优化，参与数据处理和模型评估。",
        )
        result = assess(db, job, goal)
        db.commit()
        assert result["direction_related"]
        match = db.scalar(select(Match))
        assert match.versions["rules"] == result["rules_version"]
        assert assess(db, job, goal) == result
        goal.direction = "AI 产品经理"
        goal.revision += 1
        assert not assess(db, job, goal)["direction_related"]


@pytest.mark.parametrize(
    "bounds,expected",
    [
        (["2028-05-01", "2028-08-31"], "pass"),
        (["2028-05-15", "2028-08-31"], "unknown"),
        (["2028-06-01", "2028-08-31"], "fail"),
    ],
)
def test_graduation_month_precision(workspace, bounds, expected):
    with workspace() as db:
        db.get(Profile, 1).data = {"graduation_date": "2028-05"}
        job = add_job(db, requirements={"graduation_range": bounds})
        assert assess(db, job, db.get(Goal, 1))["checks"][0]["result"] == expected


def test_dedup_and_separate_identifiers(workspace):
    with workspace() as db:
        first = add_job(db)
        assert add_job(db).id == first.id
        other = add_job(db, "b", department="另一团队")
        assert other.id != first.id
        assert db.scalar(select(func.count()).select_from(Job)) == 2
    assert (
        normalize_url("https://example.com/jobs?id=7&utm_source=a")
        == "https://example.com/jobs?id=7"
    )
    with pytest.raises(ValueError):
        normalize_url("file:///private/file")


def test_application_events_dates_and_materials(client, workspace):
    payload = {"operation_id": "app", "company": "测试", "title": "产品实习"}
    app = client.post("/api/applications", json=payload).json()
    assert client.post("/api/applications", json=payload).json()["id"] == app["id"]
    planned = client.post(
        f"/api/applications/{app['id']}/events",
        json={
            "operation_id": "plan",
            "label": "二面",
            "state": "planned",
            "planned_at": "2026-11-13T06:00:00+00:00",
        },
    ).json()
    assert planned["application"]["stage"] == "准备中"
    done = client.post(
        f"/api/applications/{app['id']}/events",
        json={"operation_id": "done", "label": "一面", "state": "completed"},
    ).json()
    assert done["application"]["stage"] == "一面"
    repeated = client.post(
        f"/api/applications/{app['id']}/events",
        json={"operation_id": "again", "label": "一面", "state": "completed"},
    ).json()
    assert repeated["event"]["id"] != done["event"]["id"]
    event = repeated["event"]
    corrected = client.patch(
        f"/api/applications/{app['id']}/events/{event['id']}",
        json={
            "expected_revision": event["revision"],
            "occurred_at": "2026-11-10T03:00:00+00:00",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["event"]["data"]["revisions"]
    confirmation = {
        "operation_id": "submitted",
        "applied_at": "2026-11-12",
        "materials": {"description": "用户自备 v2.pdf"},
    }
    result = client.post(
        f"/api/applications/{app['id']}/submission-confirmations", json=confirmation
    )
    assert result.status_code == 200
    assert (
        client.post(
            f"/api/applications/{app['id']}/submission-confirmations", json=confirmation
        ).json()["id"]
        == app["id"]
    )
    assert result.json()["submitted_materials"]["description"] == "用户自备 v2.pdf"


def test_application_full_pagination_and_revision(client, workspace):
    with workspace() as db:
        db.add_all(
            [
                Application(company=f"公司{i}", title="实习", stage="已投递")
                for i in range(125)
            ]
        )
        db.commit()
    first = client.get("/api/applications?limit=100").json()
    assert first["total"] == 125 and first["next_offset"] == 100
    assert (
        len(client.get("/api/applications?offset=100&limit=100").json()["items"]) == 25
    )
    app = first["items"][0]
    updated = client.patch(
        f"/api/applications/{app['id']}",
        json={"expected_revision": app["revision"], "notes": "准备项目介绍"},
    )
    assert updated.status_code == 200
    assert (
        client.patch(
            f"/api/applications/{app['id']}",
            json={"expected_revision": app["revision"], "notes": "旧版本"},
        ).status_code
        == 409
    )


def test_subscription_baseline_quiet_and_multiple_targets(workspace):
    with workspace() as db:
        old = add_job(db)
        sub = Subscription(
            goal_id=1,
            config={
                "events": ["new_match"],
                "channels": ["inbox"],
                "include_unknown": True,
            },
            initialized=False,
        )
        db.add(sub)
        db.flush()
        baseline_existing(db, sub, [old.id])
        db.commit()
        evaluate_check(
            db,
            sub,
            {
                "job_ids": [old.id],
                "coverage": [{"url": old.url, "status": "completed"}],
                "status": "completed",
            },
        )
        assert db.scalar(select(func.count()).select_from(Inbox)) == 0
        new = add_job(db, "new")
        result = {
            "job_ids": [old.id, new.id],
            "coverage": [{"url": new.url, "status": "completed"}],
            "status": "completed",
        }
        evaluate_check(db, sub, result)
        evaluate_check(db, sub, result)
        assert db.scalar(select(func.count()).select_from(Inbox)) == 1
        sub.enabled = False
        assert not eligible(db, sub, new, "new_match")
        sub.enabled = True
        db.add(Decision(goal_id=1, job_id=new.id, value="rejected"))
        db.commit()
        assert not eligible(db, sub, new, "new_match")


def test_initial_failure_is_still_baseline(workspace):
    with workspace() as db:
        sub = Subscription(
            goal_id=1,
            config={
                "events": ["new_match"],
                "channels": ["inbox"],
                "pending_urls": ["https://example.com/jobs/late"],
            },
            initialized=True,
        )
        db.add(sub)
        db.commit()
        job = add_job(db, "late")
        evaluate_check(
            db,
            sub,
            {
                "job_ids": [job.id],
                "coverage": [{"url": job.url, "status": "completed"}],
                "status": "completed",
            },
        )
        assert not list(db.scalars(select(Inbox)))


def test_schedule_original_clock_and_interval():
    current = datetime(2026, 11, 12, 3, tzinfo=UTC)
    assert (
        next_due({"time": "09:00", "timezone": "Asia/Shanghai"}, current)
        == "2026-11-13T01:00:00+00:00"
    )
    interval = next_due(
        {"kind": "interval", "interval_minutes": 60},
        current,
        "2026-11-10T02:00:00+00:00",
    )
    assert interval == "2026-11-12T04:00:00+00:00"
    with pytest.raises(Exception):
        validate_config({"time": "99:99"})


def test_resume_import_fact_confirmation_and_versions(workspace):
    with workspace() as db:
        resume = import_resume(db, "resume.md", "个人项目\n开发校园问答工具".encode())
        facts = list(db.scalars(select(Fact).where(Fact.resume_id == resume.id)))
        assert facts and not any(fact.confirmed for fact in facts)
        job = add_job(db)
        material = Material(
            job_id=job.id,
            resume_id=resume.id,
            content=resume.text,
            suggestions=[
                {
                    "original": "开发校园问答工具",
                    "proposed": "为校园信息查询设计问答工具",
                    "decision": "accepted",
                }
            ],
        )
        db.add(material)
        db.flush()
        version = save_version(db, material)
        db.commit()
        assert "为校园信息查询设计问答工具" in version.content
        material.content = "后续编辑"
        db.commit()
        assert "后续编辑" not in version.content
        for format in ["pdf", "docx", "md"]:
            content, media = export_content(version.content, format)
            assert len(content) > 10


def test_fill_preview_authorization_existing_and_unknown(workspace):
    with workspace() as db:
        app = Application(company="测试", title="产品")
        db.add(app)
        db.flush()
        resume = import_resume(db, "resume.txt", b"test@example.com")
        fact = db.scalar(select(Fact).where(Fact.resume_id == resume.id))
        fact.confirmed = True
        fact.metadata_ = {"field_key": "email"}
        session = FillSession(application_id=app.id)
        db.add(session)
        db.flush()
        snapshot = build_snapshot(
            db,
            session,
            "https://example.com/apply",
            [
                {
                    "key": "email",
                    "index": 0,
                    "label": "电子邮箱",
                    "type": "email",
                    "has_value": True,
                },
                {
                    "key": "salary",
                    "index": 1,
                    "label": "期望薪资",
                    "type": "text",
                    "has_value": False,
                },
            ],
            [],
        )
        assert snapshot.preview[0]["state"] == "existing"
        assert snapshot.preview[1]["state"] == "sensitive"
        with pytest.raises(Exception):
            approve_fill(
                db, session, snapshot, ["salary"], [], [], {"salary": "100"}, "fill1"
            )
        approval = approve_fill(db, session, snapshot, ["email"], [], [], {}, "fill2")
        assert approval.data["actions"] == []
        allowed = approve_fill(
            db, session, snapshot, ["email"], [], ["email"], {}, "fill3"
        )
        assert allowed.data["actions"][0]["value"] == "test@example.com"
        assert app.stage == "准备中"


def test_secrets_masked_and_client_boundary(client):
    assert (
        client.patch(
            "/api/settings", json={"values": {"llm_api_key": "secret-test"}}
        ).status_code
        == 200
    )
    data = client.get("/api/settings").json()
    assert data["llm_api_key"] == {"configured": True}
    assert "secret-test" not in json.dumps(data)
    assert (
        client.post(
            "/api/threads", json={}, headers={"X-Workspace-Client": "other"}
        ).status_code
        == 403
    )


def test_backup_restore_stages_before_switch(client, workspace):
    result = client.post("/api/backups").json()
    archive = client.get(result["url"]).content
    restored = client.post(
        "/api/backups/restore",
        files={"file": ("backup.zip", archive, "application/zip")},
    )
    assert restored.status_code == 200 and restored.json()["ready"]
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../bad", "bad")
    assert (
        client.post(
            "/api/backups/restore", files={"file": ("bad.zip", bad.getvalue())}
        ).status_code
        == 422
    )


def test_restore_uses_configured_database_location(workspace):
    from app.backups import stage_restore, apply_pending_restore
    from app.config import settings

    with workspace() as db:
        db.add(Application(company="恢复前", title="实习"))
        db.commit()
    engine = workspace.kw["bind"]
    target = Path(engine.url.database)
    engine.dispose()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.write(target, "workspace.db")
    stage_restore(archive.getvalue())
    with sqlite3.connect(target) as db:
        db.execute("UPDATE applications SET company='恢复之后的修改'")
    apply_pending_restore()
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT company FROM applications").fetchone()[0] == "恢复前"
    assert list((settings().data_dir / "backups").glob("before-restore-*.db"))


def test_legacy_migration_is_repeatable_and_keeps_source(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE candidate_profiles(id integer,confirmed boolean,target_graduation_year text,target_directions text,target_cities text,target_recruitment_types text)"
        )
        db.execute(
            "INSERT INTO candidate_profiles VALUES(1,1,'2028','[\"产品\"]','[\"上海\"]','[\"日常实习\"]')"
        )
        db.execute(
            "CREATE TABLE applications(id integer,company text,position text,current_stage text,applied_date text,created_at text)"
        )
        db.execute(
            "INSERT INTO applications VALUES(7,'迁移公司','产品实习','二面','2026-11-01','2026-11-01')"
        )
        db.execute("ALTER TABLE applications ADD COLUMN resume_document_id integer")
        db.execute("UPDATE applications SET resume_document_id=3")
        db.execute(
            "CREATE TABLE resume_documents(id integer, original_name text, stored_path text)"
        )
        db.execute("INSERT INTO resume_documents VALUES(3,'历史简历.pdf','')")
        db.execute(
            "CREATE TABLE automation_schedules(id integer, name text, workflow text, enabled boolean, interval_minutes integer)"
        )
        db.execute(
            "INSERT INTO automation_schedules VALUES(1,'邮件检查','mail_sync',0,15)"
        )
    url = f"sqlite:///{tmp_path / 'new.db'}"
    first = migrate(path, url)
    second = migrate(path, url)
    assert first == second and first["applications"] == 1
    with sqlite3.connect(tmp_path / "new.db") as db:
        extra, material = db.execute(
            "SELECT extra,material FROM applications WHERE id=7"
        ).fetchone()
        assert json.loads(extra)["linked_resume_ids"] == [3]
        assert material == "历史简历.pdf"
        assert db.execute("SELECT count(*) FROM subscriptions").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT count(*) FROM legacy_records WHERE source_table='automation_schedules'"
            ).fetchone()[0]
            == 1
        )
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from applications").fetchone()[0] == 1


def test_legacy_json_scalars_decode():
    from app.migrate import value

    assert (
        value({"value": '"https://example.com/v1"'}, "value")
        == "https://example.com/v1"
    )
    assert value({"value": "true"}, "value") is True
    assert value({"value": "0.5"}, "value") == 0.5


def test_official_priority_keeps_both_source_evidence(workspace):
    with workspace() as db:
        official = add_job(db, explicitly_closed=False)
        verified_at = official.verified_at
        incoming = {
            "company": "测试公司",
            "title": official.title,
            "city": "上海",
            "application_url": official.url,
            "description": "社区转载岗位，毕业条件与官网不一致，需要保留原文供核对。",
            "requirements": {"graduation_text": "2027届"},
            "explicitly_closed": True,
        }
        merged, created = upsert_job(
            db,
            incoming,
            "https://community.example/post/1",
            incoming["description"],
            1,
            "community",
        )
        assert not created and merged.id == official.id
        assert merged.status == "open" and merged.verified_at == verified_at
        assert merged.requirements["graduation_text"] == "2026届及以后"
        assert merged.requirements["conflicted_fields"] == []
        assert db.scalar(select(func.count()).select_from(JobSource)) == 2
        last = db.scalar(select(Evidence).order_by(Evidence.id.desc()))
        assert last.fields["requirements"]["graduation_text"] == "2027届"
        assert assess(db, merged, db.get(Goal, 1))["checks"][0]["result"] == "pass"


def test_same_source_updates_reopen_once_and_expired_is_stable(workspace):
    with workspace() as db:
        job = add_job(db, explicitly_closed=True)
        revision = job.revision
        job = add_job(
            db, explicitly_closed=False, requirements={"graduation_text": "2028届"}
        )
        assert job.revision == revision + 1 and job.status == "open"
        assert not job.requirements.get("source_conflicts")
        add_job(db, explicitly_closed=False, requirements={"graduation_text": "2028届"})
        assert (
            db.scalar(
                select(func.count())
                .select_from(JobEvent)
                .where(JobEvent.kind == "reopened")
            )
            == 1
        )
        expired = add_job(
            db,
            "expired",
            explicitly_closed=False,
            deadline_at="2020-01-01T20:00:00+08:00",
        )
        revision = expired.revision
        assert expired.status == "closed"
        add_job(
            db,
            "expired",
            explicitly_closed=False,
            deadline_at="2020-01-01T20:00:00+08:00",
        )
        assert expired.revision == revision


def test_bulk_stage_is_atomic_and_updates_history(client):
    rows = [
        client.post(
            "/api/applications",
            json={"operation_id": f"bulk-{i}", "company": f"公司{i}", "title": "实习"},
        ).json()
        for i in range(2)
    ]
    payload = {
        "operation_id": "bulk-update",
        "stage": "二面",
        "items": [
            {"id": row["id"], "expected_revision": row["revision"]} for row in rows
        ],
    }
    payload["items"][1]["expected_revision"] += 1
    assert client.post("/api/applications/bulk-stage", json=payload).status_code == 409
    assert all(
        item["stage"] == "准备中"
        for item in client.get("/api/applications").json()["items"]
    )
    payload["items"][1]["expected_revision"] -= 1
    assert client.post("/api/applications/bulk-stage", json=payload).status_code == 200
    assert client.post("/api/applications/bulk-stage", json=payload).status_code == 200
    assert client.get(f"/api/applications/{rows[0]['id']}").json()["stage"] == "二面"


@pytest.mark.asyncio
async def test_paused_notification_and_timeout_are_not_resent(workspace, monkeypatch):
    import httpx
    from app import monitoring

    monkeypatch.setattr(monitoring, "Session", workspace)
    with workspace() as db:
        job = add_job(db, explicitly_closed=False)
        sub = Subscription(
            goal_id=1,
            enabled=False,
            initialized=True,
            config={
                "events": ["new_match"],
                "channels": ["feishu"],
                "include_unknown": True,
            },
        )
        db.add(sub)
        db.flush()
        inbox = Inbox(
            job_id=job.id,
            event_key="test-event",
            title="新岗位",
            body="新匹配",
            goal_reasons=[
                {"subscription_id": sub.id, "goal_id": 1, "kind": "new_match"}
            ],
        )
        db.add(inbox)
        db.flush()
        delivery = Delivery(inbox_id=inbox.id, channel="feishu")
        db.add(delivery)
        db.add(Setting(key="feishu_webhook", value="https://example.test/webhook"))
        db.commit()
        delivery_id, subscription_id = delivery.id, sub.id
    await monitoring.send_deliveries()
    with workspace() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery.status == "cancelled" and delivery.attempts == 0
        db.get(Subscription, subscription_id).enabled = True
        delivery.status = "pending"
        db.commit()
    calls = []

    async def timeout(self, *args, **kwargs):
        calls.append(1)
        raise httpx.ReadTimeout("test timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", timeout)
    await monitoring.send_deliveries()
    await monitoring.send_deliveries()
    with workspace() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery.status == "unknown" and delivery.attempts == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_agent_saved_step_reused_but_reads_refresh(workspace, monkeypatch):
    from app import agent

    monkeypatch.setattr(agent, "Session", workspace)
    with workspace() as db:
        thread = Thread(title="测试对话", active_goal_id=1)
        db.add(thread)
        db.flush()
        run = Run(kind="conversation", thread_id=thread.id, goal_id=1)
        db.add(run)
        db.commit()
        run_id = run.id
    arguments = {"profile_patch": {"graduation_year": "2029"}}
    first = await agent.execute_tool(run_id, "update_context", arguments)
    second = await agent.execute_tool(run_id, "update_context", arguments)
    assert first == second
    with workspace() as db:
        assert db.get(Profile, 1).revision == 2
        assert (
            db.scalar(select(Step).where(Step.tool == "update_context")).status
            == "completed"
        )
    await agent.execute_tool(run_id, "list_goals", {})
    with workspace() as db:
        db.get(Goal, 1).name = "已修改目标"
        db.commit()
    refreshed = await agent.execute_tool(run_id, "list_goals", {})
    assert refreshed[0]["name"] == "已修改目标"


@pytest.mark.asyncio
async def test_fill_recovery_requires_new_snapshot(workspace, monkeypatch):
    from app import execution

    monkeypatch.setattr(execution, "Session", workspace)
    with workspace() as db:
        application = Application(company="测试", title="实习")
        db.add(application)
        db.flush()
        session = FillSession(application_id=application.id)
        db.add(session)
        db.flush()
        snapshot = build_snapshot(db, session, "https://example.com", [], [])
        approval = approve_fill(db, session, snapshot, [], [], [], {}, "before-restart")
        approval.status = "executing"
        db.commit()
        session_id, snapshot_id, approval_id = session.id, snapshot.id, approval.id
    await execution.recover()
    with workspace() as db:
        session = db.get(FillSession, session_id)
        assert session.status == "needs_scan"
        assert db.get(Approval, approval_id).status == "result_unknown"
        with pytest.raises(Exception):
            approve_fill(
                db,
                session,
                db.get(Snapshot, snapshot_id),
                [],
                [],
                [],
                {},
                "after-restart",
            )


def test_extension_execution_intent_and_stale_snapshot(client):
    application = client.post(
        "/api/applications",
        json={"operation_id": "extension-app", "company": "测试", "title": "实习"},
    ).json()
    session = client.post(
        f"/api/applications/{application['id']}/fill-sessions",
        json={
            "operation_id": "extension-session",
            "url": "https://example.com/apply",
            "executor": "extension",
        },
    ).json()
    endpoint = f"/api/fill-sessions/{session['id']}"
    snapshot = client.post(
        endpoint + "/snapshots",
        json={"url": "https://example.com/apply", "fields": [], "blockers": []},
    ).json()
    approval = client.post(
        endpoint + "/execute",
        json={
            "operation_id": "extension-action",
            "snapshot_id": snapshot["id"],
            "selected": [],
            "sensitive": [],
            "overwrite": [],
            "answers": {},
        },
    ).json()
    assert approval["status"] == "executing"
    result = client.post(
        f"/api/approvals/{approval['id']}/complete",
        json={"url": snapshot["url"], "error": "页面在填写中关闭"},
    )
    assert result.json()["status"] == "result_unknown"
    assert client.get(endpoint).json()["status"] == "needs_scan"
    client.post(
        endpoint + "/snapshots",
        json={"url": "https://example.com/next", "fields": [], "blockers": []},
    )
    stale = client.post(
        endpoint + "/execute",
        json={
            "operation_id": "old-snapshot",
            "snapshot_id": snapshot["id"],
            "selected": [],
            "sensitive": [],
            "overwrite": [],
            "answers": {},
        },
    )
    assert stale.status_code == 409
