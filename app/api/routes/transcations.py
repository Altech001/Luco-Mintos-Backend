# type: ignore
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select, func

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Transaction,
    TransactionCreate,
    TransactionUpdate,
    TransactionPublic,
    TransactionsPublic,
    Message,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/", response_model=TransactionPublic)
def create_transaction(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    transaction_in: TransactionCreate,
) -> Any:
    tx = Transaction(
        **transaction_in.model_dump(),
        user_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


@router.get("/", response_model=TransactionsPublic)
def list_my_transactions(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    transaction_type: str | None = None,
) -> Any:
    stmt = select(Transaction).where(Transaction.user_id == current_user.id)

    if status:
        stmt = stmt.where(Transaction.status == status)
    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)

    stmt = stmt.offset(skip).limit(limit).order_by(Transaction.created_at.desc())
    items = session.exec(stmt).all()

    count_stmt = select(func.count()).select_from(Transaction).where(
        Transaction.user_id == current_user.id
    )
    if status:
        count_stmt = count_stmt.where(Transaction.status == status)
    if transaction_type:
        count_stmt = count_stmt.where(Transaction.transaction_type == transaction_type)
    count = session.exec(count_stmt).one()

    return TransactionsPublic(data=items, count=count)


@router.get("/all", response_model=TransactionsPublic)
def list_all_transactions(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    transaction_type: str | None = None,
) -> Any:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    stmt = select(Transaction)
    if status:
        stmt = stmt.where(Transaction.status == status)
    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)

    stmt = stmt.offset(skip).limit(limit).order_by(Transaction.created_at.desc())
    items = session.exec(stmt).all()

    count_stmt = select(func.count()).select_from(Transaction)
    if status:
        count_stmt = count_stmt.where(Transaction.status == status)
    if transaction_type:
        count_stmt = count_stmt.where(Transaction.transaction_type == transaction_type)
    count = session.exec(count_stmt).one()

    return TransactionsPublic(data=items, count=count)


@router.get("/{transaction_id}", response_model=TransactionPublic)
def get_transaction(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    transaction_id: uuid.UUID,
) -> Any:
    tx = session.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return tx


@router.patch("/{transaction_id}", response_model=TransactionPublic)
def update_transaction(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    transaction_id: uuid.UUID,
    transaction_update: TransactionUpdate,
) -> Any:
    tx = session.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    update_data = transaction_update.model_dump(exclude_unset=True)

    # Normal users cannot change status
    if not current_user.is_superuser:
        # Allow only description and reference_number
        allowed = {"description", "reference_number"}
        update_data = {k: v for k, v in update_data.items() if k in allowed}

    for k, v in update_data.items():
        setattr(tx, k, v)

    tx.updated_at = datetime.utcnow()
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


@router.delete("/{transaction_id}", response_model=Message)
def delete_transaction(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    transaction_id: uuid.UUID,
) -> Any:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    tx = session.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    session.delete(tx)
    session.commit()
    return Message(message="Transaction deleted successfully")


@router.get("/stats/summary", response_model=dict)
def transaction_stats(
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    def count_where(*conds):
        return session.exec(
            select(func.count()).select_from(Transaction).where(*conds)
        ).one()

    if current_user.is_superuser:
        total = count_where()
        pending = count_where(Transaction.status == "pending")
        completed = count_where(Transaction.status == "completed")
        failed = count_where(Transaction.status == "failed")
        cancelled = count_where(Transaction.status == "cancelled")

        credit = count_where(Transaction.transaction_type == "credit")
        debit = count_where(Transaction.transaction_type == "debit")
        payment = count_where(Transaction.transaction_type == "payment")
        refund = count_where(Transaction.transaction_type == "refund")
    else:
        total = count_where(Transaction.user_id == current_user.id)
        pending = count_where(
            Transaction.user_id == current_user.id, Transaction.status == "pending"
        )
        completed = count_where(
            Transaction.user_id == current_user.id, Transaction.status == "completed"
        )
        failed = count_where(
            Transaction.user_id == current_user.id, Transaction.status == "failed"
        )
        cancelled = count_where(
            Transaction.user_id == current_user.id, Transaction.status == "cancelled"
        )

        credit = count_where(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == "credit",
        )
        debit = count_where(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == "debit",
        )
        payment = count_where(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == "payment",
        )
        refund = count_where(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == "refund",
        )

    return {
        "total": total,
        "status": {
            "pending": pending,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
        },
        "type": {"credit": credit, "debit": debit, "payment": payment, "refund": refund},
    }