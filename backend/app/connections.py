import asyncio
import json
import sys

from fastapi import HTTPException
from sqlalchemy import select

from .common import get
from .database import Application, Inbox, Legacy, now
from .services import setting

MAIL_SCRIPT = r"""ObjC.import('Foundation');
const Mail=Application('Mail');
const messages=Mail.inbox.messages();
const result=[];
for(let i=0;i<Math.min(messages.length,100);i++){
 const message=messages[i];
 const subject=message.subject()||'';
 if(/面试|笔试|测评|招聘|申请|offer|interview|application/i.test(subject)) result.push({external_id:String(message.id()),subject,body:message.content().slice(0,14000),received_at:message.dateReceived().toISOString()});
}
JSON.stringify(result);"""
CALENDAR_SCRIPT = r"""function run(argv){
 const args=JSON.parse(argv[0]); const app=Application('Calendar');
 let calendars=app.calendars.whose({name:args.calendar})();
 if(!calendars.length){const calendar=app.Calendar({name:args.calendar});app.calendars.push(calendar);calendars=[calendar];}
 const calendar=calendars[0];
 const events=calendar.events.whose({summary:args.title})();
 const existing=events.find(event=>event.description().includes(args.reference));
 if(existing)return JSON.stringify({external_id:existing.uid(),existing:true});
 const event=app.Event({summary:args.title,startDate:new Date(args.start),endDate:new Date(args.end),description:args.reference});calendar.events.push(event);
 return JSON.stringify({external_id:event.uid()});
}"""


async def run_script(script, arguments=None):
    if sys.platform != "darwin":
        raise HTTPException(422, "邮件和日历连接需要 macOS 本地运行")
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/osascript",
        "-l",
        "JavaScript",
        "-e",
        script,
        *([json.dumps(arguments)] if arguments else []),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(), 45)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise HTTPException(504, "系统应用未响应，请核对自动化权限")
    if process.returncode:
        raise HTTPException(422, "系统连接失败，请检查应用是否打开及自动化权限")
    return json.loads(output.decode())


async def sync_mail(db):
    if not setting(db, "mail_enabled", False):
        raise HTTPException(409, "邮件连接尚未启用")
    records = await run_script(MAIL_SCRIPT)
    added = []
    for record in records:
        if db.scalar(
            select(Legacy.id).where(
                Legacy.source_table == "external_mail_events",
                Legacy.source_id == record["external_id"],
            )
        ):
            continue
        row = Legacy(
            source_table="external_mail_events",
            source_id=record["external_id"],
            data={**record, "status": "needs_review"},
        )
        db.add(row)
        db.flush()
        db.add(
            Inbox(
                event_key=f"mail:{record['external_id']}",
                title=record["subject"],
                body="招聘邮件待核对，请确认关联申请及事件后再更新进度。",
                goal_reasons=[],
            )
        )
        added.append(row.id)
    db.commit()
    return {"added": added, "checked_at": now()}


async def calendar_event(db, progress):
    if not setting(db, "calendar_enabled", False):
        raise HTTPException(409, "日历连接尚未启用")
    if not progress.planned_at:
        raise HTTPException(422, "该事件没有计划时间")
    application = get(db, Application, progress.application_id)
    from datetime import datetime, timedelta

    start = datetime.fromisoformat(progress.planned_at.replace("Z", "+00:00"))
    result = await run_script(
        CALENDAR_SCRIPT,
        {
            "calendar": setting(db, "calendar_name", "求职"),
            "title": f"{application.company} · {progress.label}",
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
            "reference": f"JobAgent progress:{progress.id}",
        },
    )
    existing = db.scalar(
        select(Legacy).where(
            Legacy.source_table == "calendar_event_links",
            Legacy.source_id == str(progress.id),
        )
    )
    if existing:
        existing.data = {**result, "progress_event_id": progress.id}
    else:
        db.add(
            Legacy(
                source_table="calendar_event_links",
                source_id=str(progress.id),
                data={**result, "progress_event_id": progress.id},
            )
        )
    db.commit()
    return result
