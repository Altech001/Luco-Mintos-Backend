# type: ignore
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select, func

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    SmsHistory,
    SmsHistoryCreate,
    SmsHistoryUpdate,
    SmsHistoryPublic,
    SmsHistoriesPublic,
    Message,
)

router = APIRouter(prefix="/historysms", tags=["historysms"])


@router.post("/", response_model=SmsHistoryPublic)
def create_sms_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    history_in: SmsHistoryCreate,
) -> Any:
    h = SmsHistory(
        **history_in.model_dump(),
        user_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(h)
    session.commit()
    session.refresh(h)
    return h


@router.get("/", response_model=SmsHistoriesPublic)
def list_my_sms_history(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    delivery_status: str | None = None,
) -> Any:
    stmt = select(SmsHistory).where(SmsHistory.user_id == current_user.id)
    if status:
        stmt = stmt.where(SmsHistory.status == status)
    if delivery_status:
        stmt = stmt.where(SmsHistory.delivery_status == delivery_status)

    stmt = stmt.offset(skip).limit(limit).order_by(SmsHistory.created_at.desc())
    items = session.exec(stmt).all()

    count_stmt = select(func.count()).select_from(SmsHistory).where(
        SmsHistory.user_id == current_user.id
    )
    if status:
        count_stmt = count_stmt.where(SmsHistory.status == status)
    if delivery_status:
        count_stmt = count_stmt.where(SmsHistory.delivery_status == delivery_status)
    count = session.exec(count_stmt).one()

    return SmsHistoriesPublic(data=items, count=count)


@router.get("/all", response_model=SmsHistoriesPublic)
def list_all_sms_history(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    delivery_status: str | None = None,
) -> Any:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    stmt = select(SmsHistory)
    if status:
        stmt = stmt.where(SmsHistory.status == status)
    if delivery_status:
        stmt = stmt.where(SmsHistory.delivery_status == delivery_status)

    stmt = stmt.offset(skip).limit(limit).order_by(SmsHistory.created_at.desc())
    items = session.exec(stmt).all()

    count_stmt = select(func.count()).select_from(SmsHistory)
    if status:
        count_stmt = count_stmt.where(SmsHistory.status == status)
    if delivery_status:
        count_stmt = count_stmt.where(SmsHistory.delivery_status == delivery_status)
    count = session.exec(count_stmt).one()

    return SmsHistoriesPublic(data=items, count=count)


@router.get("/{history_id}", response_model=SmsHistoryPublic)
def get_sms_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    history_id: uuid.UUID,
) -> Any:
    h = session.get(SmsHistory, history_id)
    if not h:
        raise HTTPException(status_code=404, detail="SMS history not found")

    if h.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return h


@router.patch("/{history_id}", response_model=SmsHistoryPublic)
def update_sms_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    history_id: uuid.UUID,
    history_update: SmsHistoryUpdate,
) -> Any:
    h = session.get(SmsHistory, history_id)
    if not h:
        raise HTTPException(status_code=404, detail="SMS history not found")

    if h.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    update_data = history_update.model_dump(exclude_unset=True)

    # Normal users cannot change status/delivery_status
    if not current_user.is_superuser:
        allowed = {"external_id", "error_message"}
        update_data = {k: v for k, v in update_data.items() if k in allowed}

    for k, v in update_data.items():
        setattr(h, k, v)

    h.updated_at = datetime.utcnow()
    session.add(h)
    session.commit()
    session.refresh(h)
    return h


@router.delete("/{history_id}", response_model=Message)
def delete_sms_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    history_id: uuid.UUID,
) -> Any:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    h = session.get(SmsHistory, history_id)
    if not h:
        raise HTTPException(status_code=404, detail="SMS history not found")

    session.delete(h)
    session.commit()
    return Message(message="SMS history deleted successfully")


@router.get("/stats/summary", response_model=dict)
def sms_history_stats(
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    def count_where(*conds):
        return session.exec(
            select(func.count()).select_from(SmsHistory).where(*conds)
        ).one()

    if current_user.is_superuser:
        total = count_where()
        pending = count_where(SmsHistory.status == "pending")
        sent = count_where(SmsHistory.status == "sent")
        delivered = count_where(SmsHistory.status == "delivered")
        failed = count_where(SmsHistory.status == "failed")

        dl_pending = count_where(SmsHistory.delivery_status == "pending")
        dl_success = count_where(SmsHistory.delivery_status == "success")
        dl_failed = count_where(SmsHistory.delivery_status == "failed")
    else:
        total = count_where(SmsHistory.user_id == current_user.id)
        pending = count_where(
            SmsHistory.user_id == current_user.id, SmsHistory.status == "pending"
        )
        sent = count_where(
            SmsHistory.user_id == current_user.id, SmsHistory.status == "sent"
        )
        delivered = count_where(
            SmsHistory.user_id == current_user.id, SmsHistory.status == "delivered"
        )
        failed = count_where(
            SmsHistory.user_id == current_user.id, SmsHistory.status == "failed"
        )

        dl_pending = count_where(
            SmsHistory.user_id == current_user.id,
            SmsHistory.delivery_status == "pending",
        )
        dl_success = count_where(
            SmsHistory.user_id == current_user.id,
            SmsHistory.delivery_status == "success",
        )
        dl_failed = count_where(
            SmsHistory.user_id == current_user.id, SmsHistory.delivery_status == "failed"
        )

    return {
        "total": total,
        "status": {
            "pending": pending,
            "sent": sent,
            "delivered": delivered,
            "failed": failed,
        },
        "delivery_status": {
            "pending": dl_pending,
            "success": dl_success,
            "failed": dl_failed,
        },
    }