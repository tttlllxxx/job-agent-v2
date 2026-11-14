from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from .database import Operation, serialize


def get(db, model, row_id):
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(404, "记录不存在")
    return row


def revise(row, changes, expected_revision=None):
    if expected_revision is not None and expected_revision != row.revision:
        raise HTTPException(
            409,
            {
                "code": "REVISION_CONFLICT",
                "message": "记录已更新，请核对最新内容",
                "current": serialize(row),
            },
        )
    for key, value in changes.items():
        setattr(row, key, value)
    row.revision += 1
    return row


def existing_operation(db, key, request):
    if not key:
        raise HTTPException(422, "缺少 operation_id")
    prior = db.get(Operation, key)
    if prior and prior.request != request:
        raise HTTPException(409, "相同操作编号对应了不同内容")
    return prior.result if prior else None


def commit_operation(db, key, request, result):
    db.add(Operation(key=key, request=request, result=result))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = existing_operation(db, key, request)
        if prior is None:
            raise
        return prior
    return result
