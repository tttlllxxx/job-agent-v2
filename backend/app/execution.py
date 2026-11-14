import asyncio

from sqlalchemy import select

from .agent import bridge
from .common import get
from .database import (
    Check,
    Goal,
    Message,
    Run,
    Session,
    Subscription,
)
from .services import add_event, record_usage

active_tasks = {}


def dispatch(run_id):
    if run_id in active_tasks:
        return
    task = asyncio.create_task(execute(run_id))
    active_tasks[run_id] = task
    task.add_done_callback(lambda _: active_tasks.pop(run_id, None))


async def execute(run_id):
    with Session() as db:
        run = get(db, Run, run_id)
        if run.status not in ["queued", "running"]:
            return
        run.status = "running"
        run.phase = run.kind
        db.commit()
        try:
            if run.kind == "discovery":
                from .discovery import discover
                from .monitoring import evaluate_check

                goal = get(db, Goal, run.goal_id)
                result = await discover(
                    db,
                    run,
                    goal,
                    run.context.get("urls"),
                    run.context.get("mode", "search"),
                    run.context.get("company_ids"),
                )
                db.refresh(run)
                db.refresh(goal)
                subscription_id = run.context.get("subscription_id")
                if subscription_id:
                    subscription = get(db, Subscription, subscription_id)
                    db.refresh(subscription)
                    evaluate_check(db, subscription, result)
                    check = db.scalar(select(Check).where(Check.run_id == run.id))
                    if check:
                        check.status = result["status"]
                        check.coverage = result
                run.result = result
                run.status = result["status"]
            elif run.kind == "conversation":
                response = await bridge.prompt(run.id)
                db.refresh(run)
                if run.cancellation_requested or not run.context.get(
                    "assistant_message_id"
                ):
                    run.status = "cancelled"
                    db.commit()
                    return
                reply = get(db, Message, run.context["assistant_message_id"])
                db.refresh(reply)
                reply.content = response.get("text") or reply.content
                run.result = {"message_id": reply.id, "usage": response.get("usage")}
                run.status = "completed"
                from .providers import model_config

                record_usage(
                    db,
                    model_config(db).get("model") or "unknown",
                    "conversation",
                    response.get("usage") or {},
                    run.id,
                )
            elif run.kind == "materials":
                from .materials import prepare

                result = await prepare(
                    db, run.context["job_id"], run.context["resume_id"]
                )
                run.result = {"material_id": result.id}
                run.status = (
                    "waiting_user" if result.status == "needs_facts" else "completed"
                )
            else:
                run.status = "waiting_user"
                run.error = "该历史任务需要在对应申请重新扫描或开始后续任务"
            db.refresh(run, ["cancellation_requested"])
            if run.cancellation_requested:
                run.status = "cancelled"
            db.commit()
            add_event(
                db,
                run,
                "run_finished",
                "任务状态已更新",
                status=run.status,
                result=run.result,
            )
        except asyncio.CancelledError:
            run.status = "cancelled"
            db.commit()
            raise
        except Exception as error:
            db.rollback()
            run = get(db, Run, run_id)
            run.status = "failed"
            run.error = str(error)[:1000]
            db.commit()
            add_event(
                db,
                run,
                "run_finished",
                "任务未能完成",
                status="failed",
                error=run.error,
            )


async def recover():
    with Session() as db:
        for run in db.scalars(select(Run).where(Run.status.in_(["queued", "running"]))):
            if run.kind == "discovery":
                run.status = "queued"
            else:
                run.status = "waiting_user"
                run.phase = "interrupted"
                run.error = "服务重启，已保留记录，请核对后继续"
        from .database import Delivery, Approval, FillSession

        for session in db.scalars(
            select(FillSession).where(FillSession.status != "completed")
        ):
            session.status = "needs_scan"
        for delivery in db.scalars(
            select(Delivery).where(Delivery.status == "sending")
        ):
            delivery.status = "unknown"
        for approval in db.scalars(
            select(Approval).where(Approval.status == "executing")
        ):
            approval.status = "result_unknown"
        db.commit()
        ids = list(db.scalars(select(Run.id).where(Run.status == "queued")))
    for run_id in ids:
        dispatch(run_id)


async def shutdown():
    for task in list(active_tasks.values()):
        task.cancel()
    await asyncio.gather(*list(active_tasks.values()), return_exceptions=True)
    await bridge.close()
