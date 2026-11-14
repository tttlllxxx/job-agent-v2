from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from .database import (
    Company,
    Evidence,
    GoalCompany,
    Job,
    JobEvent,
    JobSource,
    Source,
    now,
)
from .providers import generate_json, web_search
from .services import add_event, assess


def normalize_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ["http", "https"]
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ValueError("需要有效的 HTTP 或 HTTPS 岗位链接")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.startswith("utm_") and key not in ["spm", "from", "ref"]
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path, urlencode(query), "")
    )


async def read_page(url):
    url = normalize_url(url)
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "JobAgent/2.0 (personal job search)"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        if not response.headers.get("content-type", "").startswith(
            ("text/", "application/xhtml")
        ):
            raise ValueError("链接返回了非网页内容，请导入具体岗位详情页")
        soup = BeautifulSoup(response.text[:2_000_000], "html.parser")
        for element in soup(["script", "style", "nav", "footer"]):
            element.decompose()
        text = soup.get_text("\n", strip=True)
        if len(text) < 80:
            raise ValueError("页面缺少可读取详情，可能需要登录或浏览器渲染")
        return text[:35000], str(response.url)


def upsert_job(db, data, url, text, goal_id, source_kind="official"):
    url = normalize_url(url)
    company_name = str(data.get("company") or "").strip()
    title = str(data.get("title") or "").strip()
    description = str(data.get("description") or text).strip()
    if not company_name or not title or len(description) < 20:
        raise ValueError("岗位缺少公司、标题或招聘内容，已保留为待核验候选")
    employer = db.scalar(select(Company).where(Company.name == company_name))
    if employer is None:
        employer = Company(
            name=company_name,
            data={"size": None, "reason": data.get("company_reason", "招聘信息发现")},
        )
        db.add(employer)
        db.flush()
    link_goal = db.scalar(
        select(GoalCompany).where(
            GoalCompany.goal_id == goal_id, GoalCompany.company_id == employer.id
        )
    )
    if link_goal is None:
        db.add(
            GoalCompany(
                goal_id=goal_id, company_id=employer.id, reason="发现匹配招聘信息"
            )
        )
    host = urlsplit(url).netloc
    source = db.scalar(
        select(Source).where(Source.company_id == employer.id, Source.name == host)
    )
    if source is None:
        source = Source(company_id=employer.id, name=host, url=url, kind=source_kind)
        db.add(source)
        db.flush()
    if source.kind == "official":
        source_kind = "official"
    external = str(data.get("external_id") or url)
    linked = db.scalar(
        select(JobSource).where(
            JobSource.source_id == source.id, JobSource.external_id == external
        )
    )
    job = db.get(Job, linked.job_id) if linked else None
    # A known one-to-one application URL can connect sources. Shared list URLs remain distinct.
    application_url = normalize_url(data.get("application_url") or url)
    if job is None and (
        data.get("external_id")
        or data.get("application_url")
        and application_url != url
    ):
        candidate = db.scalar(
            select(Job).where(
                Job.company_id == employer.id,
                Job.url == application_url,
                Job.title == title,
                Job.city == str(data.get("city") or ""),
                Job.department == str(data.get("department") or ""),
            )
        )
        if candidate:
            existing_ids = list(
                db.scalars(
                    select(JobSource.external_id).where(
                        JobSource.job_id == candidate.id,
                        JobSource.source_id == source.id,
                    )
                )
            )
            if not existing_ids or external in existing_ids:
                job = candidate
    created = job is None
    if job is None:
        job = Job(company_id=employer.id, title=title)
        db.add(job)
        db.flush()
    observed_data = dict(data)
    previous_verified_at = job.verified_at
    current_sources = list(
        db.scalars(
            select(Source)
            .join(JobSource, JobSource.source_id == Source.id)
            .where(JobSource.job_id == job.id)
        )
    )
    previous_evidence = list(
        db.scalars(
            select(Evidence)
            .join(JobSource)
            .where(JobSource.job_id == job.id)
            .order_by(Evidence.id.desc())
            .limit(8)
        )
    )
    conflicts = []
    seen_evidence_sources = set()
    for evidence in previous_evidence:
        if (
            evidence.job_source_id in seen_evidence_sources
            or linked
            and evidence.job_source_id == linked.id
        ):
            continue
        seen_evidence_sources.add(evidence.job_source_id)
        prior_requirements = evidence.fields.get("requirements") or {}
        for key, incoming in (data.get("requirements") or {}).items():
            prior = prior_requirements.get(key)
            if prior is not None and incoming is not None and prior != incoming:
                conflicts.append(
                    {
                        "field": key,
                        "previous": prior,
                        "incoming": incoming,
                        "source": url,
                    }
                )
    keep_official = source_kind != "official" and any(
        item.kind == "official" for item in current_sources
    )
    if keep_official:
        application_url = job.url
        data = {
            **data,
            "title": job.title,
            "description": job.description,
            "city": job.city,
            "department": job.department,
            "recruitment_type": job.recruitment_type,
            "requirements": job.requirements,
            "program": job.program,
            "explicitly_closed": job.status == "closed",
            "published_at": job.published_at,
            "refreshed_at": job.refreshed_at,
            "deadline_at": job.deadline_at,
        }
    if conflicts:
        data = {
            **data,
            "requirements": {
                **(data.get("requirements") or {}),
                "source_conflicts": conflicts,
                "conflicted_fields": []
                if keep_official
                or source_kind == "official"
                and not any(item.kind == "official" for item in current_sources)
                else sorted({item["field"] for item in conflicts}),
            },
        }
    previous_status = job.status
    previous_requirements = job.requirements or {}
    title = str(data.get("title") or title)
    description = str(data.get("description") or description)
    next_status = (
        "closed"
        if data.get("explicitly_closed")
        else "open"
        if data.get("explicitly_closed") is False
        else "unverified"
    )
    if keep_official:
        next_status = previous_status
    else:
        anomalies = []
        if data.get("published_at") and data["published_at"][:10] > now()[:10]:
            anomalies.append("发布时间晚于核验日期，请核对原文")
            next_status = "unverified"
        if data.get("deadline_at"):
            try:
                deadline_text = data["deadline_at"]
                deadline = datetime.fromisoformat(deadline_text.replace("Z", "+00:00"))
                expired = (
                    deadline_text[:10] < now()[:10]
                    if len(deadline_text) == 10
                    else deadline.replace(tzinfo=deadline.tzinfo or UTC)
                    < datetime.now(UTC)
                )
                if expired:
                    next_status = "closed"
            except ValueError:
                anomalies.append("截止日期无法解析，请核对原文")
        if anomalies:
            data = {
                **data,
                "requirements": {
                    **(data.get("requirements") or {}),
                    "date_anomalies": anomalies,
                },
            }
    changed = (
        job.description != description
        or job.city != str(data.get("city") or "")
        or previous_requirements != (data.get("requirements") or {})
        or job.status != next_status
        or job.title != title
        or job.department != str(data.get("department") or "")
        or job.recruitment_type != str(data.get("recruitment_type") or "")
        or job.deadline_at != data.get("deadline_at")
    )
    if changed and not created:
        job.revision += 1
    job.title = title
    job.description = description
    job.city = str(data.get("city") or "")
    job.department = str(data.get("department") or "")
    job.recruitment_type = str(data.get("recruitment_type") or "")
    job.requirements = data.get("requirements") or {}
    job.program = data.get("program") or {}
    job.url = normalize_url(application_url)
    job.verified_at = now()
    job.published_at = data.get("published_at")
    job.refreshed_at = data.get("refreshed_at")
    job.deadline_at = data.get("deadline_at")
    job.status = next_status
    if keep_official:
        job.status = previous_status
        job.verified_at = previous_verified_at
    if linked is None:
        linked = JobSource(
            job_id=job.id, source_id=source.id, external_id=external, url=url
        )
        db.add(linked)
        db.flush()
    latest = db.scalar(
        select(Evidence)
        .where(Evidence.job_source_id == linked.id)
        .order_by(Evidence.id.desc())
    )
    if latest is None or latest.text != text:
        db.add(Evidence(job_source_id=linked.id, text=text, fields=observed_data))
    kind = (
        "first_observed"
        if created
        else "reopened"
        if previous_status == "closed" and job.status == "open"
        else "qualification_changed"
        if previous_requirements != job.requirements
        else None
    )
    if kind and not db.scalar(
        select(JobEvent).where(
            JobEvent.job_id == job.id,
            JobEvent.kind == kind,
            JobEvent.job_revision == job.revision,
        )
    ):
        db.add(
            JobEvent(
                job_id=job.id, kind=kind, job_revision=job.revision, data={"url": url}
            )
        )
    source.status = "healthy"
    source.last_checked_at = now()
    source.last_success_at = now()
    source.error = ""
    db.commit()
    return job, created


async def discover(db, run, goal, urls=None, mode="search", company_ids=None):
    queries = [
        f"{goal.direction} {goal.recruitment_type} 招聘 "
        + " ".join(goal.preferences.get("cities", []))
    ]
    if mode == "companies":
        queries.append(f"{goal.direction} 实习 招聘 创业公司 中小公司")
    coverage = []
    candidates = []
    failures = []
    results = []
    if urls:
        candidates = [{"url": url} for url in urls]
    else:
        for query in queries:
            if run.cancellation_requested:
                break
            add_event(db, run, "progress", "正在联网发现岗位", query=query)
            try:
                hits = await web_search(db, query)
                candidates.extend(hits)
                coverage.append(
                    {"query": query, "status": "completed", "count": len(hits)}
                )
            except Exception as error:
                failures.append({"query": query, "reason": str(error)[:300]})
    watched_sources = list(
        db.scalars(
            select(Source)
            .join(GoalCompany, GoalCompany.company_id == Source.company_id)
            .where(GoalCompany.goal_id == goal.id, GoalCompany.active.is_(True))
        )
    )
    for source in watched_sources:
        if not company_ids or source.company_id in company_ids:
            candidates.append({"url": source.url, "source_id": source.id})
    seen = set()
    for candidate in candidates:
        db.refresh(run)
        if run.cancellation_requested:
            break
        url = candidate.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        add_event(db, run, "progress", "正在读取和核验招聘信息", url=url)
        try:
            text, actual_url = await read_page(url)
            extracted = await generate_json(
                db,
                "从招聘网页提取具体岗位。返回 jobs 数组，每个包含 company,title,description,city,department,recruitment_type,external_id,application_url,published_at,refreshed_at,deadline_at,explicitly_closed,source_kind(official/platform/community/web),requirements。"
                "requirements 包含 graduation_text,graduation_range(精确日期区间),all_students,days_per_week,duration_months,start_before。"
                "必须引用原文，只返回明确存在的招聘岗位。公司项目要求放 program，具体岗位要求放 requirements。来源中没有的日期与要求保持 null。",
                {"url": actual_url, "text": text},
            )
            discovered = extracted.get("jobs", [])
            if not discovered:
                coverage.append({"url": url, "status": "no_jobs", "count": 0})
            for data in discovered[:50]:
                job, _ = upsert_job(
                    db,
                    data,
                    actual_url,
                    text,
                    goal.id,
                    str(data.get("source_kind") or "web"),
                )
                assessment = assess(db, job, goal)
                results.append({"id": job.id, "assessment": assessment})
            coverage.append(
                {"url": url, "status": "completed", "count": len(discovered)}
            )
            add_event(
                db,
                run,
                "result_batch",
                "已保存核验结果",
                job_ids=[item["id"] for item in results],
            )
        except Exception as error:
            failures.append({"url": url, "reason": str(error)[:300]})
            if candidate.get("source_id"):
                source = db.get(Source, candidate["source_id"])
                source.status = (
                    "restricted"
                    if "403" in str(error) or "登录" in str(error)
                    else "failed"
                )
                source.error = str(error)[:300]
                source.last_checked_at = now()
                db.commit()
    return {
        "job_ids": list(dict.fromkeys(item["id"] for item in results)),
        "coverage": coverage,
        "failures": failures,
        "status": "partial"
        if results and failures
        else "failed"
        if failures and not results
        else "completed",
        "checked_at": now(),
    }
