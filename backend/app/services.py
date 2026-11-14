import re
from calendar import monthrange

from sqlalchemy import select

from .common import get
from .database import (
    Action,
    Company,
    Decision,
    Event,
    Evidence,
    Fact,
    Goal,
    JobSource,
    Match,
    Profile,
    Progress,
    Run,
    Setting,
    serialize,
    now,
)


def setting(db, key, default=None):
    row = db.get(Setting, key)
    return row.value if row is not None else default


def job_out(db, job, goal_id=None):
    result = serialize(job)
    result["company"] = get(db, Company, job.company_id).name
    if goal_id:
        goal = get(db, Goal, goal_id)
        result["assessment"] = assess(db, job, goal)
        decision = db.scalar(
            select(Decision).where(
                Decision.goal_id == goal_id, Decision.job_id == job.id
            )
        )
        result["decision"] = serialize(decision) if decision else {"value": "undecided"}
    return result


def assess(db, job, goal):
    profile = db.get(Profile, 1)
    person = profile.data if profile else {}
    requirements = job.requirements or {}
    versions = {
        "profile": profile.revision if profile else 0,
        "goal": goal.revision,
        "job": job.revision,
        "rules": "2.1",
    }
    prior = db.scalar(
        select(Match).where(Match.job_id == job.id, Match.goal_id == goal.id)
    )
    if prior and prior.versions == versions:
        return prior.assessment
    checks = []

    def add(key, label, requirement, candidate, result=None, reason=""):
        if result is None:
            result = "unknown"
        checks.append(
            {
                "key": key,
                "label": label,
                "requirement": requirement,
                "candidate": candidate,
                "result": result,
                "reason": reason
                or (
                    "资料或岗位要求尚不完整"
                    if result == "unknown"
                    else "依据当前条件比较"
                ),
            }
        )

    text = str(requirements.get("graduation_text") or "")
    years = [int(year) for year in re.findall(r"20\d{2}", text)]
    graduation = person.get("graduation_year")
    result = None
    precise_range = requirements.get("graduation_range")
    if precise_range:
        actual = person.get("graduation_date")
        if actual and len(actual) >= 7:
            lower = upper = actual
            if len(actual) == 7:
                year, month = map(int, actual.split("-"))
                lower = actual + "-01"
                upper = f"{actual}-{monthrange(year, month)[1]:02d}"
            result = (
                "pass"
                if precise_range[0] <= lower and upper <= precise_range[1]
                else "fail"
                if upper < precise_range[0] or lower > precise_range[1]
                else "unknown"
            )
    elif requirements.get("all_students") or "全体在校" in text or "在校生" in text:
        if person.get("in_school") is not None:
            result = "pass" if person["in_school"] else "fail"
    elif years and graduation:
        year = int(graduation)
        if any(term in text for term in ["及以后", "及之后", "以后", "之后"]):
            passed = year >= min(years)
        elif any(term in text for term in ["及以前", "及之前"]):
            passed = year <= max(years)
        elif len(years) > 1 and re.search(r"[-—~至到]", text):
            passed = min(years) <= year <= max(years)
        else:
            passed = year in years
        result = "pass" if passed else "fail"
    add(
        "graduation",
        "毕业条件",
        precise_range or text or None,
        person.get("graduation_date") or graduation,
        result,
    )
    wanted_type = goal.recruitment_type
    actual_type = job.recruitment_type
    add(
        "recruitment_type",
        "招聘类型",
        actual_type or None,
        wanted_type or None,
        ("pass" if wanted_type in actual_type or actual_type in wanted_type else "fail")
        if wanted_type and actual_type
        else None,
    )
    city_hard = goal.constraints.get("cities", [])
    cities = city_hard or goal.preferences.get("cities", [])
    regions = {
        "江苏": [
            "南京",
            "苏州",
            "无锡",
            "常州",
            "南通",
            "扬州",
            "镇江",
            "徐州",
            "连云港",
            "淮安",
            "盐城",
            "泰州",
            "宿迁",
            "江苏",
        ],
        "浙江": ["杭州", "宁波", "绍兴", "嘉兴", "温州", "金华", "浙江"],
        "上海": ["上海"],
    }
    if "江浙沪" in cities:
        cities = [
            *([city for city in cities if city != "江浙沪"]),
            "江苏",
            "浙江",
            "上海",
        ]
    expanded = [city for region in cities for city in regions.get(region, [region])]
    city_match = (
        any(city in job.city for city in expanded) if expanded and job.city else None
    )
    add(
        "city",
        "工作地点",
        job.city or None,
        cities or None,
        ("pass" if city_match else "fail")
        if city_hard and city_match is not None
        else ("pass" if job.city and cities else None),
        "偏好范围外，保留为可考虑机会" if not city_hard and city_match is False else "",
    )
    for key, label in [
        ("days_per_week", "每周天数"),
        ("duration_months", "实习时长（月）"),
    ]:
        need = requirements.get(key)
        actual = person.get(key)
        add(
            key,
            label,
            need,
            actual,
            ("pass" if float(actual) >= float(need) else "fail")
            if need is not None and actual is not None
            else None,
        )
    required_start = requirements.get("start_before")
    available = person.get("available_from")
    add(
        "start",
        "到岗日期",
        required_start,
        available,
        ("pass" if available <= required_start else "fail")
        if required_start and available
        else None,
    )
    disputed = set(requirements.get("conflicted_fields", []))
    field_map = {
        "graduation": "graduation_text",
        "city": "city",
        "recruitment_type": "recruitment_type",
        "start": "start_before",
    }
    for check in checks:
        if field_map.get(check["key"], check["key"]) in disputed:
            check["result"] = "unknown"
            check["reason"] = "来源存在冲突，请核对证据"
    aliases = {
        "产品": ["产品", "product"],
        "AI": ["ai", "大模型", "人工智能", "智能体"],
        "Agent": ["agent", "智能体"],
        "RAG": ["rag", "检索增强"],
        "后端": ["后端", "backend", "服务端"],
        "前端": ["前端", "frontend"],
        "运营": ["运营", "operation"],
        "算法": ["算法", "algorithm"],
        "测试": ["测试", "test engineer"],
    }
    direction = goal.direction.casefold()
    searchable = (job.title + " " + job.description).casefold()
    alternatives = re.split(r"[、，,；;]", direction)
    relevant = []
    related = False
    for alternative in alternatives:
        groups = [
            (key, variants)
            for key, variants in aliases.items()
            if any(alias.casefold() in alternative for alias in variants)
        ]
        if not groups:
            groups = [
                (term, [term]) for term in re.split(r"[\s/]+", alternative) if term
            ]
        matched = [
            key
            for key, variants in groups
            if any(alias.casefold() in searchable for alias in variants)
        ]
        related = related or bool(groups) and len(matched) == len(groups)
        relevant.extend(key for key in matched if key not in relevant)
    score = (
        min(100, 30 + 25 * len(relevant) + (10 if city_match else 0)) if relevant else 0
    )
    failed = [item for item in checks if item["result"] == "fail"]
    unknown = [item for item in checks if item["result"] == "unknown"]
    facts = list(
        db.scalars(select(Fact).where(Fact.active.is_(True), Fact.confirmed.is_(True)))
    )
    active_resume_id = person.get("active_resume_id")
    if active_resume_id:
        facts = [fact for fact in facts if fact.resume_id in [None, active_resume_id]]
    keywords = [
        "Python",
        "Java",
        "SQL",
        "用户研究",
        "需求分析",
        "产品设计",
        "原型",
        "大模型",
        "智能体",
    ]
    strengths = []
    for keyword in keywords:
        if keyword.casefold() not in searchable:
            continue
        fact = next(
            (fact for fact in facts if keyword.casefold() in fact.value.casefold()),
            None,
        )
        if fact:
            strengths.append(
                {"keyword": keyword, "fact_id": fact.id, "text": fact.value[:150]}
            )
    evidence_ids = list(
        db.scalars(
            select(Evidence.id)
            .join(JobSource)
            .where(JobSource.job_id == job.id)
            .order_by(Evidence.id.desc())
            .limit(8)
        )
    )
    for check in checks:
        check["evidence_refs"] = evidence_ids
    result = {
        "checks": checks,
        "strengths": strengths,
        "status": "fail" if failed else "unknown" if unknown else "pass",
        "score": score,
        "direction_related": related,
        "reasons": [f"职责包含 {term}" for term in relevant],
        "pending": [item["label"] for item in unknown],
        "rules_version": "2.1",
    }
    match = db.scalar(
        select(Match).where(Match.job_id == job.id, Match.goal_id == goal.id)
    )
    if match is None:
        match = Match(job_id=job.id, goal_id=goal.id)
        db.add(match)
    match.versions = versions
    match.assessment = result
    return result


def project_application(db, application):
    completed = list(
        db.scalars(
            select(Progress)
            .where(
                Progress.application_id == application.id, Progress.state == "completed"
            )
            .order_by(Progress.sequence, Progress.id)
        )
    )
    if completed:
        application.stage = completed[-1].label
    else:
        application.stage = "准备中"
    application.revision += 1
    return application


def append_progress(
    db,
    application,
    label,
    state="completed",
    occurred_at=None,
    planned_at=None,
    data=None,
    sequence=None,
):
    events = list(
        db.scalars(select(Progress).where(Progress.application_id == application.id))
    )
    row = Progress(
        application_id=application.id,
        label=label,
        state=state,
        occurred_at=occurred_at or (now() if state == "completed" else None),
        planned_at=planned_at,
        sequence=sequence
        if sequence is not None
        else max([e.sequence for e in events], default=0) + 1,
        data=data or {},
    )
    db.add(row)
    db.flush()
    project_application(db, application)
    if state == "planned":
        db.add(
            Action(
                application_id=application.id,
                title=label,
                due_at=planned_at,
                data={"progress_id": row.id},
            )
        )
    return row


def create_run(
    db, kind, goal_id=None, thread_id=None, application_id=None, context=None
):
    run = Run(
        kind=kind,
        goal_id=goal_id,
        thread_id=thread_id,
        application_id=application_id,
        context=context or {},
    )
    db.add(run)
    db.flush()
    db.add(Event(run_id=run.id, type="queued", data={"message": "任务已排队"}))
    return run


def add_event(db, run, event_type, message="", **data):
    row = Event(run_id=run.id, type=event_type, data={"message": message, **data})
    db.add(row)
    db.commit()
    return row


def company_out(db, company):
    from .database import GoalCompany, Source

    result = serialize(company)
    result["sources"] = [
        serialize(row)
        for row in db.scalars(select(Source).where(Source.company_id == company.id))
    ]
    result["goals"] = [
        serialize(row)
        for row in db.scalars(
            select(GoalCompany).where(GoalCompany.company_id == company.id)
        )
    ]
    return result


def record_usage(db, model, purpose, tokens, run_id=None):
    from .database import Usage

    input_tokens = int(tokens.get("input", tokens.get("prompt_tokens", 0)) or 0)
    output_tokens = int(tokens.get("output", tokens.get("completion_tokens", 0)) or 0)
    input_price = setting(db, "llm_input_price_rmb_per_million")
    output_price = setting(db, "llm_output_price_rmb_per_million")
    estimated = (
        (input_tokens * float(input_price) + output_tokens * float(output_price))
        / 1_000_000
        if input_price is not None and output_price is not None
        else None
    )
    db.add(
        Usage(
            run_id=run_id,
            model=model,
            purpose=purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_rmb=estimated,
        )
    )
