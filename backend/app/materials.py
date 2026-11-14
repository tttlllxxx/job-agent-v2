import io
import textwrap
from pathlib import Path
from uuid import uuid4

import fitz
from docx import Document
from fastapi import HTTPException
from sqlalchemy import select

from .common import get
from .config import settings
from .database import Fact, Job, Material, MaterialVersion, Resume
from .providers import generate_json


def extract_text(content, suffix):
    if suffix == ".pdf":
        with fitz.open(stream=content, filetype="pdf") as document:
            return "\n".join(page.get_text() for page in document)
    if suffix == ".docx":
        return "\n".join(
            paragraph.text for paragraph in Document(io.BytesIO(content)).paragraphs
        )
    return content.decode("utf-8-sig")


def import_resume(db, name, content):
    suffix = Path(name).suffix.lower()
    if suffix not in [".pdf", ".docx", ".md", ".txt"]:
        raise HTTPException(422, "支持 PDF、DOCX、Markdown 和纯文本")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "文件超过 20MB")
    try:
        text = extract_text(content, suffix).strip()
    except Exception as error:
        raise HTTPException(422, "文件无法解析，请检查文件内容") from error
    if not text:
        raise HTTPException(422, "文件没有可读取文本，可上传文字版简历")
    path = settings().data_dir / "uploads" / f"{uuid4().hex}{suffix}"
    path.write_bytes(content)
    resume = Resume(
        name=name,
        path=str(path),
        media_type={
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }.get(suffix, "text/plain"),
        text=text,
    )
    db.add(resume)
    db.flush()
    for index, line in enumerate(
        [line.strip() for line in text.splitlines() if line.strip()]
    ):
        db.add(
            Fact(
                key=f"line.{index + 1}",
                value=line,
                resume_id=resume.id,
                source_ref=f"resume:{resume.id}",
                metadata_={"line": index + 1},
            )
        )
    if not db.scalar(select(Resume.id).where(Resume.active.is_(True))):
        resume.active = True
    db.commit()
    return resume


async def prepare(db, job_id, resume_id):
    job = get(db, Job, job_id)
    resume = get(db, Resume, resume_id)
    facts = list(
        db.scalars(
            select(Fact).where(
                Fact.resume_id == resume_id,
                Fact.confirmed.is_(True),
                Fact.active.is_(True),
            )
        )
    )
    material = Material(
        job_id=job.id,
        resume_id=resume.id,
        job_revision=job.revision,
        resume_revision=resume.revision,
        content=resume.text,
    )
    db.add(material)
    db.flush()
    if not facts:
        material.status = "needs_facts"
        db.commit()
        return material
    result = await generate_json(
        db,
        "根据已确认简历事实和 JD 提出具体表达修改。返回 suggestions 数组，每项含 id,original,proposed,reason,fact_ids。"
        "original 必须是简历中完整的原文片段，proposed 保持事实，只调整表达与组织。不得添加成绩、技能、任职或数字。"
        "缺少事实时返回 questions。",
        {
            "resume": resume.text,
            "jd": job.description,
            "facts": [{"id": fact.id, "text": fact.value} for fact in facts],
        },
    )
    allowed = {fact.id for fact in facts}
    suggestions = []
    for index, item in enumerate(result.get("suggestions", [])):
        refs = item.get("fact_ids", [])
        if (
            item.get("original")
            and item["original"] in resume.text
            and refs
            and set(refs) <= allowed
            and item.get("proposed")
        ):
            suggestions.append(
                {
                    "id": str(index + 1),
                    "original": item["original"],
                    "proposed": str(item["proposed"]),
                    "reason": str(item.get("reason", "")),
                    "fact_ids": refs,
                    "fact_evidence": [
                        {"id": fact.id, "revision": fact.revision, "text": fact.value}
                        for fact in facts
                        if fact.id in refs
                    ],
                    "decision": "pending",
                }
            )
    material.suggestions = suggestions
    material.status = "review"
    db.commit()
    return material


def final_content(material, resume):
    content = material.content or resume.text
    for suggestion in material.suggestions:
        if suggestion.get("decision") == "accepted":
            content = content.replace(
                suggestion["original"],
                suggestion.get("edited") or suggestion["proposed"],
                1,
            )
    return content


def save_version(db, material):
    resume = get(db, Resume, material.resume_id)
    content = final_content(material, resume)
    filename = uuid4().hex + ".md"
    path = settings().data_dir / "generated" / filename
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content)
    temporary.replace(path)
    version = MaterialVersion(
        material_id=material.id,
        content=content,
        path=str(path),
        data={
            "resume_id": resume.id,
            "resume_revision": material.resume_revision,
            "job_id": material.job_id,
            "job_revision": material.job_revision,
        },
    )
    db.add(version)
    material.status = "saved"
    db.flush()
    return version


def export_content(content, format):
    if format == "docx":
        document = Document()
        for line in content.splitlines():
            document.add_paragraph(line)
        result = io.BytesIO()
        document.save(result)
        return (
            result.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    if format == "pdf":
        document = fitz.open()
        remaining = (
            "\n".join(
                wrapped
                for line in content.splitlines()
                for wrapped in (textwrap.wrap(line, width=45) or [""])
            )
            or " "
        )
        while remaining:
            page = document.new_page()
            lines = remaining.splitlines()
            chunk = "\n".join(lines[:42])
            remaining = "\n".join(lines[42:])
            page.insert_textbox(
                fitz.Rect(40, 40, 555, 802), chunk, fontname="china-s", fontsize=10
            )
        return document.tobytes(), "application/pdf"
    return content.encode(), "text/markdown; charset=utf-8"
