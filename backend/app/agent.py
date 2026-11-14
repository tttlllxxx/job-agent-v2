import asyncio
import json

from sqlalchemy import select

from .common import get
from .config import ROOT
from .database import (
    Event,
    Goal,
    Message,
    Profile,
    Run,
    Session,
    Step,
    Thread,
    serialize,
)
from .providers import model_config


class AgentBridge:
    def __init__(self):
        self.process = None
        self.reader = None
        self.pending = {}
        self.sequence = 0
        self.lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()
        self.callbacks = set()

    async def start(self):
        if self.process and self.process.returncode is None:
            return
        self.process = await asyncio.create_subprocess_exec(
            "node",
            str(ROOT / "agent-runtime/dist/index.js"),
            cwd=str(ROOT / "agent-runtime"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.reader = asyncio.create_task(self.read())

    async def write(self, message):
        async with self.write_lock:
            self.process.stdin.write(
                (json.dumps(message, ensure_ascii=False) + "\n").encode()
            )
            await self.process.stdin.drain()

    async def read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if message.get("method") == "tool.execute":
                    task = asyncio.create_task(self.handle_tool(message))
                    self.callbacks.add(task)
                    task.add_done_callback(self.callbacks.discard)
                elif message.get("method") == "agent.event":
                    data = message["params"]
                    if data.get("type") == "text_delta":
                        with Session() as db:
                            run = db.get(Run, data["run_id"])
                            reply = (
                                db.get(Message, run.context.get("assistant_message_id"))
                                if run
                                else None
                            )
                            if reply:
                                reply.content += data.get("delta") or ""
                                db.add(
                                    Event(
                                        run_id=run.id,
                                        type="text_delta",
                                        data={"delta": data.get("delta", "")},
                                    )
                                )
                                db.commit()
                elif message.get("id") in self.pending:
                    future = self.pending.pop(message["id"])
                    if not future.done():
                        if message.get("error"):
                            future.set_exception(
                                ValueError(message["error"]["message"])
                            )
                        else:
                            future.set_result(message.get("result"))
        except Exception:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(
                        ValueError("Agent 连接中断，请查看已完成记录后继续")
                    )
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ValueError("Agent 进程已退出"))
            self.pending.clear()

    async def handle_tool(self, message):
        try:
            params = message["params"]
            result = await execute_tool(
                params["run_id"], params["name"], params.get("arguments") or {}
            )
            await self.write({"jsonrpc": "2.0", "id": message["id"], "result": result})
        except Exception as error:
            await self.write(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32000, "message": str(error)[:500]},
                }
            )

    async def request(self, method, params):
        await self.start()
        self.sequence += 1
        key = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        await self.write(
            {"jsonrpc": "2.0", "id": key, "method": method, "params": params}
        )
        try:
            return await asyncio.wait_for(future, 330)
        finally:
            self.pending.pop(key, None)

    async def prompt(self, run_id):
        async with self.lock:
            with Session() as db:
                run = get(db, Run, run_id)
                thread = get(db, Thread, run.thread_id)
                history = list(
                    db.scalars(
                        select(Message)
                        .where(Message.thread_id == thread.id)
                        .order_by(Message.id.desc())
                        .limit(25)
                    )
                )
                goals = list(db.scalars(select(Goal).where(Goal.archived.is_(False))))
                profile = db.get(Profile, 1)
                context = {
                    "current_goal_id": run.goal_id,
                    "goals": [serialize(goal) for goal in goals],
                    "profile": serialize(profile) if profile else None,
                    "summary": thread.summary,
                    "history": [
                        {"role": message.role, "content": message.content[:6000]}
                        for message in reversed(history)
                        if message.content
                    ],
                }
                provider = model_config(db)
                prompt = run.context["content"]
            return await self.request(
                "agent.prompt",
                {
                    "run_id": run_id,
                    "prompt": prompt,
                    "context": context,
                    "provider": provider,
                },
            )

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.reader:
            self.reader.cancel()
        for task in self.callbacks:
            task.cancel()


bridge = AgentBridge()


async def execute_tool(run_id, name, args):
    operation = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
    with Session() as db:
        run = get(db, Run, run_id)
        if run.cancellation_requested:
            raise ValueError("任务已中止")
        step = db.scalar(
            select(Step).where(Step.run_id == run_id, Step.operation_key == operation)
        )
        if (
            step
            and step.status == "completed"
            and name
            in [
                "update_context",
                "discover_jobs",
                "expand_companies",
                "set_job_decision",
                "manage_subscription",
                "prepare_materials",
                "start_fill",
                "manage_application",
            ]
        ):
            return step.result["value"]
        if step is None:
            step = Step(run_id=run_id, operation_key=operation, tool=name)
            db.add(step)
        step.status = "running"
        db.add(Event(run_id=run_id, type="tool_started", data={"tool": name}))
        db.commit()
        step_id = step.id
    try:
        result = await _execute_tool(run_id, name, args)
        with Session() as db:
            run = get(db, Run, run_id)
            step = get(db, Step, step_id)
            if run.cancellation_requested:
                step.status = "cancelled"
                db.commit()
                raise ValueError("任务已中止，已完成的业务操作保留在对应记录中")
            step.status = "completed"
            step.result = {"value": result}
            if name in [
                "discover_jobs",
                "expand_companies",
                "prepare_materials",
            ] and isinstance(result, dict):
                child = db.get(Run, result.get("id"))
                if child:
                    child.thread_id = run.thread_id
                    child.context = {**child.context, "parent_run_id": run_id}
            db.add(
                Event(
                    run_id=run_id,
                    type="tool_finished",
                    data={"tool": name, "message": f"{name} 已完成"},
                )
            )
            db.commit()
        return result
    except Exception as error:
        with Session() as db:
            run = get(db, Run, run_id)
            step = get(db, Step, step_id)
            step.status = "cancelled" if run.cancellation_requested else "failed"
            step.result = (
                {} if run.cancellation_requested else {"error": str(error)[:500]}
            )
            db.add(
                Event(
                    run_id=run_id,
                    type="tool_failed",
                    data={"tool": name, "message": "工具未完成"},
                )
            )
            db.commit()
        raise


async def _execute_tool(run_id, name, args):
    from . import api
    from .schemas import (
        ApplicationInput,
        DiscoverInput,
        EventInput,
        FillInput,
        GoalInput,
        GoalPatch,
        MaterialInput,
        ProfilePatch,
        SubscriptionInput,
        SubscriptionPatch,
    )
    from .database import (
        Application,
        Company,
        Fact,
        Source,
        Subscription,
    )

    with Session() as db:
        run = get(db, Run, run_id)
        if run.cancellation_requested:
            raise ValueError("任务已中止")
        goal_id = args.get("goal_id") or run.goal_id

        def require_goal():
            if not goal_id:
                raise ValueError("请选择当前求职目标，或先说明求职方向")
            return get(db, Goal, goal_id)

        operation = f"agent:{run_id}:{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
        if name == "update_context":
            if args.get("profile_patch"):
                profile = get(db, Profile, 1)
                api.patch_profile(
                    ProfilePatch(
                        expected_revision=profile.revision,
                        data={**profile.data, **args["profile_patch"]},
                    ),
                    db,
                )
            if args.get("new_goal"):
                result = api.create_goal(
                    GoalInput(**args["new_goal"], operation_id=operation), db
                )
                goal_id = result["id"]
                run.goal_id = goal_id
                thread = get(db, Thread, run.thread_id)
                thread.active_goal_id = goal_id
                db.commit()
            if args.get("goal_patch"):
                goal = require_goal()
                api.patch_goal(
                    goal.id,
                    GoalPatch(expected_revision=goal.revision, **args["goal_patch"]),
                    db,
                )
            return {
                "profile": serialize(get(db, Profile, 1)),
                "goal": serialize(db.get(Goal, goal_id)) if goal_id else None,
            }
        if name == "list_goals":
            return api.list_goals(False, db)
        if name == "search_jobs":
            require_goal()
            return api.list_jobs(goal_id, args.get("query", ""), "", 0, 30, db)
        if name in ["discover_jobs", "expand_companies"]:
            require_goal()
            return await api.create_discovery(
                DiscoverInput(
                    operation_id=operation,
                    goal_id=goal_id,
                    urls=args.get("urls", []),
                    mode="companies"
                    if name == "expand_companies"
                    else args.get("mode", "search"),
                ),
                db,
            )
        if name == "get_job_assessment":
            return api.get_job(args["job_id"], goal_id, db)
        if name == "set_job_decision":
            require_goal()
            return api.decide_job(
                args["job_id"],
                {
                    "goal_id": goal_id,
                    "decision": args["decision"],
                    "reason": args.get("reason", ""),
                },
                db,
            )
        if name == "manage_subscription":
            require_goal()
            action = args["action"]
            if action == "create":
                return await api.create_subscription(
                    SubscriptionInput(
                        operation_id=operation,
                        goal_id=goal_id,
                        config=args.get("config", {}),
                    ),
                    db,
                )
            subscription = get(db, Subscription, args["id"])
            if action == "check":
                return await api.check_subscription(
                    subscription.id, {"operation_id": operation}, db
                )
            changes = (
                {"enabled": action == "resume"}
                if action in ["pause", "resume"]
                else {"config": args.get("config", {})}
            )
            return await api.patch_subscription(
                subscription.id,
                SubscriptionPatch(expected_revision=subscription.revision, **changes),
                db,
            )
        if name == "get_progress":
            if args.get("run_id"):
                return api.get_run(args["run_id"], db)
            if args.get("subscription_id"):
                return api.subscription_history(args["subscription_id"], db)
            return [
                serialize(row)
                for row in db.scalars(select(Run).order_by(Run.id.desc()).limit(10))
            ]
        if name == "prepare_materials":
            return await api.prepare_material(
                args["job_id"],
                MaterialInput(operation_id=operation, resume_id=args["resume_id"]),
                db,
            )
        if name == "start_fill":
            return api.start_fill(
                args["application_id"],
                FillInput(operation_id=operation, url=args["url"]),
                db,
            )
        if name == "manage_application":
            data = args["data"]
            if args["action"] == "create":
                return api.create_application(
                    ApplicationInput(**data, operation_id=operation), db
                )
            if args["action"] == "add_event":
                return api.create_progress(
                    args["application_id"],
                    EventInput(**data, operation_id=operation),
                    db,
                )
            raise ValueError("支持创建申请和添加进展事件")
        if name == "query_workspace":
            resource = args["resource"]
            models = {
                "applications": Application,
                "sources": Source,
                "actions": api.Action,
                "subscriptions": Subscription,
                "facts": Fact,
                "companies": Company,
            }
            if resource == "profile":
                return serialize(get(db, Profile, 1))
            if resource == "memory":
                query = args.get("query", "")
                return [
                    serialize(row)
                    for row in db.scalars(
                        select(Message)
                        .where(Message.content.contains(query))
                        .order_by(Message.id.desc())
                        .limit(30)
                    )
                ]
            if resource not in models:
                raise ValueError("不支持的查询对象")
            return [
                serialize(row)
                for row in db.scalars(select(models[resource]).limit(100))
            ]
        raise ValueError("工具未在业务白名单中")
