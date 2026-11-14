import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from .common import get
from .database import (
    Application,
    Baseline,
    Check,
    Decision,
    Delivery,
    Goal,
    Inbox,
    Intent,
    Job,
    JobEvent,
    JobSource,
    Run,
    Session,
    Subscription,
    now,
)
from .services import assess, create_run, setting

locks = {}


def subscription_lock(subscription_id):
    return locks.setdefault(subscription_id, asyncio.Lock())


def validate_config(config):
    config = {
        "kind": "daily",
        "time": "09:00",
        "timezone": "Asia/Shanghai",
        "events": ["new_match"],
        "channels": ["inbox"],
        **config,
    }
    try:
        ZoneInfo(config["timezone"])
        datetime.strptime(config.get("time", "09:00"), "%H:%M")
        if config["kind"] not in ["daily", "interval"]:
            raise ValueError()
        if (
            config["kind"] == "interval"
            and not 1 <= int(config.get("interval_minutes", 0)) <= 525600
        ):
            raise ValueError()
        if not set(config["events"]) <= {
            "new_match",
            "deadline_due",
            "reopened",
            "qualification_changed",
        }:
            raise ValueError()
        if not set(config["channels"]) <= {"inbox", "feishu"}:
            raise ValueError()
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(422, "订阅时间、时区或事件配置不正确") from error
    return config


def next_due(config, reference=None, anchor=None):
    current = reference or datetime.now(UTC)
    if config.get("kind") == "interval":
        delta = timedelta(minutes=int(config["interval_minutes"]))
        base = (
            datetime.fromisoformat(anchor.replace("Z", "+00:00")) if anchor else current
        )
        if base.tzinfo is None:
            base = base.replace(tzinfo=UTC)
        steps = max(1, int((current - base) / delta) + 1)
        return (base + steps * delta).isoformat()
    zone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    local = current.astimezone(zone)
    hour, minute = map(int, config.get("time", "09:00").split(":"))
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    # Round trip through UTC resolves an absent wall-clock time to the next valid instant.
    candidate = candidate.astimezone(UTC).astimezone(zone)
    return candidate.astimezone(UTC).isoformat()


def baseline_existing(db, subscription, job_ids=None, reason="shown"):
    if job_ids is None:
        job_ids = list(db.scalars(select(Job.id)))
    existing = set(
        db.scalars(
            select(Baseline.job_id).where(Baseline.subscription_id == subscription.id)
        )
    )
    for job_id in job_ids:
        if job_id not in existing:
            job = db.get(Job, job_id)
            if job:
                db.add(
                    Baseline(
                        subscription_id=subscription.id,
                        job_id=job_id,
                        reason=reason,
                        job_revision=job.revision,
                    )
                )


def eligible(db, subscription, job, kind):
    if not subscription.enabled:
        return False
    config = subscription.config
    from .database import GoalCompany

    followed = db.scalar(
        select(GoalCompany).where(
            GoalCompany.goal_id == subscription.goal_id,
            GoalCompany.company_id == job.company_id,
        )
    )
    if followed and not followed.active:
        return False
    if config.get("scope_mode") == "selected" and job.company_id not in config.get(
        "company_ids", []
    ):
        return False
    if kind not in config.get("events", ["new_match"]):
        return False
    if config.get("company_ids") and job.company_id not in config["company_ids"]:
        return False
    decision = db.scalar(
        select(Decision).where(
            Decision.job_id == job.id, Decision.goal_id == subscription.goal_id
        )
    )
    if decision and decision.value in ["later", "rejected"]:
        return False
    applied = db.scalar(
        select(Application.id).where(
            Application.job_id == job.id, Application.applied_at != ""
        )
    )
    if applied and (kind == "new_match" or not config.get("follow_applied", False)):
        return False
    if job.status == "closed" and kind != "deadline_due":
        return False
    assessment = assess(db, job, get(db, Goal, subscription.goal_id))
    return (
        assessment["direction_related"]
        and assessment["status"] != "fail"
        and (config.get("include_unknown", True) or assessment["status"] == "pass")
    )


def evaluate_check(db, subscription, result):
    pending = set(subscription.config.get("pending_urls", []))
    for job_id in result.get("job_ids", []):
        job = get(db, Job, job_id)
        base = db.scalar(
            select(Baseline).where(
                Baseline.subscription_id == subscription.id, Baseline.job_id == job_id
            )
        )
        urls = set(db.scalars(select(JobSource.url).where(JobSource.job_id == job_id)))
        initial = not subscription.initialized or bool(urls & pending)
        if base is None:
            db.add(
                Baseline(
                    subscription_id=subscription.id,
                    job_id=job_id,
                    reason="initial_check" if initial else "observed",
                    job_revision=job.revision,
                )
            )
            if not initial and eligible(db, subscription, job, "new_match"):
                record_intent(db, subscription, job, "new_match", 1)
        elif base.job_revision != job.revision:
            events = list(
                db.scalars(
                    select(JobEvent).where(
                        JobEvent.job_id == job.id,
                        JobEvent.job_revision > base.job_revision,
                    )
                )
            )
            for event in events:
                if eligible(db, subscription, job, event.kind):
                    record_intent(db, subscription, job, event.kind, event.job_revision)
            base.job_revision = job.revision
    for job in db.scalars(select(Job).where(Job.deadline_at.is_not(None))):
        try:
            deadline = datetime.fromisoformat(job.deadline_at.replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            if 0 < (deadline - datetime.now(UTC)).total_seconds() <= 86400 and eligible(
                db, subscription, job, "deadline_due"
            ):
                record_intent(db, subscription, job, "deadline_due", job.revision)
        except ValueError:
            continue
    complete_urls = {
        item["url"]
        for item in result.get("coverage", [])
        if item.get("url") and item.get("status") == "completed"
    }
    pending -= complete_urls
    pending.update(
        item["url"] for item in result.get("failures", []) if item.get("url")
    )
    subscription.config = {**subscription.config, "pending_urls": sorted(pending)}
    subscription.last_checked_at = now()
    if result.get("coverage"):
        subscription.initialized = True
        if result.get("status") == "completed":
            subscription.last_success_at = now()
    db.commit()


def record_intent(db, subscription, job, kind, revision):
    event = db.scalar(
        select(JobEvent).where(
            JobEvent.job_id == job.id,
            JobEvent.kind == kind,
            JobEvent.job_revision == revision,
        )
    )
    if event is None:
        event = JobEvent(job_id=job.id, kind=kind, job_revision=revision)
        db.add(event)
        db.flush()
    if db.scalar(
        select(Intent.id).where(
            Intent.job_event_id == event.id, Intent.subscription_id == subscription.id
        )
    ):
        return
    db.add(
        Intent(
            job_event_id=event.id,
            subscription_id=subscription.id,
            status="pending",
            data={"goal_revision": get(db, Goal, subscription.goal_id).revision},
        )
    )
    key = f"job:{job.id}:{kind}:{revision}"
    inbox = db.scalar(select(Inbox).where(Inbox.event_key == key))
    reason = {
        "goal_id": subscription.goal_id,
        "subscription_id": subscription.id,
        "kind": kind,
    }
    if inbox is None:
        from .database import Company

        company = get(db, Company, job.company_id)
        inbox = Inbox(
            event_key=key,
            job_id=job.id,
            title=f"{company.name} · {job.title}",
            body=f"岗位变化：{kind}。资格与来源请在详情核对。",
            goal_reasons=[reason],
        )
        db.add(inbox)
        db.flush()
    elif reason not in inbox.goal_reasons:
        inbox.goal_reasons = [*inbox.goal_reasons, reason]
    if "feishu" in subscription.config.get("channels", []) and not db.scalar(
        select(Delivery.id).where(
            Delivery.inbox_id == inbox.id, Delivery.channel == "feishu"
        )
    ):
        db.add(Delivery(inbox_id=inbox.id, channel="feishu"))


async def send_deliveries():
    with Session() as db:
        ids = list(db.scalars(select(Delivery.id).where(Delivery.status == "pending")))
    for delivery_id in ids:
        with Session() as db:
            delivery = get(db, Delivery, delivery_id)
            inbox = get(db, Inbox, delivery.inbox_id)
            subscription_ids = sorted(
                {item["subscription_id"] for item in inbox.goal_reasons}
            )
        acquired = []
        try:
            for subscription_id in subscription_ids:
                lock = subscription_lock(subscription_id)
                await lock.acquire()
                acquired.append(lock)
            with Session() as db:
                delivery = get(db, Delivery, delivery_id)
                inbox = get(db, Inbox, delivery.inbox_id)
                job = db.get(Job, inbox.job_id) if inbox.job_id else None
                valid = []
                for reason in inbox.goal_reasons:
                    sub = db.get(Subscription, reason["subscription_id"])
                    if sub and job and eligible(db, sub, job, reason["kind"]):
                        valid.append(reason)
                if not valid:
                    delivery.status = "cancelled"
                    db.commit()
                    continue
                inbox.goal_reasons = valid
                webhook = setting(db, "feishu_webhook", "")
                if not webhook:
                    delivery.status = "failed"
                    delivery.error = "尚未配置飞书 Webhook"
                    db.commit()
                    continue
                delivery.status = "sending"
                delivery.attempts += 1
                db.commit()
                try:
                    async with httpx.AsyncClient(timeout=20) as client:
                        response = await client.post(
                            webhook,
                            json={
                                "msg_type": "text",
                                "content": {"text": inbox.title + "\n" + inbox.body},
                            },
                        )
                        response.raise_for_status()
                        payload = response.json()
                        if payload.get("code", payload.get("StatusCode", 0)) != 0:
                            raise ValueError("渠道拒绝了消息")
                    delivery.status = "accepted"
                    delivery.sent_at = now()
                    delivery.error = ""
                except (httpx.TimeoutException, httpx.NetworkError):
                    delivery.status = "unknown"
                    delivery.error = "渠道是否收到尚未确认，重试前请核对"
                except Exception as error:
                    delivery.status = "failed"
                    delivery.error = str(error)[:200]
                db.commit()
        finally:
            for lock in reversed(acquired):
                lock.release()


async def tick():
    from .execution import dispatch

    with Session() as db:
        due = list(
            db.scalars(
                select(Subscription).where(
                    Subscription.enabled.is_(True), Subscription.next_run_at <= now()
                )
            )
        )
        run_ids = []
        for sub in due:
            occurrence = sub.next_run_at
            if db.scalar(
                select(Check.id).where(
                    Check.subscription_id == sub.id, Check.occurrence_key == occurrence
                )
            ):
                continue
            active = db.scalar(
                select(Run.id).where(
                    Run.goal_id == sub.goal_id,
                    Run.kind == "discovery",
                    Run.status.in_(["queued", "running"]),
                )
            )
            if active:
                continue
            run = create_run(
                db,
                "discovery",
                goal_id=sub.goal_id,
                context={
                    "subscription_id": sub.id,
                    "mode": "search",
                    "missed_since": occurrence,
                },
            )
            db.add(
                Check(subscription_id=sub.id, occurrence_key=occurrence, run_id=run.id)
            )
            sub.next_run_at = next_due(sub.config, anchor=occurrence)
            run_ids.append(run.id)
        db.commit()
    for run_id in run_ids:
        dispatch(run_id)
    await send_deliveries()
