import json
import shutil
import sqlite3
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.engine import make_url

from .config import settings


def stage_restore(content):
    directory = settings().data_dir
    staging = directory / "backups" / f"restore-{uuid4().hex}"
    staging.mkdir()
    archive_path = staging / "source.zip"
    archive_path.write_bytes(content)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if sum(info.file_size for info in archive.infolist()) > 1024 * 1024 * 1024:
                raise ValueError("解压后超过 1GB")
            for info in archive.infolist():
                path = (staging / info.filename).resolve()
                if not path.is_relative_to(staging.resolve()):
                    raise ValueError("备份文件路径不正确")
                if info.filename != "workspace.db" and not info.filename.startswith(
                    ("uploads/", "generated/")
                ):
                    continue
                archive.extract(info, staging)
        snapshot = staging / "workspace.db"
        with sqlite3.connect(snapshot) as db:
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"profiles", "goals", "applications", "jobs", "resumes"} <= tables:
                raise ValueError("备份数据库版本不正确")
            if (
                db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or db.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("备份数据库关联检查失败")
            counts = {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ["applications", "jobs", "resumes"]
            }
        (directory / "pending-restore.json").write_text(
            json.dumps({"staging": str(staging)})
        )
        return {
            "ready": True,
            "counts": counts,
            "message": "备份校验通过，重启本地服务后恢复。当前数据会在切换前另行备份。",
        }
    except Exception as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise HTTPException(422, str(error)) from error


def apply_pending_restore():
    directory = settings().data_dir
    marker = directory / "pending-restore.json"
    if not marker.exists():
        return
    staging = Path(json.loads(marker.read_text())["staging"]).resolve()
    if not staging.is_relative_to((directory / "backups").resolve()):
        raise ValueError("恢复目录不正确")
    target = Path(make_url(settings().database_url).database).resolve()
    backup = directory / "backups" / f"before-restore-{uuid4().hex}.db"
    if target.exists():
        with sqlite3.connect(target) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
    for folder in ["uploads", "generated"]:
        if (staging / folder).exists():
            shutil.copytree(staging / folder, directory / folder, dirs_exist_ok=True)
    temporary = target.with_name(target.name + ".restore")
    shutil.copy2(staging / "workspace.db", temporary)
    # The server is stopped here. Remove only the old connection's WAL after its snapshot is preserved.
    for suffix in ["-wal", "-shm"]:
        target.with_name(target.name + suffix).unlink(missing_ok=True)
    temporary.replace(target)
    marker.unlink()
