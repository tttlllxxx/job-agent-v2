from contextlib import asynccontextmanager
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .backups import apply_pending_restore

apply_pending_restore()

from .api import router
from .config import ROOT
from .database import Base, Profile, Session, engine
from .execution import recover, shutdown
from .filling import browser
from .monitoring import tick

logger = logging.getLogger("job_agent")


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with Session() as db:
        if not db.get(Profile, 1):
            db.add(Profile(id=1, data={}))
            db.commit()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(tick, "interval", seconds=30, max_instances=1, coalesce=True)
    scheduler.start()
    app.state.scheduler = scheduler
    await recover()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await shutdown()
        await browser.close()


app = FastAPI(title="职序 · 个人求职 Agent", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Workspace-Client", "Last-Event-ID"],
)


@app.middleware("http")
async def local_write_boundary(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method in [
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ]:
        if request.headers.get("x-workspace-client") != "job-agent":
            return JSONResponse(
                {
                    "code": "CLIENT_REQUIRED",
                    "message": "请通过本地工作台或扩展执行操作",
                },
                status_code=403,
            )
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error(request, error):
    detail = error.detail
    return JSONResponse(
        detail
        if isinstance(detail, dict)
        else {"code": f"HTTP_{error.status_code}", "message": str(detail)},
        status_code=error.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    return JSONResponse(
        {
            "code": "VALIDATION_ERROR",
            "message": "请检查字段格式",
            "field_errors": [
                {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                for item in error.errors()
            ],
        },
        status_code=422,
    )


@app.exception_handler(Exception)
async def internal_error(request, error):
    logger.error(
        "请求失败 %s %s (%s)", request.method, request.url.path, type(error).__name__
    )
    return JSONResponse(
        {"code": "INTERNAL_ERROR", "message": "操作未完成，请查看对应任务或重试"},
        status_code=500,
    )


app.include_router(router)


@app.get("/health/ready")
def health():
    return {"ready": True, "version": "2.0.0"}


dist = ROOT / "frontend/dist"
if (dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    if not (dist / "index.html").exists():
        raise HTTPException(503, "请先构建前端")
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})
