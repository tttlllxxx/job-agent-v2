import asyncio

from fastapi import HTTPException
from sqlalchemy import select

from .common import get
from .database import (
    Application,
    Approval,
    Fact,
    FillSession,
    Resume,
    Snapshot,
    now,
)

FIELD_ALIASES = {
    "name": ["姓名", "name", "full name"],
    "email": ["邮箱", "email", "e-mail"],
    "phone": ["手机", "电话", "phone", "mobile"],
    "school": ["学校", "school", "university"],
    "major": ["专业", "major"],
    "degree": ["学历", "degree"],
    "graduation": ["毕业", "graduation"],
    "city": ["城市", "city"],
    "linkedin": ["linkedin"],
    "github": ["github"],
}
SENSITIVE = [
    "身份证",
    "护照",
    "性别",
    "民族",
    "婚姻",
    "残疾",
    "健康",
    "宗教",
    "政治",
    "薪资",
    "证件",
    "passport",
    "gender",
    "salary",
    "disability",
]
SCAN_SCRIPT = r"""() => {
 const fields = Array.from(document.querySelectorAll('input,textarea,select')).filter(e => !['hidden','submit','button','password','file'].includes(e.type) && e.getClientRects().length && getComputedStyle(e).visibility !== "hidden").map((e,index) => {
  const id = e.id || e.name || `field-${index}`;
  const label = e.labels?.[0]?.innerText || e.getAttribute('aria-label') || e.placeholder || e.name || id;
  const value = ['checkbox','radio'].includes(e.type) ? e.checked : e.value;
  return {key:`${id}::${index}`,index,label,type:e.type || e.tagName.toLowerCase(),required:e.required,has_value:Boolean(value),value,options:e.options ? Array.from(e.options).map(o=>({label:o.text,value:o.value})) : []};
 });
 const blockers = [];
 if (document.querySelector('input[type=password]')) blockers.push('页面要求登录，请在浏览器中完成');
 if (/验证码|captcha|人机验证/i.test(document.body.innerText)) blockers.push('页面可能需要验证码，请人工核对');
 const submit = Array.from(document.querySelectorAll('button,input[type=submit]')).filter(e=>e.getClientRects().length).find(e=>/^(提交申请|确认提交|提交|Submit application|Submit)$/i.test((e.innerText||e.value||'').trim()));
 return {url:location.href,fields,blockers,submit_text:submit ? (submit.innerText||submit.value).trim() : null};
}"""


def build_snapshot(db, session, url, fields, blockers):
    get(db, Application, session.application_id)
    active = db.scalar(select(Resume).where(Resume.active.is_(True)))
    facts = list(
        db.scalars(select(Fact).where(Fact.confirmed.is_(True), Fact.active.is_(True)))
    )
    if active:
        facts = [fact for fact in facts if fact.resume_id in [None, active.id]]
    preview = []
    for field in fields:
        label = str(field.get("label", "")).casefold()
        candidates = []
        for fact in facts:
            field_key = fact.metadata_.get("field_key") or fact.key
            if field_key in FIELD_ALIASES and any(
                alias in label for alias in FIELD_ALIASES[field_key]
            ):
                candidates.append(fact)
        answer = session.answers.get(field["key"])
        if answer is not None:
            proposed = answer
            source = "application_answer"
        elif len(candidates) == 1:
            proposed = candidates[0].value
            source = f"fact:{candidates[0].id}"
        else:
            proposed = None
            source = None
        sensitive = any(term in label for term in SENSITIVE)
        state = (
            "existing"
            if field.get("has_value")
            else "sensitive"
            if sensitive
            else "ready"
            if proposed is not None
            else "missing"
        )
        preview.append(
            {
                **field,
                "proposed": proposed,
                "source": source,
                "sensitive": sensitive,
                "state": state,
            }
        )
    snapshot = Snapshot(
        fill_session_id=session.id,
        url=url,
        fields=fields,
        preview=preview,
        blockers=blockers,
    )
    db.add(snapshot)
    db.flush()
    session.pages = [
        *session.pages,
        {"snapshot_id": snapshot.id, "url": url, "status": "scanned", "at": now()},
    ]
    session.status = "preview"
    db.commit()
    return snapshot


def approve_fill(
    db, session, snapshot, selection, sensitive, overwrite, answers, operation_id
):
    if session.status == "needs_scan":
        raise HTTPException(409, "请重新扫描当前网页后继续")
    if snapshot.fill_session_id != session.id:
        raise HTTPException(409, "页面快照与申请不一致")
    latest_id = db.scalar(
        select(Snapshot.id)
        .where(Snapshot.fill_session_id == session.id)
        .order_by(Snapshot.id.desc())
    )
    if snapshot.id != latest_id:
        raise HTTPException(409, "已有更新的页面快照，请核对最新预览")
    session.answers = {**session.answers, **answers}
    fields = {field["key"]: field for field in snapshot.preview}
    actions = []
    for key in selection:
        field = fields.get(key)
        if not field:
            raise HTTPException(422, f"找不到字段 {key}")
        if field["sensitive"] and key not in sensitive:
            raise HTTPException(403, "敏感字段需要单独授权")
        if field.get("has_value") and key not in overwrite:
            continue
        value = answers.get(key, field.get("proposed"))
        if value is None:
            raise HTTPException(422, "缺失答案需要补充后再填写")
        actions.append(
            {
                "key": key,
                "index": field.get("index"),
                "label": field["label"],
                "value": value,
                "type": field.get("type"),
            }
        )
    approval = Approval(
        fill_session_id=session.id,
        snapshot_id=snapshot.id,
        operation_id=operation_id,
        status="approved",
        data={
            "url": snapshot.url,
            "actions": actions,
            "fields": snapshot.fields,
            "overwrite": overwrite,
        },
    )
    db.add(approval)
    session.status = "ready_to_fill"
    db.flush()
    return approval


class BrowserExecutor:
    def __init__(self):
        self.driver = None
        self.context = None
        self.pages = {}
        self.lock = asyncio.Lock()

    async def page(self, session_id, url=None):
        from playwright.async_api import async_playwright
        from .config import settings

        if self.context is None:
            self.driver = await async_playwright().start()
            self.context = await self.driver.chromium.launch_persistent_context(
                str(settings().data_dir / "browser-profile"), headless=False
            )
        if session_id not in self.pages or self.pages[session_id].is_closed():
            self.pages[session_id] = await self.context.new_page()
            if url:
                await self.pages[session_id].goto(
                    url, wait_until="domcontentloaded", timeout=45000
                )
        return self.pages[session_id]

    async def scan(self, db, session):
        async with self.lock:
            application = get(db, Application, session.application_id)
            page = await self.page(session.id, application.url)
            result = await page.evaluate(SCAN_SCRIPT)
            snapshot = build_snapshot(
                db, session, result["url"], result["fields"], result["blockers"]
            )
            return snapshot, result.get("submit_text")

    async def execute(self, db, approval):
        async with self.lock:
            session = get(db, FillSession, approval.fill_session_id)
            page = await self.page(session.id)
            current = await page.evaluate(SCAN_SCRIPT)
            expected = approval.data["fields"]
            structure = lambda fields: [
                (item["key"], item.get("type"), item.get("label")) for item in fields
            ]
            if current["url"] != approval.data["url"] or structure(
                current["fields"]
            ) != structure(expected):
                approval.status = "invalid"
                db.commit()
                raise HTTPException(409, "页面已变化，请重新扫描")
            if approval.status != "approved":
                raise HTTPException(409, "授权已消费，请核对执行结果")
            current_fields = {field["key"]: field for field in current["fields"]}
            expected_fields = {field["key"]: field for field in expected}
            for action in approval.data["actions"]:
                field = current_fields[action["key"]]
                if action["key"] not in approval.data.get(
                    "overwrite", []
                ) and field.get("value") != expected_fields[action["key"]].get("value"):
                    raise HTTPException(409, "字段已有值发生变化，请重新扫描并核对")
            approval.status = "executing"
            db.commit()
            results = []
            try:
                # Resolve by the scanned visible field order rather than interpolating page-controlled selectors.
                for action in approval.data["actions"]:
                    locator = (
                        page.locator(
                            "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=password]):not([type=file]),textarea,select"
                        )
                        .filter(visible=True)
                        .nth(action["index"])
                    )
                    if action["type"] in ["checkbox", "radio"]:
                        checked = str(action["value"]).lower() in [
                            "true",
                            "yes",
                            "1",
                            "是",
                        ]
                        await locator.set_checked(checked)
                        verified = await locator.is_checked() == checked
                    elif action["type"] == "select-one":
                        await locator.select_option(label=str(action["value"]))
                        verified = bool(await locator.input_value())
                    else:
                        await locator.fill(str(action["value"]))
                        verified = await locator.input_value() == str(action["value"])
                    results.append({"key": action["key"], "verified": verified})
                approval.status = "consumed"
                session.status = "waiting_user"
                session.pages = [
                    *session.pages,
                    {
                        "snapshot_id": approval.snapshot_id,
                        "status": "filled",
                        "results": results,
                        "at": now(),
                    },
                ]
                db.commit()
                return {
                    "results": results,
                    "message": "请核对当前页面，跨页后重新扫描，文件上传与提交由用户处理",
                }
            except Exception:
                approval.status = "result_unknown"
                session.status = "needs_scan"
                db.commit()
                raise

    async def close(self):
        if self.context:
            await self.context.close()
        if self.driver:
            await self.driver.stop()


browser = BrowserExecutor()
